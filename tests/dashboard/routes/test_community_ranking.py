from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace
from bot.dashboard.routes import community


class _FakeDB:
    async def list_memory_users(self):
        return [
            {"user_id": "twitch:1", "platform": "twitch", "username": "zed", "trust_score": 0.9},
            {"user_id": "twitch:2", "platform": "twitch", "username": "gaby", "trust_score": 0.5},
        ]

    async def get_love_scores_batch(self, pairs):
        return {("twitch", "1"): 0.8, ("twitch", "2"): 0.7}


def _client(db):
    app = FastAPI()
    app.include_router(community.public_router, prefix="/api/public")
    app.state.wally = SimpleNamespace(db=db)
    return app


def test_ranking_sorted_desc_with_azrael_pinned():
    ranking = TestClient(_client(_FakeDB())).get("/api/public/community/ranking").json()["ranking"]
    names = [x["name"] for x in ranking]
    assert names[0] == "zed"
    assert ranking[-1]["name"] == "Azrael"
    assert ranking[-1]["score"] == "MAX"


def test_ranking_degrades_on_db_error():
    class _Boom:
        async def list_memory_users(self):
            raise RuntimeError("db down")

    r = TestClient(_client(_Boom())).get("/api/public/community/ranking")
    assert r.status_code == 200
    assert r.json()["ranking"][-1]["name"] == "Azrael"
