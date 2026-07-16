# Veredicto — Ciclo diseño de señal: banda muerta (histéresis) sobre TSMOM k=14

Fecha: 2026-07-16
Spec: `docs/superpowers/specs/2026-07-16-ciclo-histeresis-momentum-design.md`
Script congelado: `estudios/estudio_histeresis.py`
Reporte de calibración: `backtest_runs/estudios/2026-07-16_16-38-15_histeresis-calibracion/resultados.json`
Reporte de verificación: `backtest_runs/estudios/2026-07-16_18-14-56_histeresis-verificacion/resultados.json`

## Umbral de adopción (pre-registrado, copiado verbatim de la spec)

> Un valor de X>0 **pasa** si, en calibración Y en verificación evaluadas por
> separado (la verificación entera, sin subventanas), comparado contra el
> control X=0% de la misma ventana:
>
> 1. cambios de posición de X < cambios de posición del control, Y
> 2. Sharpe de X ≥ Sharpe del control, Y
> 3. max drawdown de X ≤ max drawdown del control.
>
> "Casi" = NO PASA, sin excepciones — mismo criterio que todos los ciclos
> anteriores.

## Criterio de salida del ciclo (pre-registrado, copiado verbatim de la spec)

> - **Si algún X>0 pasa en ambas ventanas:** se adopta ese valor de X (el de
>   mayor reducción de operaciones entre los que pasan) como parte de la señal
>   candidata. Próximo ciclo posible: robustez en k=28/P/MA, o integración
>   operativa con el bot de scalping — decisión de Guille en su momento.
> - **Si ninguno pasa:** se descarta la banda muerta para esta señal; la señal
>   candidata sigue siendo TSMOM k=14 long/flat sin banda (el resultado del
>   ciclo anterior, intacto). No se re-testea la banda con otra grilla sin
>   una razón nueva.

## Tabla de calibración (2017-08 → 2025-06, BTCUSDT)

| X | Sharpe | Max drawdown | Media (diaria) | Cambios de posición | `pasa_vs_control` |
|---|---|---|---|---|---|
| 0.0 (control) | 1.2826396717 | 0.6553363166 | 0.0016826876 | 333 | — |
| 0.02 | 1.1246564596 | 0.6884667373 | 0.0014825638 | 199 | false |
| 0.05 | 1.0749538002 | 0.6471022724 | 0.0014168076 | 120 | false |
| 0.08 | 0.7720854484 | 0.6953890471 | 0.0010626298 | 94 | false |

Condición por X (calibración):

- **X=0.02:** cambios 199 < 333 (cumple) · Sharpe 1.1246564596 ≥ 1.2826396717 (NO cumple) · drawdown 0.6884667373 ≤ 0.6553363166 (NO cumple) → **NO PASA**
- **X=0.05:** cambios 120 < 333 (cumple) · Sharpe 1.0749538002 ≥ 1.2826396717 (NO cumple) · drawdown 0.6471022724 ≤ 0.6553363166 (cumple) → **NO PASA**
- **X=0.08:** cambios 94 < 333 (cumple) · Sharpe 0.7720854484 ≥ 1.2826396717 (NO cumple) · drawdown 0.6953890471 ≤ 0.6553363166 (NO cumple) → **NO PASA**

## Tabla de verificación (2025-07 → presente, sellada, BTCUSDT)

| X | Sharpe | Max drawdown | Media (diaria) | Cambios de posición | `pasa_vs_control` |
|---|---|---|---|---|---|
| 0.0 (control) | 0.1979924878 | 0.1780861289 | 0.0001308955 | 46 | — |
| 0.02 | -1.2248404358 | 0.3543651305 | -0.0007902845 | 24 | false |
| 0.05 | -1.5263462889 | 0.4264993877 | -0.0010505141 | 18 | false |
| 0.08 | -1.3357098911 | 0.3977655311 | -0.0008693807 | 10 | false |

Condición por X (verificación):

- **X=0.02:** cambios 24 < 46 (cumple) · Sharpe -1.2248404358 ≥ 0.1979924878 (NO cumple) · drawdown 0.3543651305 ≤ 0.1780861289 (NO cumple) → **NO PASA**
- **X=0.05:** cambios 18 < 46 (cumple) · Sharpe -1.5263462889 ≥ 0.1979924878 (NO cumple) · drawdown 0.4264993877 ≤ 0.1780861289 (NO cumple) → **NO PASA**
- **X=0.08:** cambios 10 < 46 (cumple) · Sharpe -1.3357098911 ≥ 0.1979924878 (NO cumple) · drawdown 0.3977655311 ≤ 0.1780861289 (NO cumple) → **NO PASA**

## Combinación por X (AND entre calibración y verificación)

| X | Calibración | Verificación | Pasa el ciclo (AND) |
|---|---|---|---|
| 0.02 | NO PASA | NO PASA | **NO PASA** |
| 0.05 | NO PASA | NO PASA | **NO PASA** |
| 0.08 | NO PASA | NO PASA | **NO PASA** |

## Conclusión

Ningún valor de X de la grilla pre-registrada (0.02, 0.05, 0.08) pasa el
umbral de adopción en ambas ventanas. En calibración, los tres valores
reducen `cambios_de_posicion` frente al control, pero ninguno cumple
simultáneamente Sharpe ≥ control y drawdown ≤ control (X=0.02 y X=0.08
fallan ambas condiciones adicionales; X=0.05 falla Sharpe). En verificación
el resultado es más severo: el control (X=0.0, TSMOM k=14 sin banda) tiene
Sharpe positivo (0.1979924878) en la ventana 2025-07→presente, mientras que
los tres valores de X con banda tienen Sharpe negativo, y los tres empeoran
el drawdown frente al control. Ningún X está "casi" pasando en verificación:
las tres condiciones fallan a la vez para los tres valores.

Aplicando el criterio de salida pre-registrado ("si ninguno pasa → se
descarta la banda muerta para esta señal; la señal candidata sigue siendo
TSMOM k=14 long/flat sin banda"): **se descarta la banda muerta; la señal
candidata sigue siendo TSMOM k=14 long_flat sin banda, sin re-testear con
otra grilla sin una razón nueva.**
