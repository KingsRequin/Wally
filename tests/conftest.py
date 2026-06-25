import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    import asyncio
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(autouse=True)
def reset_identity_after_test():
    """Réinitialise l'identité du bot après chaque test.

    Évite que set_identity() appelé dans un test ne pollue les tests suivants.
    """
    yield
    from bot.intelligence import identity
    identity._NAME = "Wally"
    identity._CREATOR = "KingsRequin"
    identity._OWNER = ""
