"""Write pre-registered study reports: a machine-readable JSON dump plus a
human-readable markdown summary that always leads with the pre-registration
and the number of cells looked at, so nobody can quietly p-hack after seeing
results.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone


def escribir_reporte(
    nombre: str,
    preregistro: dict,
    celdas: int,
    resultados: dict,
    base_dir: str = "backtest_runs/estudios",
) -> str:
    """Write resultados.json and reporte.md under a timestamped run directory.

    Returns the path to the created directory.
    """
    sello = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    ruta = os.path.join(base_dir, f"{sello}_{nombre}")
    os.makedirs(ruta, exist_ok=True)

    datos = {"preregistro": preregistro, "celdas": celdas, "resultados": resultados}
    with open(os.path.join(ruta, "resultados.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)

    lineas_preregistro = "\n".join(
        f"- {clave}: {valor}" for clave, valor in preregistro.items()
    )
    md = (
        f"# {nombre}\n\n"
        f"## Pre-registro\n\n"
        f"{lineas_preregistro}\n\n"
        f"Celdas miradas: {celdas}\n\n"
        f"## Resultados\n\n"
        f"```json\n{json.dumps(resultados, indent=2, ensure_ascii=False)}\n```\n"
    )
    with open(os.path.join(ruta, "reporte.md"), "w", encoding="utf-8") as f:
        f.write(md)

    return ruta
