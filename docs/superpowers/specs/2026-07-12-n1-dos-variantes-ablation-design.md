# Decisión N1: dos variantes de entrada + ablation de gates (P0-8)

**Fecha:** 2026-07-12
**Estado:** aprobado por Guille (diseño validado en sesión)
**Referencias:** `docs/revisiones/tercera-opinion-logica-implementacion-fable.md`
(propuesta N1, secciones 3.1 y 4), `docs/mejoras-propuestas.md` §6 (sweep de
umbrales 2026-07-03), `signals.py`, `state.py`, `backtest.py`.

## Contexto y problema

El sweep de umbrales de squeeze (7 variantes sobre abr–jun 2026, persistidas en
`backtest_runs/`) mostró que el modelo de entrada actual (fade/pre-break) pierde
en todas las calibraciones y que el win rate cae al abrir el embudo (25 trades →
20%, 173 → 10%). La tercera opinión identificó dos defectos estructurales que
impiden concluir nada definitivo todavía:

1. El bot no distingue soporte de resistencia: `_nearest_key_level` mezcla
   `swing_highs + swing_lows` y descarta el tipo, así que la dirección del fade
   se adivina a medias (`signals.py:15-21`).
2. La entrada por ruptura es **inalcanzable**: la vela que rompe el nivel no
   está comprimida, así que `update_squeeze` resetea el estado antes de que
   `check_entry_signal` pueda disparar en la dirección del break
   (`signals.py:57-61`).

La decisión N1 (qué modelo de entrada adoptar) quedó elevada como bloqueante
único de todo trabajo de señal. **Decisión tomada en sesión (2026-07-12):
implementar ambas variantes y decidir con el ablation P0-8.**

## Objetivo

1. **Variante A (fade con tipo de nivel):** la apuesta anticipada solo se arma
   coherente con el tipo real de nivel (soporte → LONG, resistencia → SHORT).
2. **Variante B (confirmación de ruptura):** la squeeze sobrevive a la vela de
   ruptura y la entrada se habilita en la dirección real del break.
3. **Harness de ablation (P0-8):** correr, por variante, la base (todos los
   gates) + una corrida por gate apagado, todo reproducible por CLI y
   persistido en `backtest_runs/`.
4. **Contadores de veto por gate** en cada corrida, para ver qué filtro mata
   cuántas señales sin necesidad de corridas extra.

## Criterio de adopción (pre-registrado, fijado ANTES de correr)

- Se adopta una variante **solo si su corrida base** (todos los gates activos)
  es **rentable neta de comisiones** en abr–jun 2026 **con ≥ 30 trades**.
- El ablation es diagnóstico, no búsqueda de la mejor combinación: si la base
  pierde pero "apagando el gate X gana", eso genera una hipótesis nueva a
  validar aparte, no adopción automática.
- Si ambas variantes pierden: no se adopta ninguna y se replantea la señal de
  fondo.
- Calibración del embudo para TODAS las corridas del ablation (pre-registrada):
  `SQUEEZE_COMPRESSION_ATR = 0.6`, `SQUEEZE_MIN_BARS = 2` — con la calibración
  base (0.4/3) hay ~0 trades por trimestre y no habría nada que medir.

## No-objetivos

- No se adopta ninguna variante en este trabajo; solo se produce la evidencia.
- No se toca el cost gate (P0-3), el scoring continuo (P2-3) ni ningún
  parámetro de riesgo.
- No se optimizan umbrales: una sola calibración de embudo, fijada arriba.
- El bot en vivo sigue corriendo el comportamiento actual hasta que la
  decisión se tome; ninguna variante se activa por defecto fuera del backtest.

## Componente 1 — Tipo de nivel (`signals.py`, base compartida)

`_nearest_key_level` pasa a devolver `(level, distance, kind)` con
`kind ∈ {"support", "resistance"}` según la lista de origen (`swing_lows` →
support, `swing_highs` → resistance). Ante empate exacto de distancia, gana el
nivel coherente con el lado del precio (soporte por debajo, resistencia por
encima); si tampoco, soporte.

## Componente 2 — Variante A: fade con tipo de nivel

En `update_squeeze` (armado de la squeeze):

- Comprimido + cerca de un **soporte** (swing low) y `last_price ≥ level` →
  `squeeze_direction = LONG` (rebote hacia arriba).
- Comprimido + cerca de una **resistencia** (swing high) y `last_price ≤ level`
  → `squeeze_direction = SHORT` (rebote hacia abajo).
- Nivel incoherente con el lado (p. ej. resistencia ya rota que quedó por
  debajo del precio) → la squeeze no se arma con dirección; sin señal.

`check_entry_signal` no cambia: consume `squeeze_direction` como hoy.

## Componente 3 — Variante B: confirmación de ruptura

Nuevo estado en `MarketState`:

```python
squeeze_broken: bool = False
squeeze_broken_direction: Optional[Side] = None
squeeze_broken_level: float = 0.0
squeeze_broken_ttl: int = 0      # velas de 15m restantes
```

En `update_squeeze`, ANTES del reset por vela no comprimida: si había una
squeeze armada (`in_squeeze`) y la vela cierra del otro lado del nivel de
referencia (`close > level` → LONG, `close < level` → SHORT), se setea
`squeeze_broken` con TTL = 2 velas de 15m. El TTL se decrementa por vela
cerrada; al llegar a 0 (o al abrirse una posición) se limpia todo el estado
broken. Un cierre exactamente en el nivel no es ruptura.

En modo variante B, `check_entry_signal` exige `squeeze_broken` (en lugar de
`in_squeeze`) y usa `squeeze_broken_direction`. Los demás gates corren igual.

La variante activa se selecciona con un parámetro de módulo
(`signals.ENTRY_VARIANT`, default `"fade"`), seteable desde el backtest. El
default preserva el comportamiento actual del bot en vivo (con el fix de tipo
de nivel del Componente 2, que corrige un defecto confirmado por las tres
revisiones y aplica también en vivo).

## Componente 4 — Gates apagables + contadores de veto

Los gates de `check_entry_signal` reciben nombre estable:

`regime_known`, `spread`, `trend_1h`, `macro`, `breakout_align`, `cvd`,
`ob_imbalance`.

- Un set de módulo `signals.DISABLED_GATES: set[str]` (default vacío); cada
  gate se saltea si su nombre está en el set. `in_squeeze`/`squeeze_broken` y
  `position is None` no son gates apagables (son la señal y una invariante).
- Contadores: `signals.GATE_VETO_COUNTS: dict[str, int]` incrementa cada vez
  que un gate rechaza una señal; también se cuenta `signals_fired`. El backtest
  los resetea al inicio y los persiste en `summary.json` bajo `gate_vetoes`.
  `backtest_html.write_index` los muestra si existen (tolerante a corridas
  viejas sin la clave).
- Los gates `macro` y `ob_imbalance` son **inertes en backtest** (defaults
  neutrales de `MarketState`): el runner los anota como `inert` en el reporte
  para que un veto-count de 0 no se lea como "no aporta".

## Componente 5 — CLI del backtest reproducible

`backtest.py` gana flags, todos registrados en `meta.json`:

- `--variant {fade,break}` (default `fade`)
- `--disable-gate <name>` (repetible; valida contra la lista de nombres)
- `--squeeze-compression <float>` y `--squeeze-min-bars <int>` (defaults: los
  de `config.py`) — el sweep anterior se hizo editando `config.py` a mano
  (meta con `git_dirty: true` y sin los umbrales); esto lo arregla.

Implementación: `signals.py` deja de importar las constantes de squeeze al
nivel de módulo y las lee vía `config.X` en el cuerpo de la función, para que
el backtest pueda sobreescribirlas (`config.SQUEEZE_COMPRESSION_ATR = ...`)
sin editar archivos.

## Componente 6 — Runner del ablation (`run_ablation.py`, nuevo)

CLI: `python run_ablation.py --start 2026-04-01 --end 2026-07-01`.

- Enumera: por cada variante (`fade`, `break`) → corrida base + una corrida
  por cada gate apagable **no inerte** (`regime_known`, `spread`, `trend_1h`,
  `breakout_align`, `cvd`) = 2 × 6 = **12 corridas**, secuenciales (pico de
  RAM ~2.2 GB por corrida; nunca en paralelo), ~11 min c/u ≈ 2.5 h.
- Todas con el embudo pre-registrado (0.6/2) y labels sistemáticos:
  `ablA-base`, `ablA-no-trend_1h`, …, `ablB-base`, `ablB-no-cvd`, …
- Es reanudable: si ya existe una corrida con el mismo label y los mismos
  parámetros en `backtest_runs/`, la saltea.
- Al final escribe `backtest_runs/ablation-<fecha>.md`: tabla por variante
  (corrida, trades, win rate, P&L neto, profit factor, vetos por gate), los
  gates inertes marcados, y el veredicto del criterio pre-registrado aplicado
  a las dos corridas base.

## Testing

TDD estricto (test primero) para:

1. `_nearest_key_level` con tipo: soporte/resistencia, empates, listas vacías.
2. Variante A: dirección por tipo de nivel; nivel incoherente → sin dirección.
3. Variante B: `squeeze_broken` se setea en la vela de ruptura, TTL expira a
   las 2 velas, cierre exacto en el nivel no rompe, entrada consume el estado.
4. Gates apagables: cada nombre saltea exactamente su gate; nombre inválido en
   CLI → error; contadores incrementan donde corresponde.
5. Overrides de CLI llegan a `config` y quedan en `meta.json`.
6. Regresión: la suite existente pasa sin cambios de comportamiento con
   defaults (variante fade + todos los gates + umbrales de config).

## Ejecución

En worktree aislado, plan por fases con subagentes Sonnet ejecutando y Fable
planificando/revisando (preferencia registrada). El ablation completo corre en
background al final; el veredicto se presenta con las dos corridas base contra
el criterio pre-registrado.
