"""Lecture d'informations matérielles sur l'hôte (températures, charge)."""
from __future__ import annotations

import glob


def read_host_temps() -> str | None:
    """Lit les zones thermiques /sys/class/thermal/* et retourne une string lisible.

    Priorité : x86_pkg_temp (CPU physique) > acpitz (ACPI générique).
    Retourne None si aucune zone accessible (VM sans accès /sys).
    """
    cpu_temp: int | None = None
    acpi_temps: list[int] = []

    for zone_dir in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        try:
            zone_type = open(f"{zone_dir}/type").read().strip()
            raw = int(open(f"{zone_dir}/temp").read().strip())
            celsius = raw // 1000
            if zone_type == "x86_pkg_temp":
                cpu_temp = celsius
            elif zone_type == "acpitz":
                acpi_temps.append(celsius)
        except Exception:
            continue

    parts: list[str] = []
    if cpu_temp is not None:
        parts.append(f"CPU {cpu_temp}°C")
    if acpi_temps:
        avg = sum(acpi_temps) // len(acpi_temps)
        parts.append(f"système {avg}°C")

    return ", ".join(parts) if parts else None
