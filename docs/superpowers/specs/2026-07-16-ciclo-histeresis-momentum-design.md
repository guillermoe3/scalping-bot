# Ciclo diseño de señal — banda muerta (histéresis) sobre TSMOM k=14 (spec)

Fecha: 2026-07-16
Estado: aprobada por Guille en sesión de brainstorming (decisiones firmadas
abajo).
Antecedente directo: el ciclo momentum multi-día cerró con veredicto
positivo (`backtest_runs/estudios/veredicto-momentum-2026-07.md`) — M1
(TSMOM) y M2 (P/MA) pasan en BTC, calibración y verificación. Su criterio de
salida pre-registrado ("si al menos una celda de M1 o M2 pasa... siguiente
ciclo = brainstorming de diseño de señal") habilita este ciclo.

## Propósito

La señal ganadora (TSMOM k=14, long/flat, BTC spot) cambia de posición cada
vez que el retorno de 14 días cruza cero. Este ciclo prueba UNA pregunta:
**¿envolver esa señal en una banda muerta (histéresis) reduce la cantidad de
cambios de posición sin empeorar Sharpe ni drawdown?** No es un ciclo de "¿la
señal existe?" (eso ya se contestó); es un ciclo de "¿se puede operar más
barato sin perder lo que ya funciona?".

Cero código del bot en este ciclo. Si la banda pasa, la integración
operativa (convivencia con el bot de scalping, kill switch, gates
adicionales) es un ciclo aparte.

## Decisiones firmadas en el brainstorming (2026-07-16)

1. **Alcance:** solo la celda ganadora del ciclo anterior — TSMOM k=14,
   long/flat, BTC. No se repite en k=28 ni en P/MA este ciclo.
2. **Mecanismo:** banda muerta simétrica sobre el retorno de 14 días. Entra
   largo si retorno > X; pasa a flat si retorno ≤ -X; si cae en el interior
   (-X, X], mantiene la posición del día anterior. (Los bordes son
   asimétricos a propósito: así, con X=0%, las dos condiciones ">0" y "≤0"
   cubren todos los casos sin dejar ningún interior ambiguo — ver punto 3.)
3. **Grilla de X (pre-registrada, fija):** 0%, 2%, 5%, 8%. Con X=0% el
   interior de la banda es vacío (retorno > 0 → largo, retorno ≤ 0 → flat,
   sin caso intermedio), así que degenera exactamente en
   `posiciones_tsmom(closes, 14, "long_flat")` ya existente — este es el
   control de sanidad, verificado con un test de igualdad de listas (no
   aproximado).
4. **Base:** señal cruda, sin el overlay de vol-targeting (M3 del ciclo
   anterior) encima. Se aísla el efecto de la banda; el overlay se puede
   reaplicar después en otro ciclo si hace falta.
5. **Split de datos — ventana nueva, no reusar la ya gastada:** la ventana
   de verificación 2024-01→2026 ya se miró una vez para adoptar M1/M2.
   Volver a mirarla para afinar X sería sobreajuste silencioso. Se sella una
   ventana nueva y más reciente, nunca vista: **calibración
   2017-08-01 → 2025-06-30, verificación 2025-07-01 → hoy (12 meses),
   sellada**. Corte: `CORTE_HISTERESIS_MS = 1751328000000`
   (2025-07-01T00:00:00Z).
6. **Criterio de éxito (sin tolerancia, "casi" = NO PASA):** para cada X>0,
   comparado contra el control (X=0%) en cada ventana por separado, pasa si
   simultáneamente:
   - menos cambios de posición que el control, Y
   - Sharpe ≥ Sharpe del control, Y
   - max drawdown ≤ max drawdown del control.
   Debe cumplirse en calibración Y en verificación evaluadas por separado
   para que ese X se considere ganador.

## No-objetivos

- No se escribe código del bot ni se decide convivencia operativa con el
  bot de scalping en este ciclo.
- No se prueba la banda sobre k=28 ni sobre P/MA (queda para un ciclo de
  robustez posterior, si hace falta).
- No se reintroduce el overlay de vol-targeting en este ciclo.
- No gates adicionales, no cadencia de rebalanceo distinta a diaria — esos
  quedan para ciclos de diseño de señal posteriores si este pasa.
- No paper trading.

## Datos

- Reusa `daily_history.py` tal cual (velas diarias BTC spot, ya cacheadas
  desde el ciclo anterior — sin descargas nuevas necesarias salvo meses que
  falten al momento de correr).
- Reusa `estudios/nucleo.py` (`ventana`, `retorno_forward`, `resumen`,
  `serie_estrategia`, `sharpe_anualizado`, `max_drawdown`, `peor_mes`,
  `metricas_estrategia`) sin tocar las funciones existentes.

## Convenciones de cálculo

Mismas convenciones que el ciclo momentum anterior (sin lookahead, Sharpe
anualizado × √365, max drawdown sobre producto acumulado, sin costos de
transacción modelados — pre-registrado igual que M1-M3: con 1-6 cambios de
estado/mes el drag de fees es marginal frente al objetivo de este ciclo, que
es contar operaciones, no modelar su costo en dólares).

- **Burn-in:** 14 días (el único lookback de este estudio; no hace falta el
  margen de 90 días que usaba M1 porque acá no hay grilla de lookbacks).
- **Posición con banda:** `posiciones_tsmom_banda(closes, k=14, x)` — a
  diferencia de `posiciones_tsmom`, esta función es *stateful* día a día:
  la posición de hoy depende de la posición de ayer cuando el retorno cae
  dentro de (-x, +x).

## Estudio — banda muerta sobre TSMOM k=14

- **Señal:** retorno acumulado de los últimos 14 días, igual que M1.
- **Posición con banda `posiciones_tsmom_banda(closes, 14, x)`:**
  - retorno > x → posición = 1 (largo)
  - retorno ≤ -x → posición = 0 (flat)
  - -x < retorno ≤ x (interior, solo existe si x>0) → posición = posición
    del día anterior. El primer día evaluable (no tiene día anterior) usa
    posición = 0 (flat) si cae en el interior — default explícito, sin
    posición previa que mantener.
- **Conteo de operaciones:** nueva función `cambios_de_posicion(posiciones)`
  en `nucleo.py` — cuenta cuántos días la posición difiere de la del día
  anterior. Se aplica igual al control (X=0%) y a cada X>0.
- **Métricas por celda (una celda por X):** Sharpe, max drawdown, media y
  mediana de `r_strat` sobre días en posición, cambios de posición — mismo
  patrón de `metricas_estrategia` ya existente, extendido con el conteo.
- **4 celdas** (una por valor de X), evaluadas en 2 ventanas (calibración,
  verificación) = 8 filas de reporte.

## Umbral de adopción (pre-registrado — verbatim en el reporte)

Un valor de X>0 **pasa** si, en calibración Y en verificación evaluadas por
separado (la verificación entera, sin subventanas), comparado contra el
control X=0% de la misma ventana:

1. cambios de posición de X < cambios de posición del control, Y
2. Sharpe de X ≥ Sharpe del control, Y
3. max drawdown de X ≤ max drawdown del control.

"Casi" = NO PASA, sin excepciones — mismo criterio que todos los ciclos
anteriores.

## Criterio de salida del ciclo (pre-registrado)

- **Si algún X>0 pasa en ambas ventanas:** se adopta ese valor de X (el de
  mayor reducción de operaciones entre los que pasan) como parte de la señal
  candidata. Próximo ciclo posible: robustez en k=28/P/MA, o integración
  operativa con el bot de scalping — decisión de Guille en su momento.
- **Si ninguno pasa:** se descarta la banda muerta para esta señal; la señal
  candidata sigue siendo TSMOM k=14 long/flat sin banda (el resultado del
  ciclo anterior, intacto). No se re-testea la banda con otra grilla sin
  una razón nueva.

## Arquitectura

- `estudios/estudio_histeresis.py` (nuevo): mismo esqueleto CLI que
  `estudio_momentum.py` (`--parametro` para X, `--modo calibracion|verificacion`,
  `--verificacion` como gate explícito), reporte vía el mismo patrón de
  `escribir_reporte` con el pre-registro verbatim.
- `estudios/nucleo.py`: se agregan `posiciones_tsmom_banda` y
  `cambios_de_posicion` sin tocar ninguna función existente. Se agrega
  `CORTE_HISTERESIS_MS = 1751328000000` junto a las otras constantes
  `CORTE_*_MS`.
- Sin dependencias nuevas, sin pandas/numpy — mismo criterio que el ciclo
  anterior (volumen de datos trivial).

## Testing y proceso

- TDD estricto por task (failing-first con los valores pre-registrados;
  suite completa verde en cada commit).
- `posiciones_tsmom_banda`: tests a mano — retorno claramente positivo →
  largo; claramente negativo → flat; dentro de la banda (-x, x] → mantiene
  la posición anterior; primer día en el interior sin posición previa →
  flat; **X=0% reproduce exactamente** `posiciones_tsmom(closes, 14,
  "long_flat")` sobre la misma serie (test de igualdad de listas, no
  aproximado).
- `cambios_de_posicion`: tests a mano con series cortas conocidas.
- El candado de verificación NO se reimplementa: se hereda de
  `nucleo.ventana` con el nuevo `CORTE_HISTERESIS_MS` pasado explícito.
- Flujo igual a los ciclos anteriores: plan → subagentes → revisión por
  task → calibración → congelamiento → checkpoint de Guille → verificación
  única → veredicto (`backtest_runs/estudios/veredicto-histeresis-YYYY-MM.md`)
  con los umbrales copiados verbatim y conclusión PASA / NO PASA por X.
- El reporte de calibración y de verificación se commitean (evidencia del
  ciclo), como en los ciclos anteriores.
