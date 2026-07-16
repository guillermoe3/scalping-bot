# Veredicto del ciclo de momentum multi-día — 2026-07

Spec: `docs/superpowers/specs/2026-07-15-ciclo-momentum-multidia-design.md`
Plan: `docs/superpowers/plans/2026-07-15-ciclo-momentum-multidia.md`

Corridas evaluadas (todas en este directorio):

| Estudio | Calibración | Verificación |
|---|---|---|
| M1 TSMOM | `2026-07-15_23-43-51_momentum-calibracion` | `2026-07-16_00-13-24_momentum-verificacion` |
| M2 P/MA | `2026-07-15_23-48-50_ma-calibracion` | `2026-07-16_00-13-29_ma-verificacion` |
| M3 vol overlay (condicional) | `2026-07-16_00-36-43_vol-overlay-calibracion` | `2026-07-16_00-37-03_vol-overlay-verificacion` |
| M4 instrumento (condicional) | `2026-07-16_00-36-48_instrumento-calibracion` | `2026-07-16_00-36-48_instrumento-verificacion` |

La ventana de verificación se abrió el 2026-07-16 con OK explícito de Guille
(checkpoint de la Task 7), con M1 y M2 congelados y revisados (code review
independiente con recomputo bit-a-bit idéntico en ambos). Cada script se
corrió UNA vez en modo verificación. No hubo re-corridas post-fix.

Convenciones: "cal" = calibración (2017-08→2023-12), "ver" = verificación
(2024-01→hoy). Umbral por celda (M1/M2, verbatim de la spec): *Sharpe
estrategia > Sharpe buy-and-hold, Y max drawdown estrategia < buy-and-hold,
Y media de r_strat > 0, Y mediana de r_strat sobre los días con posición >
0 — en calibración Y en verificación por separado.* "Casi" = NO PASA. Solo
BTC adopta/veta; ETH robustez.

---

## Estudio M1 — TSMOM (tasa base)

### Tabla completa (10 celdas BTC + 10 celdas ETH robustez)

| Símbolo | Lookback | Variante | Sharpe cal | Sharpe cal B&H | Pasa cal | Sharpe ver | Sharpe ver B&H | MDD ver | MDD ver B&H | Media ver | Mediana ver | Pasa ver |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 7d | long_short | 0.50 | 0.86 | no | -0.19 | 0.51 | 70.8% | 53.0% | -0.025% | -0.087% | - |
| BTCUSDT | 7d | long_flat | 1.00 | 0.86 | no | 0.24 | 0.51 | 40.4% | 53.0% | +0.021% | -0.061% | - |
| BTCUSDT | 14d | long_short | 0.88 | 0.86 | sí | 0.87 | 0.51 | 46.4% | 53.0% | +0.115% | +0.072% | **PASA** |
| BTCUSDT | 14d | long_flat | 1.26 | 0.86 | sí | 1.04 | 0.51 | 26.7% | 53.0% | +0.091% | +0.096% | **PASA** |
| BTCUSDT | 28d | long_short | 0.97 | 0.86 | no | 0.34 | 0.51 | 52.4% | 53.0% | +0.045% | +0.068% | - |
| BTCUSDT | 28d | long_flat | 1.34 | 0.86 | sí | 0.62 | 0.51 | 33.8% | 53.0% | +0.056% | +0.071% | **PASA** |
| BTCUSDT | 56d | long_short | 1.11 | 0.86 | sí | 0.17 | 0.51 | 63.8% | 53.0% | +0.023% | +0.004% | cal sí / ver no |
| BTCUSDT | 56d | long_flat | 1.34 | 0.86 | sí | 0.49 | 0.51 | 42.6% | 53.0% | +0.045% | +0.010% | cal sí / ver no |
| BTCUSDT | 90d | long_short | 0.49 | 0.86 | no | 0.81 | 0.51 | 38.2% | 53.0% | +0.106% | +0.056% | - |
| BTCUSDT | 90d | long_flat | 0.81 | 0.86 | no | 0.90 | 0.51 | 24.5% | 53.0% | +0.084% | +0.046% | - |
| ETHUSDT | 7d | long_short | 0.95 | 0.81 | no | 0.48 | 0.13 | 59.1% | 67.6% | +0.090% | -0.086% | - |
| ETHUSDT | 7d | long_flat | 1.29 | 0.81 | sí | 0.47 | 0.13 | 44.6% | 67.6% | +0.057% | -0.086% | cal sí / ver no |
| ETHUSDT | 14d | long_short | 0.68 | 0.81 | no | 0.55 | 0.13 | 58.3% | 67.6% | +0.105% | +0.050% | - |
| ETHUSDT | 14d | long_flat | 1.02 | 0.81 | sí | 0.53 | 0.13 | 42.0% | 67.6% | +0.064% | +0.129% | PASA (robustez) |
| ETHUSDT | 28d | long_short | 0.63 | 0.81 | no | 0.62 | 0.13 | 61.3% | 67.6% | +0.117% | +0.050% | - |
| ETHUSDT | 28d | long_flat | 1.02 | 0.81 | sí | 0.60 | 0.13 | 43.7% | 67.6% | +0.070% | +0.094% | PASA (robustez) |
| ETHUSDT | 56d | long_short | 0.85 | 0.81 | sí | 1.17 | 0.13 | 47.3% | 67.6% | +0.222% | +0.087% | PASA (robustez) |
| ETHUSDT | 56d | long_flat | 1.07 | 0.81 | sí | 0.99 | 0.13 | 39.3% | 67.6% | +0.123% | +0.109% | PASA (robustez) |
| ETHUSDT | 90d | long_short | 0.44 | 0.81 | no | 0.78 | 0.13 | 59.8% | 67.6% | +0.148% | +0.085% | - |
| ETHUSDT | 90d | long_flat | 0.81 | 0.81 | no | 0.65 | 0.13 | 42.4% | 67.6% | +0.085% | +0.109% | - |

### Evaluación

**3 celdas de BTC pasan las cuatro condiciones en ambas ventanas por separado:**
14d long_short, 14d long_flat, 28d long_flat. Dos celdas más (56d, ambas
variantes) pasan calibración pero no sostienen en verificación — el Sharpe
cae de ~1.1-1.3 a 0.17-0.49 y queda por debajo del buy-and-hold en
verificación (0.51). El patrón es consistente con la advertencia de régimen
de la spec: el lookback óptimo se acorta en la era institucional (14-28
días sobrevive, 56-90 días no).

ETH confirma el patrón central: 14d, 28d y 56d long_flat también pasan
ambas ventanas — coherente con BTC, sin contradecirlo.

### Conclusión M1: **PASA** (BTC, celdas 14d long_short, 14d long_flat, 28d long_flat)

---

## Estudio M2 — P/MA (réplica de Detzel et al.)

### Tabla completa (4 celdas BTC + 4 celdas ETH robustez)

| Símbolo | MA | Sharpe cal | Sharpe cal B&H | Pasa cal | Sharpe ver | Sharpe ver B&H | MDD ver | MDD ver B&H | Media ver | Mediana ver | Pasa ver |
|---|---|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 10d | 0.98 | 0.86 | no | 0.70 | 0.51 | 32.1% | 53.0% | +0.062% | -0.004% | - |
| BTCUSDT | 20d | 1.14 | 0.86 | sí | 0.69 | 0.51 | 32.0% | 53.0% | +0.061% | +0.047% | **PASA** |
| BTCUSDT | 50d | 1.41 | 0.86 | sí | 0.93 | 0.51 | 25.8% | 53.0% | +0.084% | +0.071% | **PASA** |
| BTCUSDT | 100d | 1.12 | 0.86 | sí | 0.77 | 0.51 | 35.0% | 53.0% | +0.071% | +0.047% | **PASA** |
| ETHUSDT | 10d | 0.92 | 0.81 | no | 0.25 | 0.13 | 51.9% | 67.6% | +0.030% | -0.116% | - |
| ETHUSDT | 20d | 1.17 | 0.81 | sí | 0.41 | 0.13 | 45.6% | 67.6% | +0.052% | +0.009% | PASA (robustez) |
| ETHUSDT | 50d | 1.10 | 0.81 | sí | 0.93 | 0.13 | 36.7% | 67.6% | +0.112% | +0.109% | PASA (robustez) |
| ETHUSDT | 100d | 0.91 | 0.81 | sí | 0.54 | 0.13 | 45.3% | 67.6% | +0.065% | +0.100% | PASA (robustez) |

### Evaluación

**3 de las 4 celdas de BTC pasan las cuatro condiciones en ambas ventanas:**
MA de 20, 50 y 100 días (solo MA 10 falla, y falla ya en calibración). MA 50
es la mejor por Sharpe en ambas ventanas (1.41 cal, 0.93 ver). ETH confirma
el mismo patrón en las mismas tres MAs.

### Regla de fragilidad (pre-registrada)

M1 y M2 **no discrepan**: ambos pasan en BTC sobre horizontes económicamente
equivalentes (M1 pasa en 14-28 días de retorno acumulado; M2 pasa en medias
móviles de 20-100 días, que ponderan aproximadamente esa misma escala de
tiempo reciente). Es evidencia convergente de dos especificaciones
distintas de la misma familia — reduce, no aumenta, la sospecha de que el
resultado sea ruido de una especificación puntual (mismo argumento
metodológico que Hudson & Urquhart 2021 citado en el documento de
insights).

### Conclusión M2: **PASA** (BTC, celdas MA 20d, 50d, 100d)

---

## Criterio de salida — evaluado

Texto pre-registrado (spec, verbatim): *"Si al menos una celda de M1 o M2
pasa el umbral en BTC: siguiente ciclo = brainstorming de diseño de señal
(histéresis, gates, convivencia operativa con el bot actual, harness de
ablación), llevando M3/M4 ya respondidos."*

**Se cumple.** M1 y M2 pasan en múltiples celdas de BTC, en ambas ventanas,
de forma mutuamente consistente. A diferencia del ciclo intradía anterior
(C1/C2/C3, todos rechazados), esta es la primera vez en el proyecto que un
estudio de tasa base pre-registrado sobrevive intacto a su ventana de
verificación sellada.

Por eso M3 y M4 corrieron sobre la celda ganadora (mayor Sharpe de
verificación en BTC): **M1, lookback 14 días, variante long_flat**.

---

## Estudio M3 — overlay de vol targeting (condicional, corrido)

**Umbral pre-registrado:** en calibración Y verificación: mejora max
drawdown Y peor mes calendario vs la versión cruda, Y media de r_strat ≥ ½
de la cruda.

| σ_target | MDD cal (cruda 65.5%) | Peor mes cal (cruda -35.2%) | Media cal (cruda +0.174%; mitad = +0.087%) | Pasa cal | MDD ver (cruda 26.7%) | Peor mes ver (cruda -12.0%) | Media ver (cruda +0.091%; mitad = +0.046%) | Pasa ver |
|---|---|---|---|---|---|---|---|---|
| 0.20 | 26.9% (mejora) | -7.4% (mejora) | +0.067% (< mitad, NO) | no | 12.3% (mejora) | -4.2% (mejora) | +0.045% (≈mitad, **casi** NO) | no |
| 0.30 | 37.5% (mejora) | -10.9% (mejora) | +0.095% (≥ mitad, sí) | **PASA** | 16.7% (mejora) | -6.2% (mejora) | +0.067% (≥ mitad, sí) | **PASA** |
| 0.40 | 43.7% (mejora) | -11.8% (mejora) | +0.116% (≥ mitad, sí) | **PASA** | 18.4% (mejora) | -7.6% (mejora) | +0.087% (≥ mitad, sí) | **PASA** |

σ_target=0.20 falla la condición de media en las dos ventanas (en
verificación por un margen mínimo: +0.04542% vs el umbral +0.04552% —
"casi" = NO PASA, sin excepción). σ_target=0.30 y 0.40 cumplen las tres
condiciones en ambas ventanas: el drawdown de la celda cruda (65.5%
calibración) se reduce a 37-44%, y en verificación de 26.7% a 17-18%, sin
sacrificar más de la mitad de la media.

### Conclusión M3: **ADOPTAR overlay con σ_target ∈ {0.30, 0.40}** — reduce sustancialmente drawdown y peor mes sin destruir la media, en ambas ventanas.

---

## Estudio M4 — costo de instrumento (condicional, corrido)

**Sin umbral — el número decide.** Ventana 2020-01→hoy (cobertura del
funding cacheado), pata long de la celda ganadora (M1 14d long_flat).

| Ventana | n_días | Retorno total SPOT (sin funding) | Retorno total PERP (neto de funding) | Sharpe SPOT | Sharpe PERP | Drag de retorno total |
|---|---|---|---|---|---|---|
| Calibración (2020-01→2023-12) | 1460 | +751.5% | +433.2% | 1.41 | 1.15 | 318.3 puntos porcentuales |
| Verificación (2024-01→hoy) | 912 | +102.2% | +79.9% | 1.04 | 0.90 | 22.3 puntos porcentuales |

El costo de funding es material y consistente en las dos ventanas: reduce
el Sharpe en ~0.15-0.26 y se come una fracción grande del retorno acumulado
(más extremo en calibración, que incluye el bull run 2020-2021 con funding
persistentemente positivo). La pata long de esta estrategia rinde
sistemáticamente mejor en SPOT que en PERP.

### Conclusión M4: **el número favorece SPOT para la pata long** — decisión de instrumento para el ciclo de diseño de señal (aproximación documentada: precio spot + funding de futuros, base ignorada).

---

## Cierre: siguiente paso

Por el criterio de salida pre-registrado, corresponde abrir el **siguiente
ciclo: brainstorming de diseño de señal** sobre la hipótesis ganadora
(momentum de 14-28 días en BTC, long/flat), con M3 y M4 ya respondidos:

- **Señal candidata:** TSMOM long/flat, lookback 14 días (mejor Sharpe de
  verificación) o 28 días (también robusta); MA de 50 días como alternativa
  de especificación con evidencia igualmente fuerte.
- **Overlay de vol targeting:** adoptar, σ_target 0.30-0.40 anualizado,
  tope 1×.
- **Instrumento de la pata long:** spot (perp descartado por el drag de
  funding, salvo que el diseño de señal encuentre una razón operativa de
  peso para preferirlo).
- Pendiente para ese ciclo (no resuelto acá, por diseño — fuera del alcance
  de estudios de tasa base): histéresis/banda muerta, gates adicionales,
  convivencia operativa con el bot de scalping actual (¿proceso separado?),
  kill switch a escala diaria/semanal, y el harness de ablación reusado
  sobre esta hipótesis.

Esta decisión de abrir el ciclo de diseño es de Guille — el veredicto solo
constata que el criterio de salida pre-registrado se cumplió.
