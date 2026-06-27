"""Tests du parsing de DISCORD_GUILD_ID (liste de serveurs pour sync instantané des commandes)."""
from bot.discord.bot import parse_guild_ids


def test_vide_donne_liste_vide():
    assert parse_guild_ids("") == []
    assert parse_guild_ids(None) == []


def test_un_seul_id():
    assert parse_guild_ids("1151522926680617060") == [1151522926680617060]


def test_plusieurs_ids_separes_par_virgule():
    assert parse_guild_ids("1151522926680617060,1063150486137606256") == [
        1151522926680617060,
        1063150486137606256,
    ]


def test_espaces_et_zero_et_invalides_ignores():
    assert parse_guild_ids(" 123 , 0 , abc , 456 ") == [123, 456]
