"""Lecture d'informations matérielles et environnementales pour la cognition."""
from __future__ import annotations

import glob
import time

# Cache météo : (timestamp, valeur) — rafraîchi toutes les 30min.
_weather_cache: tuple[float, str | None] = (0.0, None)
_WEATHER_TTL = 1800

_WEATHER_FR: dict[str, str] = {
    "sunny": "ensoleillé", "clear": "dégagé", "partly cloudy": "partiellement nuageux",
    "cloudy": "nuageux", "overcast": "couvert", "mist": "brumeux", "fog": "brouillard",
    "rain": "pluie", "drizzle": "bruine", "heavy rain": "pluie forte",
    "snow": "neige", "sleet": "grésil", "thunder": "orage", "blizzard": "blizzard",
    "light rain": "pluie légère", "moderate rain": "pluie modérée",
    "patchy rain": "averses", "light snow": "neige légère", "freezing": "verglas",
}


def read_host_metrics() -> str | None:
    """Températures CPU, charge système et RAM — tout en une ligne."""
    parts: list[str] = []

    # Températures
    cpu_temp: int | None = None
    for zone_dir in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        try:
            if open(f"{zone_dir}/type").read().strip() == "x86_pkg_temp":
                cpu_temp = int(open(f"{zone_dir}/temp").read().strip()) // 1000
                break
        except Exception:
            continue
    if cpu_temp is not None:
        parts.append(f"CPU {cpu_temp}°C")

    # Charge 1min
    try:
        load1 = float(open("/proc/loadavg").read().split()[0])
        parts.append(f"charge {load1:.1f}")
    except Exception:
        pass

    # RAM utilisée / totale
    try:
        mem: dict[str, int] = {}
        for line in open("/proc/meminfo"):
            k, v = line.split(":", 1)
            if k in ("MemTotal", "MemAvailable"):
                mem[k] = int(v.split()[0])
        if "MemTotal" in mem and "MemAvailable" in mem:
            used_gb = (mem["MemTotal"] - mem["MemAvailable"]) / 1_048_576
            total_gb = mem["MemTotal"] / 1_048_576
            parts.append(f"RAM {used_gb:.1f}/{total_gb:.0f} Go")
    except Exception:
        pass

    return ", ".join(parts) if parts else None


async def fetch_weather_france() -> str | None:
    """Météo générale en France via wttr.in (Paris comme référence).

    Cache 30 min. Retourne une description qualitative sans mentionner la ville.
    """
    global _weather_cache
    ts, cached = _weather_cache
    if cached is not None and (time.time() - ts) < _WEATHER_TTL:
        return cached

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://wttr.in/Paris",
                params={"format": "j1"},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        cur = data["current_condition"][0]
        temp = int(cur["temp_C"])
        feels = int(cur["FeelsLikeC"])
        desc_raw = cur["weatherDesc"][0]["value"].lower()

        # Traduction qualitative
        desc_fr = next(
            (v for k, v in _WEATHER_FR.items() if k in desc_raw),
            desc_raw,
        )

        # Description qualitative de la température
        if temp >= 30:
            temp_qual = "très chaud"
        elif temp >= 22:
            temp_qual = "chaud"
        elif temp >= 15:
            temp_qual = "doux"
        elif temp >= 7:
            temp_qual = "frais"
        else:
            temp_qual = "froid"

        result = f"{desc_fr}, {temp}°C (ressenti {feels}°C) — {temp_qual}"
        _weather_cache = (time.time(), result)
        return result
    except Exception:
        # En cas d'échec, on conserve le cache expiré plutôt que None
        return _weather_cache[1]
