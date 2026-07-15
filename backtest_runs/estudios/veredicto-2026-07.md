# Veredicto del ciclo de estudios de tasa base — 2026-07

Spec: `docs/superpowers/specs/2026-07-14-ciclo-limpieza-y-estudios-tasa-base-design.md`
Plan: `docs/superpowers/plans/2026-07-14-ciclo-limpieza-y-estudios-tasa-base.md`

Corridas evaluadas (todas en este directorio):

| Estudio | Calibración | Verificación |
|---|---|---|
| C2 sesión | `2026-07-14_20-56-33_sesion-calibracion` | `2026-07-15_15-54-09_sesion-verificacion` |
| C1 funding | `2026-07-15_00-21-10_funding-calibracion` | `2026-07-15_15-53-57_funding-verificacion` |
| C3 cascadas | `2026-07-15_15-28-10_cascadas-calibracion` | `2026-07-15_15-54-04_cascadas-verificacion` |

La ventana de verificación se abrió el 2026-07-15 con OK explícito de Guille
(checkpoint de la Task 11), con los tres scripts congelados tras revisión de
código. Cada script se corrió UNA vez en modo verificación. No hubo
re-corridas post-fix: ningún bug apareció después de la verificación.

Convenciones: retornos firmados según la tesis del estudio (positivo = la
tesis ganó). "cal" = calibración, "ver" = verificación. Los valores
completos, con media incluida para C2, están en los `resultados.json` de
cada corrida.

---

## Estudio C1 — funding extremo (la apuesta principal del ciclo)

**Umbral pre-registrado (spec, verbatim):**

> **Umbral de adopción (pre-registrado):** para BTC, en AL MENOS un
> horizonte: mediana firmada ≥ 0.14% (2× costos) Y media del mismo signo Y
> hit rate > 50% — en calibración Y sostenido en verificación (mismo signo,
> magnitud ≥ la mitad de la de calibración). ETH se reporta por separado
> como robustez; no adopta ni veta por sí solo.

### Tabla C1 (todas las celdas)

| Símbolo | Cola | Horizonte | n cal | mediana cal | media cal | hit cal | n ver | mediana ver | media ver | hit ver |
|---|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT | alta | 8h | 156 | -0.107% | -0.115% | 45.5% | 72 | -0.136% | +0.016% | 43.1% |
| BTCUSDT | alta | 24h | 156 | -0.128% | -0.192% | 46.8% | 71 | +0.182% | +0.155% | 52.1% |
| BTCUSDT | alta | 72h | 156 | -0.560% | -0.510% | 44.9% | 70 | +0.180% | +0.203% | 52.9% |
| BTCUSDT | baja | 8h | 340 | +0.055% | +0.076% | 52.6% | 126 | -0.222% | -0.230% | 36.5% |
| BTCUSDT | baja | 24h | 340 | +0.294% | +0.613% | 57.4% | 126 | -0.153% | -0.349% | 41.3% |
| BTCUSDT | baja | 72h | 339 | +0.463% | +0.992% | 56.3% | 126 | -0.012% | -0.062% | 50.0% |
| ETHUSDT | alta | 8h | 172 | +0.073% | -0.022% | 50.6% | 63 | -0.228% | -0.154% | 41.3% |
| ETHUSDT | alta | 24h | 172 | +0.184% | -0.189% | 52.3% | 63 | +0.519% | +0.274% | 57.1% |
| ETHUSDT | alta | 72h | 172 | -0.478% | -0.964% | 44.8% | 63 | -0.217% | -0.758% | 44.4% |
| ETHUSDT | baja | 8h | 309 | +0.147% | -0.025% | 55.3% | 111 | -0.054% | -0.573% | 46.8% |
| ETHUSDT | baja | 24h | 309 | +0.260% | +0.179% | 53.7% | 111 | -0.081% | -0.412% | 48.6% |
| ETHUSDT | baja | 72h | 309 | +1.119% | +0.878% | 58.9% | 111 | -0.332% | -0.470% | 45.0% |

### Evaluación contra el umbral

- **n mínimo:** cumplido en calibración (todas las colas ≥ 150 por símbolo).
- **Calibración (BTC, el único que adopta/veta):** la cola **baja** (funding
  extremo negativo → tesis LONG) cumple el umbral completo en **24h**
  (mediana +0.294% ≥ 0.14%, media +0.613% mismo signo, hit 57.4% > 50%) y en
  **72h** (mediana +0.463%, media +0.992%, hit 56.3%). La cola **alta**
  (tesis SHORT) falla en los tres horizontes — medianas y medias negativas:
  en 2020-2024 el precio siguió subiendo tras el funding extremo positivo.
- **Verificación (2025-01→presente) de las celdas que pasaron calibración:**
  - baja 24h: mediana **-0.153%** (signo invertido), media -0.349%, hit
    41.3%. No sostiene.
  - baja 72h: mediana **-0.012%** (signo invertido), media -0.062%, hit
    50.0%. No sostiene.
- **Robustez ETH:** coherente con BTC en el fracaso — las celdas baja
  24h/72h que acompañaban en calibración también invierten el signo en
  verificación. (La única celda de verificación que luce bien, ETH alta 24h,
  no pasó calibración y ETH no adopta por sí solo.)

La inversión es total: la tesis "comprar cuando los bajistas pagan funding
extremo" ganaba en la era 2020-2024 y pierde en la era 2025→presente. No es
un caso "casi": el signo se dio vuelta en las dos celdas candidatas.

### Conclusión C1: **NO PASA**

---

## Estudio C2 — sesión/hora del día

**Rol pre-registrado (spec):** insumo, NO señal. No hay umbral de adopción.

### Tabla C2 (96 celdas: 24 horas × hábil/finde × 2 símbolos)

#### BTCUSDT

| Bucket | n cal | mediana cal | hit cal | n ver | mediana ver | hit ver |
|---|---|---|---|---|---|---|
| 00_finde | 2088 | +0.006% | 51.1% | 624 | +0.007% | 52.9% |
| 00_habil | 5220 | -0.004% | 49.4% | 1560 | -0.002% | 49.6% |
| 01_finde | 2088 | -0.004% | 49.1% | 624 | -0.002% | 49.0% |
| 01_habil | 5220 | -0.005% | 49.2% | 1560 | +0.003% | 50.7% |
| 02_finde | 2088 | -0.000% | 49.7% | 624 | +0.006% | 52.1% |
| 02_habil | 5220 | +0.001% | 50.2% | 1560 | -0.014% | 46.5% |
| 03_finde | 2088 | +0.000% | 50.0% | 624 | +0.005% | 52.2% |
| 03_habil | 5220 | -0.000% | 49.8% | 1560 | -0.004% | 48.8% |
| 04_finde | 2088 | +0.000% | 50.0% | 624 | -0.005% | 47.8% |
| 04_habil | 5220 | -0.005% | 48.9% | 1560 | -0.004% | 48.5% |
| 05_finde | 2088 | +0.004% | 51.6% | 624 | -0.002% | 49.4% |
| 05_habil | 5220 | +0.006% | 51.2% | 1560 | +0.000% | 50.1% |
| 06_finde | 2088 | +0.000% | 50.1% | 624 | -0.007% | 46.6% |
| 06_habil | 5220 | +0.003% | 50.6% | 1560 | +0.001% | 50.2% |
| 07_finde | 2088 | +0.001% | 50.3% | 624 | -0.003% | 49.0% |
| 07_habil | 5220 | -0.001% | 49.6% | 1560 | +0.000% | 50.0% |
| 08_finde | 2088 | -0.010% | 47.3% | 624 | -0.001% | 49.8% |
| 08_habil | 5220 | -0.004% | 49.0% | 1560 | +0.002% | 50.3% |
| 09_finde | 2088 | +0.000% | 49.9% | 624 | -0.001% | 49.7% |
| 09_habil | 5220 | +0.002% | 50.6% | 1560 | -0.002% | 49.7% |
| 10_finde | 2088 | -0.003% | 49.0% | 624 | +0.003% | 50.6% |
| 10_habil | 5220 | +0.007% | 51.4% | 1560 | -0.001% | 49.7% |
| 11_finde | 2088 | +0.001% | 50.2% | 624 | +0.001% | 50.6% |
| 11_habil | 5220 | +0.001% | 50.2% | 1560 | -0.005% | 49.0% |
| 12_finde | 2088 | -0.002% | 49.0% | 624 | +0.001% | 50.3% |
| 12_habil | 5220 | +0.003% | 50.4% | 1560 | -0.008% | 48.0% |
| 13_finde | 2088 | -0.000% | 50.0% | 624 | -0.002% | 49.5% |
| 13_habil | 5220 | -0.004% | 49.6% | 1560 | -0.003% | 49.2% |
| 14_finde | 2088 | +0.008% | 51.9% | 624 | +0.015% | 53.4% |
| 14_habil | 5220 | +0.009% | 51.1% | 1560 | -0.003% | 49.6% |
| 15_finde | 2088 | +0.008% | 51.4% | 624 | -0.005% | 48.6% |
| 15_habil | 5220 | +0.000% | 50.0% | 1560 | +0.011% | 51.3% |
| 16_finde | 2088 | +0.000% | 50.0% | 624 | -0.005% | 49.0% |
| 16_habil | 5220 | -0.005% | 49.1% | 1560 | -0.003% | 49.4% |
| 17_finde | 2088 | -0.001% | 49.8% | 624 | +0.003% | 51.6% |
| 17_habil | 5220 | +0.005% | 50.7% | 1560 | +0.012% | 52.1% |
| 18_finde | 2088 | +0.006% | 51.7% | 624 | +0.000% | 50.3% |
| 18_habil | 5220 | +0.004% | 50.8% | 1560 | -0.004% | 49.2% |
| 19_finde | 2088 | +0.001% | 50.3% | 624 | -0.004% | 48.9% |
| 19_habil | 5220 | +0.012% | 51.9% | 1560 | +0.005% | 50.8% |
| 20_finde | 2088 | +0.005% | 51.2% | 624 | -0.004% | 48.2% |
| 20_habil | 5220 | +0.014% | 52.3% | 1560 | +0.013% | 52.9% |
| 21_finde | 2088 | +0.006% | 51.4% | 624 | +0.004% | 51.4% |
| 21_habil | 5220 | +0.009% | 51.9% | 1560 | +0.005% | 51.7% |
| 22_finde | 2088 | +0.002% | 50.4% | 624 | +0.007% | 51.8% |
| 22_habil | 5220 | +0.001% | 50.2% | 1560 | -0.003% | 49.0% |
| 23_finde | 2088 | -0.006% | 48.1% | 624 | +0.003% | 50.6% |
| 23_habil | 5219 | -0.001% | 49.8% | 1559 | -0.002% | 49.7% |

#### ETHUSDT

| Bucket | n cal | mediana cal | hit cal | n ver | mediana ver | hit ver |
|---|---|---|---|---|---|---|
| 00_finde | 2088 | +0.008% | 51.2% | 624 | +0.011% | 51.6% |
| 00_habil | 5220 | -0.003% | 49.6% | 1560 | -0.007% | 49.2% |
| 01_finde | 2088 | -0.007% | 48.9% | 624 | -0.010% | 48.1% |
| 01_habil | 5220 | -0.004% | 49.2% | 1560 | +0.007% | 50.8% |
| 02_finde | 2088 | -0.009% | 48.3% | 624 | -0.001% | 49.4% |
| 02_habil | 5220 | +0.000% | 49.9% | 1560 | -0.024% | 46.3% |
| 03_finde | 2088 | -0.001% | 49.4% | 624 | +0.010% | 51.8% |
| 03_habil | 5220 | +0.003% | 50.4% | 1560 | +0.005% | 50.4% |
| 04_finde | 2088 | +0.005% | 51.0% | 624 | +0.002% | 50.6% |
| 04_habil | 5220 | -0.001% | 49.6% | 1560 | -0.003% | 49.5% |
| 05_finde | 2088 | +0.008% | 51.7% | 624 | +0.008% | 51.6% |
| 05_habil | 5220 | +0.005% | 50.9% | 1560 | +0.006% | 50.8% |
| 06_finde | 2088 | +0.003% | 50.5% | 624 | -0.016% | 45.8% |
| 06_habil | 5220 | +0.004% | 50.6% | 1560 | +0.016% | 52.1% |
| 07_finde | 2088 | -0.001% | 49.7% | 624 | +0.002% | 50.2% |
| 07_habil | 5220 | +0.005% | 50.8% | 1560 | +0.003% | 50.6% |
| 08_finde | 2088 | -0.009% | 48.4% | 624 | -0.002% | 48.9% |
| 08_habil | 5220 | -0.006% | 49.0% | 1560 | -0.005% | 49.4% |
| 09_finde | 2088 | +0.002% | 50.3% | 624 | +0.002% | 50.6% |
| 09_habil | 5220 | +0.004% | 50.6% | 1560 | -0.007% | 49.2% |
| 10_finde | 2088 | -0.004% | 48.5% | 624 | +0.003% | 50.3% |
| 10_habil | 5220 | +0.013% | 52.1% | 1560 | -0.001% | 49.7% |
| 11_finde | 2088 | +0.000% | 49.9% | 624 | +0.001% | 50.0% |
| 11_habil | 5220 | +0.006% | 50.9% | 1560 | +0.004% | 50.4% |
| 12_finde | 2088 | -0.000% | 49.7% | 624 | +0.011% | 52.9% |
| 12_habil | 5220 | +0.001% | 50.1% | 1560 | +0.002% | 50.1% |
| 13_finde | 2088 | -0.005% | 48.8% | 624 | +0.006% | 51.4% |
| 13_habil | 5220 | -0.007% | 49.0% | 1560 | -0.018% | 48.5% |
| 14_finde | 2088 | +0.013% | 51.8% | 624 | +0.020% | 54.0% |
| 14_habil | 5220 | -0.005% | 49.5% | 1560 | +0.007% | 50.5% |
| 15_finde | 2088 | +0.015% | 52.9% | 624 | -0.002% | 49.2% |
| 15_habil | 5220 | +0.010% | 51.0% | 1560 | +0.001% | 50.1% |
| 16_finde | 2088 | -0.001% | 49.6% | 624 | -0.007% | 49.0% |
| 16_habil | 5220 | -0.005% | 49.3% | 1560 | -0.008% | 49.0% |
| 17_finde | 2088 | +0.000% | 49.9% | 624 | +0.014% | 52.2% |
| 17_habil | 5220 | +0.009% | 50.9% | 1560 | +0.018% | 52.5% |
| 18_finde | 2088 | +0.011% | 52.7% | 624 | -0.001% | 49.5% |
| 18_habil | 5220 | +0.006% | 50.7% | 1560 | -0.007% | 48.8% |
| 19_finde | 2088 | +0.000% | 50.0% | 624 | -0.002% | 49.8% |
| 19_habil | 5220 | +0.013% | 51.9% | 1560 | +0.006% | 51.3% |
| 20_finde | 2088 | +0.006% | 51.1% | 624 | +0.003% | 50.8% |
| 20_habil | 5220 | +0.009% | 51.1% | 1560 | +0.008% | 51.3% |
| 21_finde | 2088 | +0.014% | 52.3% | 624 | +0.003% | 50.2% |
| 21_habil | 5220 | +0.012% | 51.5% | 1560 | +0.017% | 52.4% |
| 22_finde | 2088 | -0.001% | 49.7% | 624 | +0.014% | 51.9% |
| 22_habil | 5220 | +0.006% | 51.0% | 1560 | -0.017% | 47.2% |
| 23_finde | 2088 | -0.002% | 49.6% | 624 | -0.012% | 48.1% |
| 23_habil | 5219 | +0.000% | 50.0% | 1559 | +0.007% | 51.2% |

### Lectura como insumo

- Ninguna celda se acerca al costo round-trip pre-registrado (0.07%): las
  medianas por vela viven en ±0.02% y los hit rates en 46-54%. La hora del
  día, sola, no es una señal — confirmado en ambas ventanas.
- La persistencia calibración→verificación es débil: de las celdas de BTC
  con hit ≥ 51.5% en calibración, solo `20_habil` y `21_habil` (~20-21 UTC)
  repiten en verificación. Es lo único con alguna consistencia y sigue muy
  por debajo de costos; sirve a lo sumo como contexto horario para una señal
  futura, no como disparador.

### Conclusión C2: **insumo entregado** (sin umbral de adopción, por diseño)

---

## Estudio C3 — reversión post-movimiento extremo (proxy de cascada)

**Límite pre-registrado (spec, verbatim):**

> **Límite pre-registrado (clave):** n esperado 30-60. Con n < 50 en total,
> el estudio SOLO puede concluir "descartar" o "extender datos" — nunca
> "adoptar".

### Tabla C3 (todas las celdas; solo BTC — ETH fuera de C3 por spec)

| Dirección | Horizonte | n cal | mediana cal | media cal | hit cal | n ver | mediana ver | media ver | hit ver |
|---|---|---|---|---|---|---|---|---|---|
| alcista | 1h | 0 | — | — | — | 0 | — | — | — |
| alcista | 4h | 0 | — | — | — | 0 | — | — | — |
| alcista | 8h | 0 | — | — | — | 0 | — | — | — |
| bajista | 1h | 1 | -0.049% | -0.049% | 0.0% | 0 | — | — | — |
| bajista | 4h | 1 | -0.141% | -0.141% | 0.0% | 0 | — | — | — |
| bajista | 8h | 1 | -0.235% | -0.235% | 0.0% | 0 | — | — | — |

n_total: calibración 1, verificación 0 → **total 1 ≪ 50**.

### Evaluación

- El detector es correcto (revisión independiente con recomputo exacto,
  Task 10): en abril-junio 2026 casi nunca coinciden |z| > 3 y flujo ≥ 0.6
  en la misma vela (111 velas pasan el z-score, 6 el flujo, 1 ambas). El "n
  esperado 30-60" de la spec era demasiado optimista para esta definición
  conjunta sobre klines de 15m.
- Con n = 1 no hay nada que evaluar contra umbrales. La regla pre-registrada
  deja exactamente dos salidas: "descartar" o "extender datos". Extender
  datos es viable (los dumps de klines futures cubren 2020→hoy), pero la
  frecuencia observada (~1 evento/trimestre) sugiere que aun con 6 años
  habría ~25 eventos: probablemente haya que revisar la definición del
  evento en un ciclo futuro pre-registrado, no estirar esta.

### Conclusión C3: **N INSUFICIENTE** (descartar o extender datos)

---

## Cierre: criterio de salida del ciclo

**Texto pre-registrado de la spec (verbatim):**

> - **Si C1 pasa su umbral** (o C3 termina en "extender y re-testear" con
>   señal fuerte): siguiente ciclo = brainstorming corto de diseño de señal
>   (disparador + gates) sobre la hipótesis ganadora, y de ahí al harness de
>   ablación de siempre. C2 aporta contexto, no dispara ciclos por sí solo.
> - **Si los tres fallan:** NO se prueban más combinaciones intradía. Se abre
>   la decisión del plan B ya documentado
>   (`docs/revisiones/insights-momentum-multidia-btc.md`: momentum multi-día,
>   con sus propios estudios M1-M4 pre-esbozados) o se congela la búsqueda de
>   señal conservando la infraestructura. Esa decisión es de Guille, con ambos
>   caminos por escrito.

**Aplicación:** C1 NO PASA, C2 es insumo (no dispara ciclos), C3 terminó en
N INSUFICIENTE sin señal fuerte. Estamos en la segunda rama: no se prueban
más combinaciones intradía, y queda abierta la decisión de Guille entre:

1. **Plan B:** momentum multi-día
   (`docs/revisiones/insights-momentum-multidia-btc.md`, estudios M1-M4), o
2. **Congelar** la búsqueda de señal conservando la infraestructura (bot
   limpio sin disparador, datos 2020→hoy, librería de estudios con candado,
   harness de ablación).

Este veredicto no decide entre las dos — eso es de Guille, por pre-registro.

## Nota de datos (hallazgo Task 6, para futuras ablaciones)

El cache de ticks histórico (`BTCUSDT_aggtrades_*`, 91 días) es de mercado
**SPOT**, mientras el bot opera **FUTUROS** (um). Los estudios de este ciclo
usaron exclusivamente datos de futuros (klines y funding), pero el replay
del backtest sigue alimentándose de ticks spot: cualquier ablación futura
debería descargar aggTrades de futuros (data.binance.vision los publica) y
re-poblar el cache antes de confiar en diferencias finas de ejecución.
