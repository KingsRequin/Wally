"""Suivi du quota Azure Speech free tier (par mois) : STT (heures) + TTS (caractères).

Azure ne fournit pas l'usage en temps réel via une API simple, donc on compte localement
ce que le bot consomme (fidèle au quota réel). Persisté dans un petit fichier JSON, remis
à zéro au changement de mois.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

FREE_STT_SECONDS = 5 * 3600     # free tier F0 : 5 h de STT / mois
FREE_TTS_CHARS = 500_000        # free tier F0 : 0,5 M caractères TTS Neural / mois


class VoiceQuota:
    def __init__(self, path: str = "data/voice_quota.json") -> None:
        self._path = Path(path)
        self._data = self._load()

    @staticmethod
    def _month() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _fresh(self) -> dict:
        return {"month": self._month(), "stt_seconds": 0.0, "tts_chars": 0}

    def _load(self) -> dict:
        try:
            d = json.loads(self._path.read_text())
        except Exception:  # noqa: BLE001
            d = {}
        return d if d.get("month") == self._month() else self._fresh()

    def _reset_if_new_month(self) -> None:
        if self._data.get("month") != self._month():
            self._data = self._fresh()

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data))
        except Exception as e:  # noqa: BLE001
            logger.warning("VoiceQuota save a échoué: {e}", e=e)

    def add_stt_seconds(self, seconds: float) -> None:
        self._reset_if_new_month()
        self._data["stt_seconds"] = self._data.get("stt_seconds", 0.0) + max(0.0, seconds)
        self._save()

    def add_tts_chars(self, chars: int) -> None:
        self._reset_if_new_month()
        self._data["tts_chars"] = self._data.get("tts_chars", 0) + max(0, chars)
        self._save()

    def snapshot(self) -> dict:
        """Usage et restant du mois courant."""
        self._reset_if_new_month()
        stt = float(self._data.get("stt_seconds", 0.0))
        tts = int(self._data.get("tts_chars", 0))
        return {
            "month": self._data["month"],
            "stt_used_seconds": stt,
            "stt_remaining_seconds": max(0.0, FREE_STT_SECONDS - stt),
            "stt_free_seconds": FREE_STT_SECONDS,
            "tts_used_chars": tts,
            "tts_remaining_chars": max(0, FREE_TTS_CHARS - tts),
            "tts_free_chars": FREE_TTS_CHARS,
        }
