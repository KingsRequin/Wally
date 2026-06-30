from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from bot.intelligence.identity import render_identity, creator_name, bot_name
from bot.intelligence.upgrade_registry import (
    UpgradeRegistry, DELIVERED, DECLINED, ABANDONED,
)

# Durée typique estimée d'un run Claude, sert UNIQUEMENT à calculer un pourcentage
# d'avancement indicatif (Claude -p n'émet rien avant la fin → estimation temporelle).
_PROGRESS_EST_SECONDS = 300.0

# Seuils d'avancement (%) republiés dans le cognitive_feed pendant un run self-mod.
# Un seul event par palier franchi → le run reste visible sur le site sans noyer
# le feed (buffer de 30 events).
_FEED_THRESHOLDS = (25, 50, 75)


def _next_threshold_crossed(pct: int, last: int) -> int | None:
    """Plus haut seuil de _FEED_THRESHOLDS franchi par `pct` et pas encore publié
    (strictement > last), ou None. Garantit un event par palier."""
    crossed = [t for t in _FEED_THRESHOLDS if last < t <= pct]
    return max(crossed) if crossed else None


# Cadrage d'ingénierie préfixé à CHAQUE goal envoyé à Claude Code. Garantit un bon
# framing même si Wally rédige un goal moyen (et empêche les hallucinations du type
# « la fonction existe déjà » : on force la vérification de l'état réel du code).
_GOAL_PREAMBLE = (
    "Tu modifies le code du bot Discord/Twitch « {{BOT_NAME}} » (Python, asyncio). "
    "AVANT de coder : vérifie l'état RÉEL du code — ne te fie PAS aux suppositions "
    "de la demande (une fonction ou un fichier présenté comme « déjà prêt » peut très "
    "bien ne pas exister). Implémente DIRECTEMENT, ne te contente pas d'analyser ou de "
    "proposer. Lance la suite de tests (python3 -m pytest -q) et ne casse rien (échecs "
    "pré-existants à ignorer : tests/test_web_search.py::test_complete_with_tools_logs_cost "
    "et tests/test_dashboard_costs.py). Ajoute des tests pour ton code. Respecte le style "
    "du projet : loguru (jamais print), async. Ne touche pas à public-ui/.\n\n"
    "=== Objectif demandé ===\n"
)


@dataclass
class UpgradeRequest:
    goal: str


class SelfFix:
    """Wally décide de se modifier ; le créateur autorise en DM ; Claude Code exécute."""

    def __init__(self, bridge, bot, *, poll_interval: float = 10.0,
                 approval_timeout: float = 72 * 3600.0,
                 registry: UpgradeRegistry | None = None, gate=None) -> None:
        self._bridge = bridge
        self._bot = bot
        self._poll_interval = poll_interval
        self._approval_timeout = approval_timeout
        self._pending = False
        self._declined: set[str] = set()
        # Registre durable des demandes (Phase 6) : mémoire de ce que Wally a
        # déjà demandé / obtenu → garde anti-redemande + injection dans le contexte.
        self._registry = registry
        # Gate de sollicitation owner (un seul fil à la fois). None → pas de gate.
        self._gate = gate
        # Goal de l'upgrade en cours (#observability A4) : permet à _set_status de
        # publier l'issue (acceptée/refusée/déployée) sur le feed cognitif.
        self._active_goal: str | None = None
        # Dernier palier d'avancement publié sur le feed pour le run en cours
        # (réinitialisé à chaque nouvelle demande). Évite de republier le même palier.
        self._last_feed_pct: int = 0

    async def _set_status(self, upgrade_id: int | None, status: str) -> None:
        """Met à jour le statut d'une demande dans le registre et publie l'issue
        sur le feed cognitif (#observability A4). Best-effort : ne propage jamais."""
        # Publication feed (indépendante du registre) : rend l'auto-modification
        # visible de bout en bout sur le site (demande → acceptée/refusée/déployée).
        goal = self._active_goal or ""
        feed = getattr(self._bot, "cognitive_feed", None)
        if feed is not None and goal:
            _labels = {DELIVERED: "déployée", DECLINED: "refusée", ABANDONED: "abandonnée"}
            label = _labels.get(status, status)
            try:
                feed.publish({
                    "type": "CODEFIX",
                    "detail": f"auto-modif {label} : {goal[:200]}",
                    "full": goal,
                })
            except Exception as e:  # noqa: BLE001 — le feed ne doit jamais casser le flux
                logger.warning("self-fix feed.publish échoué: {}", e)
        if self._registry is None or upgrade_id is None:
            return
        try:
            await self._registry.set_status(upgrade_id, status)
        except Exception:  # noqa: BLE001 — le suivi ne doit jamais casser le flux
            logger.exception("self-fix: maj statut registre #{} échouée", upgrade_id)

    def _publish_feed(self, detail: str, full: str | None = None) -> None:
        """Publie un jalon de self-modification dans le cognitive_feed (type CODEFIX).
        Best-effort : ne propage jamais (le feed ne doit pas casser le flux self-fix)."""
        feed = getattr(self._bot, "cognitive_feed", None)
        if feed is None:
            return
        try:
            evt = {"type": "CODEFIX", "detail": detail}
            if full:
                evt["full"] = full
            feed.publish(evt)
        except Exception as e:  # noqa: BLE001 — le feed ne doit jamais casser le flux
            logger.debug("self-fix CODEFIX publish échoué: {}", e)

    def _maybe_publish_progress(self, pct: int) -> None:
        """Publie un jalon de progression au franchissement d'un palier (25/50/75 %)."""
        t = _next_threshold_crossed(pct, self._last_feed_pct)
        if t is not None:
            self._last_feed_pct = t
            self._publish_feed(f"auto-modif en cours — avancement estimé ~{t} %")

    def _owner_id(self) -> str:
        """Lit l'ID Discord du créateur depuis config.bot.owner_discord_id."""
        cfg = getattr(self._bot, "config", None)
        return getattr(getattr(cfg, "bot", None), "owner_discord_id", "") or ""

    def _service(self) -> str:
        """Dérive le nom du service Docker depuis config.bot.name (fallback 'wally')."""
        name = getattr(getattr(getattr(self._bot, "config", None), "bot", None), "name", "") or "wally"
        return name.lower()

    async def request_upgrade(self, req: UpgradeRequest, *, force: bool = False) -> None:
        # force=True : demande explicite du créateur en conversation → on outrepasse
        # le filtre _declined (sinon un goal déjà refusé serait ignoré en silence).
        goal = (req.goal or "").strip()
        if not goal:
            return
        if self._pending:
            logger.info("self-upgrade ignoré: un upgrade est déjà en attente")
            return
        norm = goal.lower()
        if not force and norm in self._declined:
            logger.info("self-upgrade ignoré: goal déjà refusé — {}", goal[:60])
            return
        # Garde anti-redemande (Phase 6d) : si une demande sémantiquement proche
        # est déjà en cours (requested) ou déjà livrée (delivered), ne pas
        # redemander — Wally l'a déjà. `force` (demande explicite du créateur)
        # outrepasse la garde.
        if not force and self._registry is not None:
            try:
                hit = await self._registry.find_similar(goal)
            except Exception:  # noqa: BLE001 — la garde ne doit jamais bloquer le flux
                logger.exception("self-fix: recherche anti-redemande échouée")
                hit = None
            if hit is not None:
                logger.info("self-upgrade ignoré: déjà {} (#{}) — {}", hit.status, hit.id, goal[:60])
                await self._record_outcome(
                    goal, f"Déjà {hit.status} (demande #{hit.id} : « {hit.proposal[:120]} ») — "
                    "inutile de le redemander."
                )
                return
        # Un seul fil de sollicitation owner à la fois : si un MP attend déjà sa
        # réponse, on diffère sans envoyer — la cognition re-soulèvera plus tard.
        if not force and self._gate is not None and self._gate.is_blocked():
            logger.info("self-fix différé : une sollicitation owner est déjà en attente")
            await self._record_outcome(
                goal, "Différé — une autre sollicitation vers le créateur attend déjà sa "
                "réponse ; à re-soulever plus tard."
            )
            return
        self._pending = True
        self._active_goal = goal   # suivi de l'issue sur le feed (#observability A4)
        self._last_feed_pct = 0
        self._publish_feed(f"Wally veut se modifier : {goal[:200]}", full=goal)
        upgrade_id: int | None = None
        try:
            if self._registry is not None:
                try:
                    upgrade_id = await self._registry.record_request(goal)
                except Exception:  # noqa: BLE001
                    logger.exception("self-fix: enregistrement de la demande échoué")
            await self._run_upgrade(goal, norm, upgrade_id)
        except Exception as e:  # noqa: BLE001 — jamais d'échec silencieux
            logger.exception("self-upgrade a échoué")
            await self._set_status(upgrade_id, ABANDONED)
            await self._notify(f"❌ Ma tentative d'auto-modification a échoué : {e}")
            await self._record_outcome(
                goal, f"A échoué techniquement ({e}) — non déployé, demande close."
            )
        finally:
            self._pending = False

    async def _run_upgrade(self, goal: str, norm: str, upgrade_id: int | None = None) -> None:
        oid = self._owner_id()
        if not oid:
            logger.warning("self-upgrade: owner_discord_id non configuré — abandon")
            return
        owner = await self._bot.fetch_user(int(oid))
        dm = await owner.create_dm()
        msg = await dm.send(
            "🧠 **J'ai repéré une faiblesse que je voudrais corriger :**\n"
            f"> {goal}\n\n"
            "Si tu autorises, **Claude Code** va modifier mon code dans ce sens "
            "(en autonomie), puis je redémarre avec la nouvelle version.\n"
            "✅ autoriser · ❌ refuser · _(prends ton temps)_"
        )
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
        self._remember_in_dm(dm, f"[demande de self-fix] {goal}")
        # Un fil de sollicitation owner est désormais ouvert.
        if self._gate is not None:
            self._gate.mark_sent()

        try:
            emoji = await self._await_reaction(msg, timeout=self._approval_timeout)
        except asyncio.TimeoutError:
            # Plus d'auto-refus : la demande n'est ni refusée ni blacklistée. Elle
            # est simplement mise de côté (re-proposable). Pas de message « j'abandonne ».
            await self._set_status(upgrade_id, ABANDONED)
            self._remember_in_dm(dm, f"[self-fix en attente — pas encore de réponse] {goal}")
            await self._record_outcome(
                goal, f"Pas encore de réponse de {creator_name()} — demande mise de côté, "
                "ni refusée ni abandonnée définitivement ; à re-soulever plus tard."
            )
            return

        if emoji != "✅":
            await dm.send("❌ Ok, je laisse tomber. Je ne te le reproposerai pas.")
            self._declined.add(norm)
            await self._set_status(upgrade_id, DECLINED)
            self._remember_in_dm(dm, f"[self-fix refusé] {goal}")
            await self._record_outcome(
                goal, f"Refusé par {creator_name()} — abandonné, ne plus le reproposer ni l'attendre."
            )
            return

        await dm.send("👍 C'est parti, Claude Code travaille… (ça peut prendre quelques minutes)")
        self._remember_in_dm(dm, f"[self-fix accepté] {goal}")
        await self._record_outcome(
            goal, f"Accepté par {creator_name()} — Claude Code l'implémente. Ce n'est plus "
            "en attente d'autorisation."
        )
        job_id = await self._bridge.claude_run(render_identity(_GOAL_PREAMBLE + goal))
        self._publish_feed("validé par le créateur — Claude Code démarre")

        # Message d'avancement unique, édité au fil de l'eau (pas de spam).
        prog_msg = await dm.send("⏳ Avancement estimé : ~5 %")

        async def _progress(elapsed: float) -> None:
            pct = min(95, max(5, int(100 * elapsed / _PROGRESS_EST_SECONDS)))
            try:
                await prog_msg.edit(content=f"⏳ Claude Code bosse… avancement estimé : ~{pct} %")
            except Exception:  # noqa: BLE001 — l'affichage ne doit jamais casser le flux
                pass
            self._maybe_publish_progress(pct)

        status = await self._poll(job_id, progress=_progress)
        if status is None:
            await dm.send("❌ Claude Code n'a pas répondu à temps — j'abandonne.")
            await self._set_status(upgrade_id, ABANDONED)
            self._remember_in_dm(dm, f"[self-fix abandonné — Claude Code n'a pas répondu] {goal}")
            await self._record_outcome(
                goal, "Accepté mais Claude Code n'a pas répondu à temps — non déployé, à reproposer."
            )
            return
        if status.get("state") != "done":
            tail = (status.get("output_tail") or "")[-500:]
            await dm.send(
                f"❌ Claude Code a échoué (exit {status.get('exit_code')}).\n```\n{tail}\n```"
            )
            await self._set_status(upgrade_id, ABANDONED)
            self._remember_in_dm(dm, f"[self-fix échoué] {goal}")
            await self._record_outcome(
                goal, "Accepté mais Claude Code a échoué — non déployé, à reproposer."
            )
            return
        if not status.get("changed") and not status.get("head_changed"):
            result = (status.get("result") or "").strip()[:500]
            await dm.send(f"🤔 Finalement aucun changement de code.\n{result}")
            # Aucun changement nécessaire = la capacité existe déjà → DELIVERED
            # (clôturé, ne pas redemander).
            await self._set_status(upgrade_id, DELIVERED)
            self._remember_in_dm(dm, f"[self-fix sans changement] {goal}")
            await self._record_outcome(
                goal, "Accepté mais aucun changement de code n'était nécessaire — clôturé."
            )
            return

        try:
            await prog_msg.edit(content="⏳ Claude a fini — application + rebuild… ~100 %")
        except Exception:  # noqa: BLE001
            pass
        self._publish_feed("Claude a fini — application + rebuild en cours")
        await self._bridge.claude_commit(job_id)
        await self._bridge.docker_rebuild(self._service())
        prefix = (
            "✅ **C'est implémenté et déployé !** Je redémarre avec la nouvelle "
            "version (~2 min).\n\n"
        )
        result = (status.get("result") or "").strip()
        budget = 1900 - len(prefix)  # Discord plafonne à 2000 caractères
        if len(result) > budget:
            result = result[:budget].rstrip() + " …(résumé tronqué)"
        await dm.send(prefix + result)
        await self._set_status(upgrade_id, DELIVERED)
        self._remember_in_dm(dm, f"[self-fix déployé] {goal}")
        await self._record_outcome(
            goal, f"Accepté par {creator_name()}, implémenté par Claude Code et déployé. "
            "Objectif ATTEINT — ne plus l'attendre ni le considérer en attente d'autorisation."
        )

    async def _poll(self, job_id: str, progress=None, max_wait: float = 1800.0) -> dict | None:
        waited = 0.0
        while waited <= max_wait:
            await asyncio.sleep(self._poll_interval)
            waited += self._poll_interval if self._poll_interval > 0 else 1.0
            status = await self._bridge.claude_status(job_id)
            if status.get("state") != "running":
                return status
            if progress is not None:
                await progress(waited)
        return None

    def _remember_in_dm(self, dm, text: str) -> None:
        """Injecte un message du flux self-fix dans le sliding context window du
        DM créateur, pour que Wally en garde la trace conversationnelle et puisse
        en reparler. Best-effort : ne propage jamais.
        """
        try:
            memory = getattr(self._bot, "memory", None)
            if memory is None:
                return
            memory.append_message(str(dm.id), bot_name(), text, platform="discord")
        except Exception:  # noqa: BLE001 — la trace ne doit jamais casser le flux
            logger.exception("self-fix: impossible d'inscrire le message dans l'historique DM")

    async def _record_outcome(self, goal: str, outcome: str) -> None:
        """Réinjecte l'issue d'un code_fix dans la mémoire de Wally (wally:self).

        Sans ce retour, le flux d'autorisation DM est totalement découplé de la
        cognition : le goal qui a déclenché le code_fix reste « en attente
        d'autorisation » et Wally rumine la demande indéfiniment, même après
        acceptation et déploiement (le flag _pending est en mémoire seule, perdu
        au restart qui suit le déploiement). Best-effort : ne propage jamais.
        """
        try:
            memory = getattr(self._bot, "memory", None)
            store = getattr(memory, "fact_store", None) if memory is not None else None
            if store is None:
                return
            from bot.intelligence.memory.facts import AtomicFact, FactCategory
            now = datetime.utcnow()
            await store.add(AtomicFact(
                user_id="wally:self",
                content=f"[code_fix] {outcome} — demande : « {goal[:200]} »",
                category=FactCategory.THOUGHT,
                source="self_fix",
                importance=0.9,
                confidence=1.0,
                created_at=now,
                last_seen_at=now,
            ))
        except Exception:  # noqa: BLE001 — l'enregistrement ne doit jamais casser le flux
            logger.exception("self-fix: impossible d'enregistrer l'issue en mémoire")

    async def _notify(self, text: str) -> None:
        """DM best-effort au créateur. Ne propage jamais."""
        try:
            oid = self._owner_id()
            if not oid:
                logger.warning("self-upgrade: owner_discord_id non configuré — notification ignorée")
                return
            owner = await self._bot.fetch_user(int(oid))
            dm = await owner.create_dm()
            await dm.send(text)
        except Exception:  # noqa: BLE001
            logger.exception("self-upgrade: impossible de notifier le créateur en DM")

    async def _await_reaction(self, msg, timeout: float) -> str:
        owner_id = self._owner_id()

        def check(reaction, user):
            return (
                str(user.id) == owner_id
                and str(reaction.emoji) in ("✅", "❌")
                and reaction.message.id == msg.id
            )
        reaction, _ = await self._bot.wait_for("reaction_add", check=check, timeout=timeout)
        return str(reaction.emoji)
