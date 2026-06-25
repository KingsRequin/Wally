from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

OWNER_DISCORD_ID = "610550333042589752"

# Durée typique estimée d'un run Claude, sert UNIQUEMENT à calculer un pourcentage
# d'avancement indicatif (Claude -p n'émet rien avant la fin → estimation temporelle).
_PROGRESS_EST_SECONDS = 300.0

# Cadrage d'ingénierie préfixé à CHAQUE goal envoyé à Claude Code. Garantit un bon
# framing même si Wally rédige un goal moyen (et empêche les hallucinations du type
# « la fonction existe déjà » : on force la vérification de l'état réel du code).
_GOAL_PREAMBLE = (
    "Tu modifies le code du bot Discord/Twitch « Wally » (Python, asyncio). "
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
                 approval_timeout: float = 3600.0) -> None:
        self._bridge = bridge
        self._bot = bot
        self._poll_interval = poll_interval
        self._approval_timeout = approval_timeout
        self._pending = False
        self._declined: set[str] = set()

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
        self._pending = True
        try:
            await self._run_upgrade(goal, norm)
        except Exception as e:  # noqa: BLE001 — jamais d'échec silencieux
            logger.exception("self-upgrade a échoué")
            await self._notify(f"❌ Ma tentative d'auto-modification a échoué : {e}")
            await self._record_outcome(
                goal, f"A échoué techniquement ({e}) — non déployé, demande close."
            )
        finally:
            self._pending = False

    async def _run_upgrade(self, goal: str, norm: str) -> None:
        owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
        dm = await owner.create_dm()
        msg = await dm.send(
            "🧠 **J'ai repéré une faiblesse que je voudrais corriger :**\n"
            f"> {goal}\n\n"
            "Si tu autorises, **Claude Code** va modifier mon code dans ce sens "
            "(en autonomie), puis je redémarre avec la nouvelle version.\n"
            "✅ autoriser · ❌ refuser · _(timeout 1h)_"
        )
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")

        try:
            emoji = await self._await_reaction(msg, timeout=self._approval_timeout)
        except asyncio.TimeoutError:
            await dm.send("⏱ Pas de réponse — j'abandonne cette idée.")
            self._declined.add(norm)
            await self._record_outcome(
                goal, "Aucune réponse de KingsRequin (timeout) — demande abandonnée, "
                "ce n'est plus en attente d'autorisation."
            )
            return

        if emoji != "✅":
            await dm.send("❌ Ok, je laisse tomber. Je ne te le reproposerai pas.")
            self._declined.add(norm)
            await self._record_outcome(
                goal, "Refusé par KingsRequin — abandonné, ne plus le reproposer ni l'attendre."
            )
            return

        await dm.send("👍 C'est parti, Claude Code travaille… (ça peut prendre quelques minutes)")
        await self._record_outcome(
            goal, "Accepté par KingsRequin — Claude Code l'implémente. Ce n'est plus "
            "en attente d'autorisation."
        )
        job_id = await self._bridge.claude_run(_GOAL_PREAMBLE + goal)

        # Message d'avancement unique, édité au fil de l'eau (pas de spam).
        prog_msg = await dm.send("⏳ Avancement estimé : ~5 %")

        async def _progress(elapsed: float) -> None:
            pct = min(95, max(5, int(100 * elapsed / _PROGRESS_EST_SECONDS)))
            try:
                await prog_msg.edit(content=f"⏳ Claude Code bosse… avancement estimé : ~{pct} %")
            except Exception:  # noqa: BLE001 — l'affichage ne doit jamais casser le flux
                pass

        status = await self._poll(job_id, progress=_progress)
        if status is None:
            await dm.send("❌ Claude Code n'a pas répondu à temps — j'abandonne.")
            await self._record_outcome(
                goal, "Accepté mais Claude Code n'a pas répondu à temps — non déployé, à reproposer."
            )
            return
        if status.get("state") != "done":
            tail = (status.get("output_tail") or "")[-500:]
            await dm.send(
                f"❌ Claude Code a échoué (exit {status.get('exit_code')}).\n```\n{tail}\n```"
            )
            await self._record_outcome(
                goal, "Accepté mais Claude Code a échoué — non déployé, à reproposer."
            )
            return
        if not status.get("changed") and not status.get("head_changed"):
            result = (status.get("result") or "").strip()[:500]
            await dm.send(f"🤔 Finalement aucun changement de code.\n{result}")
            await self._record_outcome(
                goal, "Accepté mais aucun changement de code n'était nécessaire — clôturé."
            )
            return

        try:
            await prog_msg.edit(content="⏳ Claude a fini — application + rebuild… ~100 %")
        except Exception:  # noqa: BLE001
            pass
        await self._bridge.claude_commit(job_id)
        await self._bridge.docker_rebuild("wally")
        prefix = (
            "✅ **C'est implémenté et déployé !** Je redémarre avec la nouvelle "
            "version (~2 min).\n\n"
        )
        result = (status.get("result") or "").strip()
        budget = 1900 - len(prefix)  # Discord plafonne à 2000 caractères
        if len(result) > budget:
            result = result[:budget].rstrip() + " …(résumé tronqué)"
        await dm.send(prefix + result)
        await self._record_outcome(
            goal, "Accepté par KingsRequin, implémenté par Claude Code et déployé. "
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
            owner = await self._bot.fetch_user(int(OWNER_DISCORD_ID))
            dm = await owner.create_dm()
            await dm.send(text)
        except Exception:  # noqa: BLE001
            logger.exception("self-upgrade: impossible de notifier le créateur en DM")

    async def _await_reaction(self, msg, timeout: float) -> str:
        def check(reaction, user):
            return (
                str(user.id) == OWNER_DISCORD_ID
                and str(reaction.emoji) in ("✅", "❌")
                and reaction.message.id == msg.id
            )
        reaction, _ = await self._bot.wait_for("reaction_add", check=check, timeout=timeout)
        return str(reaction.emoji)
