# Ciclo diseño de señal — banda muerta sobre TSMOM k=14 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Probar si una banda muerta (histéresis) simétrica sobre el retorno de 14 días de la señal ganadora (TSMOM k=14, long/flat, BTC spot) reduce la cantidad de cambios de posición sin empeorar Sharpe ni drawdown, con una ventana de verificación NUEVA (2025-07→presente) para no reusar la ya gastada adoptando M1/M2.

**Architecture:** Una función pura de posición con estado (`posiciones_tsmom_banda`) en un script de estudio nuevo (`estudios/estudio_histeresis.py`), siguiendo el mismo esqueleto CLI/reporte que `estudio_momentum.py`/`estudio_ma.py`. Una métrica genérica nueva (`cambios_de_posicion`) entra a `estudios/nucleo.py`, igual categoría que `sharpe_anualizado`/`max_drawdown`. Reusa el candado de verificación existente (`ventana` + `--verificacion`) con un corte propio.

**Tech Stack:** Python 3.12, stdlib pura (`statistics`, `argparse`), pytest. Sin dependencias nuevas. Datos ya cacheados (no hace falta descargar nada nuevo — BTCUSDT 1d 2017-08→2026-06 ya está en `backtest_cache/`).

**Spec:** `docs/superpowers/specs/2026-07-16-ciclo-histeresis-momentum-design.md` (leerla antes de la Task 1; los valores pre-registrados son ley).

## Global Constraints

- Tests: `.venv/bin/python -m pytest -q` — suite completa verde al final de cada task (base actual: 304 passed).
- Sin dependencias nuevas. Sin pandas/numpy.
- Código y comentarios en inglés; docs y reportes en español.
- TDD estricto: test que falla → implementación mínima → verde → commit. Commits: imperativo corto en inglés + footer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **El candado de verificación es sagrado:** ningún script corre `--modo verificacion` antes del checkpoint humano de la Task 3. Desarrollo/pruebas: solo calibración o fixtures sintéticos.
- Constantes pre-registradas (fuente: la spec; NO se ajustan al ver datos):
  - Alcance: solo BTCUSDT, solo TSMOM k=14, solo variante long_flat. No se repite en k=28 ni en P/MA este ciclo.
  - Mecanismo de banda: `ret > x` → largo (1.0); `ret ≤ -x` → flat (0.0); `-x < ret ≤ x` → mantiene la posición del día anterior (el primer día evaluable sin previa usa flat — cae solo de la construcción, ver Task 2).
  - Grilla de X (fija): `(0.0, 0.02, 0.05, 0.08)`. X=0.0 es el control de sanidad.
  - Corte del ciclo: `CORTE_HISTERESIS_MS = 1751328000000` (2025-07-01T00:00:00Z). Calibración 2017-08→2025-06, verificación 2025-07→presente (12 meses, sellada — ventana NUEVA, no la 2024-2026 ya usada para adoptar M1/M2).
  - Burn-in: 14 días (único lookback de este estudio).
  - Umbral de adopción (verbatim en el reporte y el veredicto): *para cada X>0, comparado contra el control X=0.0 de la MISMA ventana, en calibración Y verificación evaluadas por separado: cambios_de_posicion(X) < cambios_de_posicion(control), Y Sharpe(X) ≥ Sharpe(control), Y max_drawdown(X) ≤ max_drawdown(control). "Casi" = NO PASA.*
  - Criterio de salida (firmado 2026-07-16): si algún X>0 pasa en ambas ventanas → se adopta el de mayor reducción de operaciones entre los que pasan. Si ninguno pasa → se descarta la banda; la señal candidata sigue siendo TSMOM k=14 long_flat sin banda.
  - Convenciones: señal al cierre de t se aplica al retorno de t+1 (sin lookahead); Sharpe = media/desvío × √365; sin overlay de vol-targeting en este ciclo (señal cruda).
- Los reportes de estudio generados bajo `backtest_runs/estudios/` SE COMMITEAN (evidencia del ciclo).
- Si el sandbox bloquea python inline (`python -c` / heredoc), escribir el snippet a un archivo `.py` temporal y ejecutarlo.

---

### Task 1: Métrica genérica y constante de corte en `estudios/nucleo.py`

**Files:**
- Modify: `estudios/nucleo.py` (append al final, después de `metricas_buy_and_hold`)
- Test: `tests/test_estudios_nucleo.py` (append)

**Interfaces:**
- Produces: `CORTE_HISTERESIS_MS: int`, `cambios_de_posicion(posiciones: list[float]) -> int`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_estudios_nucleo.py`, y agregar `CORTE_HISTERESIS_MS` y `cambios_de_posicion` al bloque `from estudios.nucleo import (...)` del inicio del archivo (orden alfabético, como el resto):

```python
def test_cambios_de_posicion_cuenta_transiciones():
    assert cambios_de_posicion([0.0, 0.0, 1.0, 1.0, 0.0]) == 2
    assert cambios_de_posicion([1.0, 1.0, 1.0]) == 0
    assert cambios_de_posicion([1.0]) == 0
    assert cambios_de_posicion([]) == 0


def test_corte_histeresis_ms_es_2025_07_01():
    from datetime import datetime, timezone
    momento = datetime.fromtimestamp(CORTE_HISTERESIS_MS / 1000, tz=timezone.utc)
    assert momento == datetime(2025, 7, 1, tzinfo=timezone.utc)
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run: `.venv/bin/python -m pytest tests/test_estudios_nucleo.py -v -k "cambios_de_posicion or corte_histeresis"`
Expected: FAIL con `ImportError` (`cambios_de_posicion`/`CORTE_HISTERESIS_MS` no existen todavía).

- [ ] **Step 3: Implementación mínima**

Agregar al final de `estudios/nucleo.py`:

```python
# --- Hysteresis-band study (signal-design cycle, spec 2026-07-16) ---

CORTE_HISTERESIS_MS = 1751328000000  # 2025-07-01T00:00:00Z


def cambios_de_posicion(posiciones: list[float]) -> int:
    """Count of days where the position differs from the previous day's."""
    return sum(
        1 for t in range(1, len(posiciones)) if posiciones[t] != posiciones[t - 1]
    )
```

- [ ] **Step 4: Correr los tests para confirmar que pasan**

Run: `.venv/bin/python -m pytest tests/test_estudios_nucleo.py -v -k "cambios_de_posicion or corte_histeresis"`
Expected: PASS (2 tests).

- [ ] **Step 5: Suite completa**

Run: `.venv/bin/python -m pytest -q`
Expected: `306 passed` (304 base + 2 nuevos).

- [ ] **Step 6: Commit**

```bash
git add estudios/nucleo.py tests/test_estudios_nucleo.py
git commit -m "Add position-change counter and hysteresis-cycle split constant"
```

---

### Task 2: Estudio de banda muerta (`estudios/estudio_histeresis.py`) + corrida de calibración

**Files:**
- Create: `estudios/estudio_histeresis.py`
- Test: `tests/test_estudio_histeresis.py`

**Interfaces:**
- Consumes: `estudios.nucleo.{CORTE_HISTERESIS_MS, cambios_de_posicion, metricas_buy_and_hold, metricas_estrategia, retornos_diarios, ventana}` (Task 1 y ciclo anterior); `daily_history.cargar_rango(symbol, start_month, end_month)`; `estudios.reporte.escribir_reporte(nombre, preregistro, celdas, resultados)`.
- Produces: `posiciones_tsmom_banda(closes: List[float], k: int, x: float) -> List[float]`, `rows_con_burn_in(modo: str, verificacion: bool) -> tuple[list, int]`, `main(argv=None) -> int`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_estudio_histeresis.py`:

```python
from estudios.estudio_histeresis import posiciones_tsmom_banda


def test_banda_entra_largo_mantiene_y_sale():
    # k=2, x=0.05 (5%): retorno claro > x entra, interior mantiene, < -x sale
    closes = [100.0, 100.0, 106.0, 107.0, 103.0, 101.0]
    assert posiciones_tsmom_banda(closes, 2, 0.05) == [0.0, 0.0, 1.0, 1.0, 1.0, 0.0]


def test_banda_primer_dia_interior_sin_previa_es_flat():
    # dia 2 (primer dia evaluable, i==k): retorno 2% cae en el interior
    # (-5%, 5%], pero no hay posicion previa real -> flat, por construccion
    closes = [100.0, 100.0, 102.0]
    assert posiciones_tsmom_banda(closes, 2, 0.05) == [0.0, 0.0, 0.0]


def test_banda_x_cero_replica_tsmom_long_flat_sin_banda():
    # mismo fixture que test_posiciones_long_flat_recorta_el_lado_corto en
    # tests/test_estudio_momentum.py; con x=0.0 debe dar el mismo resultado
    closes = [100.0, 102.0, 101.0, 99.0, 98.0]
    assert posiciones_tsmom_banda(closes, 2, 0.0) == [0.0, 0.0, 1.0, 0.0, 0.0]
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run: `.venv/bin/python -m pytest tests/test_estudio_histeresis.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'estudios.estudio_histeresis'`.

- [ ] **Step 3: Implementación**

Crear `estudios/estudio_histeresis.py`:

```python
from __future__ import annotations

import argparse
import sys
from typing import List

import daily_history
from estudios.nucleo import (
    CORTE_HISTERESIS_MS,
    cambios_de_posicion,
    metricas_buy_and_hold,
    metricas_estrategia,
    retornos_diarios,
    ventana,
)
from estudios.reporte import escribir_reporte

K = 14
GRILLA_X = (0.0, 0.02, 0.05, 0.08)
BURN_IN = 14
SYMBOL = "BTCUSDT"  # alcance: solo la celda ganadora del ciclo anterior
START_MONTH = "2017-08"
END_MONTH = "2026-07"  # exclusive: current month has no published dump

PREREGISTRO = {
    "rol": "Ciclo diseno de senal — banda muerta sobre TSMOM k=14 (spec 2026-07-16)",
    "datos": "klines 1d SPOT Binance, 2017-08 -> mes corriente exclusivo, BTC unicamente",
    "senal": "banda muerta simetrica sobre ret[t-14,t]: entra largo si ret > x, pasa a flat si ret <= -x, si cae en (-x, x] mantiene la posicion del dia anterior (primer dia evaluable sin previa: flat)",
    "grilla_x": "0.0, 0.02, 0.05, 0.08 (fraccion); x=0.0 es control de sanidad, degenera en TSMOM k=14 long_flat sin banda",
    "split": "calibracion 2017-08 -> 2025-06; verificacion 2025-07 -> presente (sellada, ventana NUEVA); corte_ms=1751328000000",
    "burn_in": "en verificacion, los 14 dias previos al corte solo alimentan la senal",
    "umbral_adopcion": (
        "para cada x>0, comparado contra el control x=0.0 de la MISMA ventana, en calibracion Y "
        "verificacion por separado: cambios_de_posicion(x) < cambios_de_posicion(control), Y "
        "sharpe(x) >= sharpe(control), Y max_drawdown(x) <= max_drawdown(control). 'Casi' = NO PASA."
    ),
    "criterio_salida": (
        "si algun x>0 pasa en ambas ventanas -> se adopta el de mayor reduccion de operaciones "
        "entre los que pasan; si ninguno pasa -> se descarta la banda, la senal candidata sigue "
        "siendo TSMOM k=14 long_flat sin banda (firmado 2026-07-16)"
    ),
}


def posiciones_tsmom_banda(closes: List[float], k: int, x: float) -> List[float]:
    """Long/flat position with a symmetric dead band on the k-day return.

    ret > x -> long (1.0); ret <= -x -> flat (0.0); otherwise holds
    yesterday's position. Days before the lookback fills are flat, which
    also seeds the band's "no previous position" default.
    """
    out: List[float] = []
    pos_previa = 0.0
    for i in range(len(closes)):
        if i < k:
            pos = 0.0
        else:
            ret = closes[i] / closes[i - k] - 1.0
            if ret > x:
                pos = 1.0
            elif ret <= -x:
                pos = 0.0
            else:
                pos = pos_previa
        out.append(pos)
        pos_previa = pos
    return out


def rows_con_burn_in(modo: str, verificacion: bool):
    """Window rows plus, in verification mode, a signal-only burn-in prefix."""
    todas = daily_history.cargar_rango(SYMBOL, START_MONTH, END_MONTH)
    seleccion = ventana(todas, modo, corte_ms=CORTE_HISTERESIS_MS,
                        verificacion_habilitada=verificacion)
    if modo == "verificacion":
        previos = [r for r in todas if r[0] < CORTE_HISTERESIS_MS][-BURN_IN:]
        return previos + seleccion, len(previos)
    return seleccion, 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Signal-design cycle: dead band on TSMOM k=14 (BTC only).")
    parser.add_argument("--modo", required=True, choices=("calibracion", "verificacion"))
    parser.add_argument("--verificacion", action="store_true")
    args = parser.parse_args(argv)

    rows, eval_desde = rows_con_burn_in(args.modo, args.verificacion)
    closes = [r[4] for r in rows]
    rets = retornos_diarios(closes)
    idx0 = max(1, eval_desde)

    celdas: dict = {}
    for x in GRILLA_X:
        pos = posiciones_tsmom_banda(closes, K, x)
        m = metricas_estrategia(rets, pos, eval_desde)
        m["cambios_de_posicion"] = cambios_de_posicion(pos[idx0 - 1:])
        celdas[str(x)] = m

    control = celdas[str(GRILLA_X[0])]
    for x in GRILLA_X[1:]:
        c = celdas[str(x)]
        c["pasa_vs_control"] = bool(
            c["sharpe"] is not None
            and control["sharpe"] is not None
            and c["cambios_de_posicion"] < control["cambios_de_posicion"]
            and c["sharpe"] >= control["sharpe"]
            and c["max_drawdown"] <= control["max_drawdown"]
        )

    resultados = {
        SYMBOL: {
            "buy_and_hold": metricas_buy_and_hold(rets, eval_desde),
            "celdas": celdas,
        }
    }
    ruta = escribir_reporte(f"histeresis-{args.modo}", PREREGISTRO, len(GRILLA_X), resultados)
    print(f"Reporte escrito en: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Correr los tests para confirmar que pasan**

Run: `.venv/bin/python -m pytest tests/test_estudio_histeresis.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Suite completa**

Run: `.venv/bin/python -m pytest -q`
Expected: `309 passed` (306 de Task 1 + 3 nuevos).

- [ ] **Step 6: Corrida real de calibración (datos ya cacheados, sin descargas)**

```bash
.venv/bin/python -m estudios.estudio_histeresis --modo calibracion
```

Expected: imprime `Reporte escrito en: backtest_runs/estudios/<timestamp>_histeresis-calibracion`. Revisar `reporte.md` a mano: 4 celdas (una por X), la de `"0.0"` debe tener `cambios_de_posicion` igual al conteo de flips de TSMOM k=14 long_flat puro (sin `pasa_vs_control`, es el control); las otras 3 deben traer `pasa_vs_control` como `true`/`false`.

- [ ] **Step 7: Commit (código + reporte de calibración)**

```bash
git add estudios/estudio_histeresis.py tests/test_estudio_histeresis.py backtest_runs/estudios/
git commit -m "Add hysteresis-band study on TSMOM k=14 and run calibration"
```

---

### Task 3: CHECKPOINT humano + verificación + veredicto

**Esta task empieza con una pausa obligatoria:** el script debe estar revisado y congelado, y Guille debe revisar el reporte de calibración de la Task 2 y dar el OK explícito ANTES de abrir la ventana de verificación.

**Files:**
- Create: `backtest_runs/estudios/veredicto-histeresis-2026-07.md` (a mano, números reales)
- Modify: `docs/mejoras-propuestas.md`

**Interfaces:**
- Consumes: reporte de calibración (Task 2), script congelado (Task 2).
- Produces: veredicto del ciclo contra el umbral pre-registrado y el criterio de salida firmado.

- [ ] **Step 1: Confirmar revisión aprobada de Tasks 1-2 y OK de Guille (gate humano)**

- [ ] **Step 2: Corrida de verificación (una sola vez, script congelado)**

```bash
.venv/bin/python -m estudios.estudio_histeresis --modo verificacion --verificacion
```

Si aparece un bug después de esta corrida: se arregla, se re-corre TODO (calibración y verificación) y el veredicto lo declara ("re-corrida post-fix").

- [ ] **Step 3: Evaluar el umbral por X (a mano, en el veredicto)**

Para cada X en {0.02, 0.05, 0.08}, leer `pasa_vs_control` de calibración y de verificación (ya calculado por el script). Un X **pasa el ciclo** solo si `pasa_vs_control` es `true` en AMBAS ventanas. Tabla completa en el veredicto (X × ventana × las 3 condiciones con sus valores numéricos, no solo el booleano).

- [ ] **Step 4: Redactar `backtest_runs/estudios/veredicto-histeresis-2026-07.md`**

Estructura fija: tabla de calibración (4 celdas: control + 3 X, con Sharpe/drawdown/cambios_de_posicion), tabla de verificación (mismo formato), evaluación textual contra el umbral pre-registrado COPIADO verbatim de la spec, conclusión PASA / NO PASA por X, y el cierre según el criterio de salida:
- si algún X pasa en ambas ventanas → "se adopta X=<valor> (mayor reducción de operaciones entre los que pasan) como parte de la señal candidata";
- si ninguno pasa → "se descarta la banda muerta; la señal candidata sigue siendo TSMOM k=14 long_flat sin banda, sin re-testear con otra grilla sin una razón nueva".

- [ ] **Step 5: Actualizar `docs/mejoras-propuestas.md`**

Agregar al final:

```markdown
**Ciclo diseño de señal — banda muerta (2026-07, spec:
`docs/superpowers/specs/2026-07-16-ciclo-histeresis-momentum-design.md`):**
banda muerta simétrica sobre TSMOM k=14 long_flat BTC, grilla X∈{0,2,5,8}%,
verificación sellada NUEVA 2025-07→presente (no reusa la ya gastada en
M1/M2). Veredicto:
`backtest_runs/estudios/veredicto-histeresis-2026-07.md`.
[Completar con el resultado real y el paso siguiente.]
```

(El corchete se reemplaza por el resultado real.)

- [ ] **Step 6: Suite completa + commit final**

```bash
.venv/bin/python -m pytest -q
git add backtest_runs/estudios/ docs/mejoras-propuestas.md
git commit -m "Run hysteresis verification window and record the cycle verdict"
```

---

## Notas de diseño para el ejecutor

1. **El candado de verificación es sagrado.** Nada corre `--modo verificacion` antes del checkpoint de la Task 3. Para probar flujos: calibración o fixtures sintéticos.
2. **Los umbrales pre-registrados no se ajustan al ver datos.** "Casi" = NO PASA.
3. **Sin editorializar en los reportes:** números y pre-registro. La interpretación va solo en el veredicto, contra el umbral verbatim.
4. **`pasa_vs_control` lo calcula el script, no el veredicto** — el veredicto solo transcribe y combina las dos ventanas (Y lógico entre calibración y verificación).
5. **No se reintroduce el overlay de vol-targeting ni gates adicionales en este ciclo** — señal cruda únicamente, tal como firma la spec.
6. **Datos ya cacheados:** no hace falta tocar `daily_history.py` ni descargar nada; si al correr faltara algún mes reciente, descargarlo mes a mes (patrón ya existente), nunca en bloque.
