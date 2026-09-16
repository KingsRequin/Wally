"""Tests du journal des membres — arrivées, départs, sanctions, surnoms, rôles.

Le recoupement d'audit lui-même (`entree_audit`) est déjà testé à fond dans
`tests/discord/test_journal_moderation.py` (T2) : ces tests-ci vérifient
seulement la construction des cartes et le câblage (bots exclus, garde-fous,
budget Components V2), avec un faux journal d'audit qui filtre par ACTION —
`journal_membres` interroge plusieurs actions différentes (`ban`, `kick`,
`unban`, `member_update`, `member_role_update`) pour un même événement, ce que
le `_FauxAudit` de T2 (une seule action par test) n'a pas besoin de faire.
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from bot.core.temps import maintenant
from bot.discord import journal_membres as jmb
from bot.discord import journal_moderation as jm

LOGS, LOGS2, COMMU = 70, 71, 9


class _FauxAudit:
    """Un serveur factice dont on lit le journal d'audit, filtré par ACTION.

    Contrairement au `_FauxAudit` de `test_journal_moderation.py` (T2), celui-
    ci filtre réellement `self.entrees` par `action` — `journal_membres`
    interroge plusieurs actions pour un même événement (ban PUIS kick au
    départ ; member_update ET member_role_update à la modification), et sans
    ce filtre une entrée de kick apparaîtrait à tort comme une entrée de ban.
    """

    def __init__(self, entrees=(), *, refuse=False, id=COMMU):
        self.id = id
        self.entrees = list(entrees)
        self.refuse = refuse
        self.appels: list[tuple[int, discord.AuditLogAction]] = []

    def audit_logs(self, *, limit, action):
        self.appels.append((limit, action))
        pertinentes = [e for e in self.entrees if e.action == action][:limit]
        refuse = self.refuse

        async def _iterer():
            if refuse:
                raise discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "audit")
            for entree in pertinentes:
                yield entree

        return _iterer()


def _entree(*, action, id=1, modo_id=999, cible_id=1, age=0.0, raison=None):
    return SimpleNamespace(
        id=id, action=action, user=SimpleNamespace(id=modo_id), target=SimpleNamespace(id=cible_id),
        extra=None, reason=raison, created_at=maintenant() - timedelta(seconds=age),
    )


def _etat_audit_neuf() -> None:
    """Les compteurs et les serveurs déjà signalés vivent en RAM, par module
    (`journal_moderation`, partagé par le recoupement d'audit)."""
    jm._compteurs_audit.clear()
    jm._audit_refuse.clear()


def _salon_logs(sid):
    return SimpleNamespace(id=sid, send=AsyncMock())


def _bot(salon_ids=(LOGS,), guild_ids=(COMMU,), *, inclure_bots=False, audit=None):
    salons = {sid: _salon_logs(sid) for sid in salon_ids}
    cfg = SimpleNamespace(salon_ids=list(salon_ids), guild_ids=list(guild_ids), inclure_bots=inclure_bots)
    bot = SimpleNamespace(config=SimpleNamespace(discord=SimpleNamespace(journal_moderation=cfg)))
    bot.get_channel = lambda cid: salons.get(cid)
    bot.get_guild = lambda gid: audit if gid in guild_ids else None
    logs = salons[salon_ids[0]] if salon_ids else _salon_logs(LOGS)
    return bot, logs


def _guild(gid=COMMU):
    return SimpleNamespace(id=gid)


def _role(id, nom):
    return SimpleNamespace(id=id, name=nom)


def _membre(*, id=1, nom="alice", bot=False, age_compte_jours=999.0, roles=(), nick=None,
            timed_out_until=None, joined_at=None, guild=None):
    return SimpleNamespace(
        id=id, name=nom, bot=bot, nick=nick,
        created_at=maintenant() - timedelta(days=age_compte_jours),
        roles=list(roles), timed_out_until=timed_out_until, joined_at=joined_at,
        guild=guild or _guild(),
        display_avatar=SimpleNamespace(url="https://cdn/avatar.png"),
    )


async def _sans_sommeil(_secondes: float) -> None:
    """Le sommeil de `_DELAI_AUDIT`, ramené à zéro pour les tests."""


async def _fond() -> None:
    """Attend les tâches de fond lancées par le journal (`_fire`)."""
    from bot.discord.handlers import _bg_tasks
    for _ in range(5):
        taches = list(_bg_tasks)
        if not taches:
            return
        await asyncio.gather(*taches)
        await asyncio.sleep(0)


def _vue(logs, appel=0):
    return logs.send.await_args_list[appel].kwargs["view"]


def _textes(vue) -> list[str]:
    return [c.content for c in vue.walk_children() if isinstance(c, discord.ui.TextDisplay)]


def _longueur_totale(vue) -> int:
    return sum(len(t) for t in _textes(vue))


# ---------------------------------------------------------------------------
# #8 — arrivée


async def test_arrivee_publie_une_carte_avec_age_du_compte():
    bot, logs = _bot()
    membre = _membre(id=1, age_compte_jours=30)

    await jmb.membre_rejoint(bot, membre)

    texte = "\n".join(_textes(_vue(logs)))
    assert "📥 Nouveau membre" in texte
    assert "<@1>" in texte
    assert "Compte récent" not in texte


async def test_arrivee_compte_recent_porte_le_badge():
    bot, logs = _bot()
    membre = _membre(id=1, age_compte_jours=2)

    await jmb.membre_rejoint(bot, membre)

    texte = "\n".join(_textes(_vue(logs)))
    assert "⚠️" in texte
    assert "Compte récent" in texte


async def test_arrivee_bot_exclu_par_defaut():
    bot, logs = _bot()
    membre = _membre(id=1, bot=True)

    await jmb.membre_rejoint(bot, membre)

    logs.send.assert_not_awaited()


async def test_arrivee_bot_inclus_si_configure():
    bot, logs = _bot(inclure_bots=True)
    membre = _membre(id=1, bot=True)

    await jmb.membre_rejoint(bot, membre)

    logs.send.assert_awaited_once()


async def test_arrivee_hors_guild_configuree_ne_publie_rien():
    bot, logs = _bot(guild_ids=(4242,))
    membre = _membre(id=1, guild=_guild(COMMU))

    await jmb.membre_rejoint(bot, membre)

    logs.send.assert_not_awaited()


async def test_arrivee_journal_desactive_ne_publie_rien():
    bot, logs = _bot(salon_ids=())
    membre = _membre(id=1)

    await jmb.membre_rejoint(bot, membre)

    logs.send.assert_not_awaited()


# ---------------------------------------------------------------------------
# #8 — départ (expulsion / volontaire), sans doublon avec un ban


async def test_depart_volontaire_sans_entree_audit():
    _etat_audit_neuf()
    audit = _FauxAudit([])
    bot, logs = _bot(audit=audit)
    user = _membre(id=1, joined_at=maintenant() - timedelta(days=10))
    payload = SimpleNamespace(guild_id=COMMU, user=user)

    await jmb.membre_parti(bot, payload, dormir=_sans_sommeil)
    await _fond()

    texte = "\n".join(_textes(_vue(logs)))
    assert "🚪 Départ" in texte
    assert "Membre depuis" in texte


async def test_depart_hors_cache_sans_membre_depuis():
    """`payload.user` hors cache : un `discord.User` simple, sans `joined_at`."""
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    user = SimpleNamespace(id=1, name="fantome", bot=False)
    payload = SimpleNamespace(guild_id=COMMU, user=user)

    await jmb.membre_parti(bot, payload, dormir=_sans_sommeil)
    await _fond()

    texte = "\n".join(_textes(_vue(logs)))
    assert "Membre depuis" not in texte


async def test_depart_avec_entree_kick_devient_expulsion():
    _etat_audit_neuf()
    audit = _FauxAudit([_entree(action=discord.AuditLogAction.kick, modo_id=999, cible_id=1,
                                age=1.0, raison="spam")])
    bot, logs = _bot(audit=audit)
    user = _membre(id=1)
    payload = SimpleNamespace(guild_id=COMMU, user=user)

    await jmb.membre_parti(bot, payload, dormir=_sans_sommeil)
    await _fond()

    texte = "\n".join(_textes(_vue(logs)))
    assert "👢 Membre expulsé" in texte
    assert "**Expulsé par** <@999>" in texte
    assert "spam" in texte


async def test_depart_avec_ban_ne_publie_pas_de_carte_depart():
    """§3 : `on_member_ban` publiera sa propre carte — pas de doublon."""
    _etat_audit_neuf()
    audit = _FauxAudit([_entree(action=discord.AuditLogAction.ban, modo_id=999, cible_id=1, age=1.0)])
    bot, logs = _bot(audit=audit)
    user = _membre(id=1)
    payload = SimpleNamespace(guild_id=COMMU, user=user)

    await jmb.membre_parti(bot, payload, dormir=_sans_sommeil)
    await _fond()

    logs.send.assert_not_awaited()


async def test_depart_bot_exclu_par_defaut():
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    user = _membre(id=1, bot=True)
    payload = SimpleNamespace(guild_id=COMMU, user=user)

    await jmb.membre_parti(bot, payload, dormir=_sans_sommeil)
    await _fond()

    logs.send.assert_not_awaited()


async def test_depart_hors_guild_configuree_ne_publie_rien():
    bot, logs = _bot(guild_ids=(4242,))
    user = _membre(id=1)
    payload = SimpleNamespace(guild_id=COMMU, user=user)

    await jmb.membre_parti(bot, payload, dormir=_sans_sommeil)
    await _fond()

    logs.send.assert_not_awaited()


async def test_depart_ne_retarde_pas_l_evenement():
    """Comme #1 (T2) : le délai d'audit ne retarde que CETTE carte."""
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    user = _membre(id=1)
    payload = SimpleNamespace(guild_id=COMMU, user=user)

    await jmb.membre_parti(bot, payload, dormir=_sans_sommeil)
    logs.send.assert_not_awaited()      # encore en tâche de fond

    await _fond()
    logs.send.assert_awaited_once()


# ---------------------------------------------------------------------------
# #8 — ban / déban


async def test_ban_publie_une_carte_avec_auteur_et_raison():
    _etat_audit_neuf()
    audit = _FauxAudit([_entree(action=discord.AuditLogAction.ban, modo_id=42, cible_id=1,
                                age=1.0, raison="toxicité")])
    bot, logs = _bot(audit=audit)
    guild, user = audit, _membre(id=1)

    await jmb.membre_banni(bot, guild, user, dormir=_sans_sommeil)
    await _fond()

    texte = "\n".join(_textes(_vue(logs)))
    assert "🔨 Membre banni" in texte
    assert "**Banni par** <@42>" in texte
    assert "toxicité" in texte


async def test_ban_sans_entree_audit_ne_nomme_personne():
    _etat_audit_neuf()
    audit = _FauxAudit([])
    bot, logs = _bot(audit=audit)
    guild, user = audit, _membre(id=1)

    await jmb.membre_banni(bot, guild, user, dormir=_sans_sommeil)
    await _fond()

    assert "Banni par" not in "\n".join(_textes(_vue(logs)))


async def test_ban_sans_raison_omet_le_bloc_raison():
    _etat_audit_neuf()
    audit = _FauxAudit([_entree(action=discord.AuditLogAction.ban, modo_id=1, cible_id=1, age=1.0)])
    bot, logs = _bot(audit=audit)
    guild, user = audit, _membre(id=1)

    await jmb.membre_banni(bot, guild, user, dormir=_sans_sommeil)
    await _fond()

    assert "Raison" not in "\n".join(_textes(_vue(logs)))


async def test_ban_raison_echappe_les_mentions():
    _etat_audit_neuf()
    audit = _FauxAudit([_entree(action=discord.AuditLogAction.ban, modo_id=1, cible_id=1,
                                age=1.0, raison="ping @everyone")])
    bot, logs = _bot(audit=audit)
    guild, user = audit, _membre(id=1)

    await jmb.membre_banni(bot, guild, user, dormir=_sans_sommeil)
    await _fond()

    assert "@\u200beveryone" in "\n".join(_textes(_vue(logs)))


async def test_ban_bot_exclu_par_defaut():
    _etat_audit_neuf()
    audit = _FauxAudit([])
    bot, logs = _bot(audit=audit)
    guild, user = audit, _membre(id=1, bot=True)

    await jmb.membre_banni(bot, guild, user, dormir=_sans_sommeil)
    await _fond()

    logs.send.assert_not_awaited()


async def test_ban_attend_avant_de_lire_l_audit():
    _etat_audit_neuf()
    audit = _FauxAudit([_entree(action=discord.AuditLogAction.ban, modo_id=1, cible_id=1, age=1.0)])
    bot, _logs = _bot(audit=audit)
    guild, user = audit, _membre(id=1)
    sommeils = []

    async def _dormir(secondes):
        sommeils.append((secondes, list(audit.appels)))

    await jmb.membre_banni(bot, guild, user, dormir=_dormir)
    await _fond()

    assert sommeils == [(jmb._DELAI_AUDIT, [])]
    assert audit.appels


async def test_deban_publie_une_carte_avec_auteur():
    _etat_audit_neuf()
    audit = _FauxAudit([_entree(action=discord.AuditLogAction.unban, modo_id=3, cible_id=1, age=1.0)])
    bot, logs = _bot(audit=audit)
    guild, user = audit, _membre(id=1)

    await jmb.membre_debanni(bot, guild, user, dormir=_sans_sommeil)
    await _fond()

    texte = "\n".join(_textes(_vue(logs)))
    assert "🔓 Membre débanni" in texte
    assert "**Débanni par** <@3>" in texte


async def test_deban_bot_exclu_par_defaut():
    _etat_audit_neuf()
    audit = _FauxAudit([])
    bot, logs = _bot(audit=audit)
    guild, user = audit, _membre(id=1, bot=True)

    await jmb.membre_debanni(bot, guild, user, dormir=_sans_sommeil)
    await _fond()

    logs.send.assert_not_awaited()


# ---------------------------------------------------------------------------
# #9 — surnom, rôles ; #8 — exclusion temporaire (même écouteur)


async def test_surnom_change_publie_avant_apres():
    _etat_audit_neuf()
    audit = _FauxAudit([_entree(action=discord.AuditLogAction.member_update, modo_id=7,
                                cible_id=1, age=1.0)])
    bot, logs = _bot(audit=audit)
    guild = _guild()
    avant = _membre(id=1, nick="Ancien", guild=guild)
    apres = _membre(id=1, nick="Nouveau", guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    texte = "\n".join(_textes(_vue(logs)))
    assert "✏️ Surnom modifié" in texte
    assert "Ancien" in texte and "Nouveau" in texte
    assert "**Par** <@7>" in texte


async def test_surnom_retire_affiche_aucun():
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    guild = _guild()
    avant = _membre(id=1, nick="Pseudo", guild=guild)
    apres = _membre(id=1, nick=None, guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    assert "Pseudo → *aucun*" in "\n".join(_textes(_vue(logs)))


async def test_surnom_avec_mention_echappe():
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    guild = _guild()
    avant = _membre(id=1, nick=None, guild=guild)
    apres = _membre(id=1, nick="@everyone", guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    assert "@\u200beveryone" in "\n".join(_textes(_vue(logs)))


async def test_exclusion_temporaire_posee():
    _etat_audit_neuf()
    audit = _FauxAudit([_entree(action=discord.AuditLogAction.member_update, modo_id=5,
                                cible_id=1, age=1.0, raison="flood")])
    bot, logs = _bot(audit=audit)
    guild = _guild()
    fin = maintenant() + timedelta(hours=1)
    avant = _membre(id=1, timed_out_until=None, guild=guild)
    apres = _membre(id=1, timed_out_until=fin, guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    texte = "\n".join(_textes(_vue(logs)))
    assert "⏳ Exclusion temporaire" in texte
    assert "Exclu jusqu'à" in texte
    assert "**Par** <@5>" in texte
    assert "flood" in texte


async def test_exclusion_temporaire_levee():
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    guild = _guild()
    avant = _membre(id=1, timed_out_until=maintenant() + timedelta(hours=1), guild=guild)
    apres = _membre(id=1, timed_out_until=None, guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    assert "✅ Exclusion levée" in "\n".join(_textes(_vue(logs)))


async def test_timeout_deja_expire_des_deux_cotes_ne_declenche_rien():
    """`timed_out_until` PASSÉ vaut « pas exclu » : une vieille date encore
    présente des deux côtés n'est pas une exclusion qui vient de commencer."""
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    guild = _guild()
    passe = maintenant() - timedelta(hours=1)
    avant = _membre(id=1, timed_out_until=passe, guild=guild)
    apres = _membre(id=1, timed_out_until=passe, guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    logs.send.assert_not_awaited()


async def test_roles_ajoutes_et_retires_avec_recoupement():
    _etat_audit_neuf()
    audit = _FauxAudit([_entree(action=discord.AuditLogAction.member_role_update, modo_id=8,
                                cible_id=1, age=1.0)])
    bot, logs = _bot(audit=audit)
    guild = _guild()
    ancien, nouveau = _role(10, "Ancien"), _role(20, "Nouveau")
    avant = _membre(id=1, roles=[ancien], guild=guild)
    apres = _membre(id=1, roles=[nouveau], guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    texte = "\n".join(_textes(_vue(logs)))
    assert "🎭 Rôles modifiés" in texte
    assert "Rôles ajoutés" in texte and "Nouveau" in texte
    assert "Rôles retirés" in texte and "Ancien" in texte
    assert "**Par** <@8>" in texte


async def test_role_commun_absent_du_diff():
    """Un rôle présent des deux côtés (dont le `@everyone` toujours porté par
    `Member.roles`) ne sort ni en ajouté ni en retiré."""
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    guild = _guild()
    commun = _role(1, "everyone")
    avant = _membre(id=1, roles=[commun], guild=guild)
    apres = _membre(id=1, roles=[commun], guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    logs.send.assert_not_awaited()


async def test_rien_ne_change_ne_publie_rien():
    """Avatar, statut de boost… : `on_member_update` se déclenche sur bien
    plus que nick/timeout/rôles, et ce module ne journalise que ces trois-là."""
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    guild = _guild()
    m = _membre(id=1, guild=guild)

    await jmb.membre_modifie(bot, m, m, dormir=_sans_sommeil)
    await _fond()

    logs.send.assert_not_awaited()


async def test_modification_de_bot_exclue_par_defaut():
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    guild = _guild()
    avant = _membre(id=1, nick="A", bot=True, guild=guild)
    apres = _membre(id=1, nick="B", bot=True, guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    logs.send.assert_not_awaited()


async def test_modification_hors_guild_configuree_ne_publie_rien():
    bot, logs = _bot(guild_ids=(4242,))
    guild = _guild(COMMU)
    avant = _membre(id=1, nick="A", guild=guild)
    apres = _membre(id=1, nick="B", guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    logs.send.assert_not_awaited()


async def test_plusieurs_aspects_changes_titre_generique():
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    guild = _guild()
    r = _role(10, "Membre")
    avant = _membre(id=1, nick="A", roles=[], guild=guild)
    apres = _membre(id=1, nick="B", roles=[r], guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    assert "🔧 Membre modifié" in "\n".join(_textes(_vue(logs)))


# ---------------------------------------------------------------------------
# Budget Components V2 — pire cas (100+ rôles, noms au plafond Discord)


async def test_budget_v2_tenu_avec_cent_cinquante_roles_noms_longs():
    _etat_audit_neuf()
    bot, logs = _bot(audit=_FauxAudit([]))
    guild = _guild()
    nom_long = "x" * 100   # plafond Discord pour un nom de rôle
    avant_roles = [_role(i, nom_long) for i in range(150)]
    apres_roles = [_role(1000 + i, nom_long) for i in range(150)]
    avant = _membre(id=1, nick="A" * 32, roles=avant_roles, guild=guild)
    apres = _membre(id=1, nick="B" * 32, roles=apres_roles, guild=guild)

    await jmb.membre_modifie(bot, avant, apres, dormir=_sans_sommeil)
    await _fond()

    vue = _vue(logs)
    assert _longueur_totale(vue) <= 4000
    assert "… et" in "\n".join(_textes(vue))    # le bornage s'est réellement déclenché
