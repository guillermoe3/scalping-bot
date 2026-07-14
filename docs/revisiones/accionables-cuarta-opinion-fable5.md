# Accionables para el bot de scalping BTC/USDT — Cuarta opinión (Claude Fable 5)

Fecha: 2026-07-14
Insumos: informe de estado 2026-07-14 (plan original, cadena de auditorías,
ablación re-corrida post-fix del trail, autopsia con tasas base).

## 0. Alcance y base de evidencia — leer antes de implementar nada

**Qué es hecho verificado acá:** todo lo que cito de tu informe de estado
(números de la ablación 2026-07-14, tasas base de la autopsia, cronología de
cambios). Confío en esos números como los reportaste.

**Qué es inferencia mía:** (a) no tengo acceso al repo actual — el último
código que vi de este proyecto es el MVP de spot con reloj de 1m, y tu bot
hoy es otro sistema (15m, futures, maker post-only, ~300 tests). Cuando
nombro archivos (`signals.py`, `config.py`, `risk.py`) asumo que la
estructura modular se conserva; **verificá cada ubicación antes de editar**.
(b) Los priors sobre funding, sesión y cascadas son conocimiento general de
microestructura + literatura, no mediciones sobre tus datos. Por eso casi
todos los accionables de señal nueva son *estudios*, no código del bot.

**Regla de oro que respeto de tu método:** ninguna edición de señal entra a
producción sin tasa base positiva + criterio de adopción pre-registrado +
pasar por el harness de ablación. Los accionables están ordenados para que
eso sea posible.

---

## 1. Veredicto que fundamenta los accionables

La hipótesis squeeze-sobre-niveles está rechazada dos veces (como entrada
operada: PF ~0.30 en toda la matriz; como premisa física: |ret| forward
0.417% vs 0.573% incondicional — el squeeze predice calma). La estructura de
costos ya no es el problema (~0.17R). El único gate con información
demostrada es `trend_1h`. El gate `cvd` tal como está veta trades buenos
(PF 0.30→0.51 al quitarlo). Dos gates no vetan nada (`regime_known`,
`breakout_align`) y dos siguen inertes en backtest (`macro`,
`ob_imbalance`), o sea backtest y bot en vivo siguen siendo estrategias
parcialmente distintas.

Traducción a plan: **retirar la señal muerta, reconvertir lo que tu propia
evidencia dice que sirve para otra cosa, reparar el gate que resta, cerrar
la brecha backtest≠live, y gastar el próximo ciclo en 3 estudios de tasa
base baratos — no en recombinaciones.**

---

## 2. Grupo A — Retirar (la señal muerta y el código sin efecto)

### A1. Retirar el squeeze como disparador de entrada
- **Dónde (inferido):** `signals.py` (detección + resolución de dirección),
  `config.py` (umbrales de compresión), variantes A/B de N1.
- **Cambio:** sacar el squeeze del camino de decisión de entrada. No borrar
  el detector (ver B1). Las variantes A (fade) y B (break) quedan archivadas
  como corridas históricas en `backtest_runs/`, no como código vivo.
- **Evidencia (verificada, tu informe):** rechazo doble — operado y por tasa
  base, con medición limpia post-fix del trail y criterios pre-registrados
  que ninguna corrida cumplió.
- **Esfuerzo:** bajo. **Criterio de aceptación:** suite verde; el bot en
  paper no genera entradas (estado esperado: sin disparador activo hasta que
  un estudio del Grupo C apruebe uno nuevo).
- **Nota:** un bot sin señal que no opera es el estado *correcto* hoy. No
  llenar el vacío con un disparador improvisado para "que haga algo".

### A2. Remover del pipeline los gates que no vetan nada
- **Dónde (inferido):** `signals.py` / definición de gates del harness.
- **Cambio:** `regime_known` y `breakout_align` salen del AND de decisión
  (sus corridas de ablación son idénticas a base → costo de mantenimiento
  sin información). Conservar la infraestructura de contadores del harness;
  son los gates los que mueren, no el mecanismo.
- **Evidencia (verificada):** ablación 2026-07-14, corridas idénticas a base.
- **Matiz (inferencia):** "no vetó en 91 días de abr-jun" no es "nunca
  vetará" — si son baratos de mantener, la alternativa válida es dejarlos
  desactivados por flag en vez de borrarlos. Decisión tuya; lo importante es
  que no participen del AND por default.
- **Esfuerzo:** bajo. **Criterio de aceptación:** corrida base re-ejecutada
  sin esos gates reproduce exactamente los mismos trades.

---

## 3. Grupo B — Reconvertir y reparar (donde tu evidencia señala valor)

### B1. Reconvertir el detector de squeeze en filtro de "no operar"
- **Dónde (inferido):** el detector existente de compresión.
- **Cambio:** invertir el rol — de gatillo a veto. Tu medición dice que tras
  un squeeze el mercado se mueve MENOS que el promedio en todos los
  horizontes: es un detector de calma. Cualquier estrategia futura de
  momentum/continuación debería *abstenerse* cuando hay compresión activa.
- **Evidencia:** verificada como tasa base (calma → más calma); **el valor
  como veto para una señal futura es inferencia** hasta que la señal futura
  exista y el harness lo mida.
- **Esfuerzo:** bajo (el código ya existe; cambia el signo de uso).
- **Criterio de aceptación:** entra al harness como gate nombrado
  (`calm_filter`) con contador de vetos; se adopta solo si en la ablación de
  la señal nueva mejora el PF.

### B2. Rediseñar el gate de CVD (hoy resta)
- **Dónde (inferido):** `signals.py` / módulo de order flow, ventana y
  umbral de divergencia en `config.py`.
- **Cambio propuesto, en dos pasos:**
  1. *Inmediato:* desactivar el gate `cvd` por default (tu ablación: PF
     0.30→0.51 al quitarlo — es el único cambio de gate que mejoró algo).
  2. *Estudio antes de reintroducirlo:* re-expresar la variable como **ratio
     taker buy/sell agregado por ventana, normalizado por sesión** (z-score
     contra la distribución de esa hora del día), en vez de divergencia
     acumulada precio-vs-CVD. Hipótesis a testear en tasa base: el extremo
     del ratio (no la divergencia) contiene información. La divergencia
     acumulada arrastra historia vieja y depende del punto de anclaje; el
     ratio por ventana no.
- **Evidencia:** el paso 1 es verificado (ablación); el rediseño del paso 2
  es inferencia con prior medio.
- **Esfuerzo:** paso 1 trivial; paso 2 = script de estudio (~1 día) porque
  los datos tick que necesitás ya están en el cache de 91 días.
- **Criterio de aceptación paso 2 (pre-registrar):** el ratio extremo
  (|z|>2) debe mostrar retorno forward firmado con mediana y media del mismo
  signo, neto de 0.17R, en split temporal 60/40 de los 91 días. Si no, el
  CVD muere del todo y se documenta.

### B3. Cerrar la brecha backtest ≠ live (gates inertes)
- **Dónde (inferido):** motor de backtest + `macro` y `ob_imbalance`.
- **Cambio:** decisión binaria por gate, y cualquiera de las dos ramas es
  válida — lo inválido es el estado actual:
  - `ob_imbalance`: **retirarlo del bot en vivo.** No es historizable con tu
    infraestructura (lo declara tu informe), o sea nunca vas a poder
    validarlo en backtest → viola tu propio principio de que backtest y live
    sean la misma estrategia. Inferencia adicional de microestructura: 5
    snapshots promediados del book de BTC siguen siendo ruido + spoofing;
    el prior de que aporte es bajo.
  - `macro` (correlación BTC-SPY vía yfinance): elegir entre (a) retirarlo,
    o (b) hacerlo backtesteable descargando SPY diario/horario histórico y
    modelándolo en el motor. Si eligen (b), pasa por ablación como cualquier
    gate. Mi recomendación: (a) por ahora — es dependencia externa frágil
    (yfinance) para una señal de valor no medido.
- **Evidencia:** la brecha es verificada (tu informe la lista desde la
  cadena de auditorías); las recomendaciones de retiro son inferencia.
- **Esfuerzo:** bajo (retiro) / medio (modelado de macro).
- **Criterio de aceptación:** cero gates en producción que el backtest no
  pueda evaluar. Ese invariante debería ser un test.

### B4. Kill switch: incluir PnL no realizado en el drawdown diario
- **Dónde (inferido):** `risk.py` `check_kill_switch` o equivalente.
- **Cambio:** el drawdown diario debería computarse sobre equity total
  (balance + unrealized de la posición abierta), no solo balance realizado.
  Con una sola posición y stop de 1.5×ATR el error acotado es chico, pero es
  la clase de bug que se agranda si algún día hay más de una posición.
- **Evidencia:** esto lo señalé en la auditoría de trazabilidad del MVP
  original; **no sé si ya lo corrigieron en el sistema actual** — verificar
  antes de tocar. Si ya está, descartar este ítem.
- **Esfuerzo:** bajo. **Criterio:** test failing-first con posición abierta
  en pérdida que debe disparar el kill switch antes del cierre del trade.

---

## 4. Grupo C — Los tres estudios del próximo ciclo (antes que cualquier señal)

Formato común pre-registrado: mediana **y** media del mismo signo, magnitud
neta > 0 contra fee round-trip maker de 0.17R, split temporal
calibración/verificación, n mínimo declarado antes de correr. Corrección por
multiplicidad: lo que pase en calibración solo cuenta si se sostiene en
verificación intacta. Todos corren día a día en la VM (agregados
incrementales, nunca el histórico entero en RAM).

### C1. Funding rate extremo como condicionante direccional — prioridad 1
- **Datos nuevos:** histórico de funding de Binance (gratuito; verificar
  granularidad disponible en Vision/API antes de diseñar — ver sección 6).
  Extender klines 15m a 2+ años: este estudio NO necesita ticks.
- **Evento:** funding de 8h en percentil >90 o <10 de ventana rolling 30d
  (percentil, no valor absoluto — el nivel "normal" deriva).
- **Forward:** retorno firmado contra la tesis (funding alto → forward
  negativo) a 8h / 24h / 72h.
- **Métrica:** mediana, media, hit rate direccional.
- **n mínimo:** 150 eventos por cola (con 2 años debería sobrar).
- **Umbral de adopción:** mediana firmada > 2× fee neto Y media del mismo
  signo Y sostenido en verificación.
- **Por qué primero (inferencia):** es variable de posicionamiento (quién
  está apalancado y de qué lado) — información que el precio solo no
  contiene, con mecanismo causal (longs pagando caro = combustible de
  squeeze bajista real). Es la única candidata de tu lista con mecanismo
  estructural y datos gratis.

### C2. Estacionalidad de sesión/hora — prioridad 2 (el más barato)
- **Datos:** los que ya tenés (klines 15m; extender a 2 años si C1 ya bajó
  el histórico).
- **Evento:** cada vela de 15m, bucketed por hora UTC; separar días con/sin
  release macro US (CPI/FOMC/NFP).
- **Métrica:** drift medio y mediano, |retorno|, volumen por bucket.
- **Uso esperado (inferencia):** casi seguro NO da señal direccional
  operable sola. Su valor: (a) gate de contexto para C1/C3 (¿el efecto es
  más fuerte en cierta sesión?), (b) filtro de "no operar", (c) chequeo
  retroactivo: ¿tus 300 squeezes se distribuían igual por sesión, o
  promediaste dos fenómenos distintos?
- **Esfuerzo:** una tarde. **Umbral:** no aplica adopción directa; es
  insumo. Registrar igual el diseño antes de mirar los datos.

### C3. Reversión post-movimiento extremo (proxy de cascada) — prioridad 3
- **Datos:** los 91 días tick que ya tenés (este sí los necesita).
- **Evento:** retorno 15m con |z| > 3 contra vol realizada de 24h previas +
  ratio de volumen taker unidireccional > umbral (proxy de cascada de
  liquidaciones sin feed de liquidaciones).
- **Forward:** retorno firmado contra el movimiento a 1h / 4h / 8h.
- **n esperado:** 30-60 eventos — **pre-registrar que con n<50 el estudio
  solo puede concluir "descartar" o "extender datos", nunca "adoptar".**
- **Por qué (inferencia):** las cascadas son el squeeze literal del mercado
  de futuros; la sobre-extensión mecánica con reversión parcial tiene
  mecanismo (stops forzados ≠ información). Coherencia con tus datos: si los
  rangos persisten (B1), el fade de extremos es la hipótesis que tu
  evidencia señala como siguiente candidata natural — lo cual no la hace
  rentable, la hace testeable.

---

## 5. Grupo D — Harness e infraestructura

### D1. Split temporal y multiplicidad como primitivas del harness
- **Cambio:** que el harness soporte nativamente (a) partición
  calibración/verificación por fecha con la verificación bloqueada hasta el
  final, y (b) registro del número de hipótesis/horizontes mirados por
  ciclo, para que el umbral de "pasó" lo tenga en cuenta.
- **Justificación (inferencia):** con 3 estudios × 3 horizontes × 2 métricas
  vas a mirar ~18 números; algo va a lucir bien por azar. El pre-registro ya
  lo tenés; falta la mecánica que lo haga difícil de violar por accidente.
- **Esfuerzo:** medio.

### D2. Descargador de funding + extensión de klines a 2+ años
- **Cambio:** extender el downloader de Binance Vision existente a funding
  rate y a klines 15m multi-año, cache compacto por día como el actual.
- **Esfuerzo:** bajo-medio (reusa lo construido en P0-6).
- **Criterio:** paridad de conteos contra la API REST en una muestra de días
  (mismo control que hicieron al migrar el cache viejo).

### D3. Paper trading en vivo para validar el modelo de fills maker
- **Estado:** ya lo tenés como pendiente no bloqueante; lo subo a
  "recomendado este ciclo" con una precisión: no hace falta señal rentable
  para validar el *modelo de ejecución*. Podés correr paper con un
  disparador sintético (ej: entrada aleatoria 1×/día con los mismos limit
  post-only + timeout 300s) y medir fill rate real vs el modelo conservador
  del backtest. Si el modelo de fills está mal, TODA medición futura hereda
  el error — mejor saberlo antes del próximo ciclo de señal.
- **Evidencia:** la necesidad es verificada (tu propio pendiente); el diseño
  con disparador sintético es inferencia/propuesta.
- **Esfuerzo:** bajo si el camino live GTX ya existe.

### D4. Invariante backtest=live como test permanente
- **Cambio:** test automático que falle si existe un gate habilitado en
  producción que el motor de backtest no evalúa (cierra B3 para siempre).
- **Esfuerzo:** bajo.

---

## 6. Grupo E — No tocar (igual de importante)

- **La capa de riesgo completa** (0.5%/trade, stop 1.5×ATR, TP1 2R,
  breakeven, breathing stop, trailing estructural post-fix, salidas por
  tiempo/momentum, kill switch, reconciliación): tu informe la declara la
  parte mejor fundada y la ablación no la implica en las pérdidas (post-fix,
  las pérdidas son de señal, no de ejecución). Única excepción: B4 si
  corresponde.
- **La arquitectura disparador + gates binarios en AND con ablación:** no
  migrar a score continuo ni a régimen multi-estado. Con 25-80
  trades/trimestre, más grados de libertad = más overfitting y menos
  legibilidad. El AND con contadores de veto es tu ventaja metodológica.
- **Nada de clasificadores entrenados (ML) con esta muestra.** Regla de
  ~10-20 eventos por parámetro → presupuesto para 2-4 parámetros, que ya los
  usás. Un modelo de 6 features sobre 50 trades da backtest hermoso y
  forward aleatorio. Es aritmética, no conservadurismo.
- **No optimizar parámetros de la señal muerta** (lo pediste vos y lo
  refrendo): ningún sweep adicional de umbrales de squeeze.

---

## 7. Información que me falta (y por qué importa)

1. **Repo actual de `signals.py`, `config.py`, `risk.py` y el harness.** Mis
   ubicaciones de archivo son inferidas del MVP viejo; sin ver el código
   actual no puedo dar diffs concretos ni detectar si B4 ya está corregido.
2. **Modelo de fills maker exacto del backtest:** ¿el límite llena solo si
   el precio *atraviesa* (trade-through) o también al toque? ¿Se modela
   posición en cola? Cambia cuán conservador es D3 y cuánto sesgo tiene toda
   la matriz de ablación.
3. **Granularidad y profundidad del histórico de funding y OI disponible**
   en Binance Vision / API para BTCUSDT perp: necesito saber si C1 puede
   hacerse a 2+ años con funding por período de 8h (casi seguro sí) y si OI
   histórico existe con granularidad útil (dudoso — de memoria la API lo
   limita; verificar antes de prometer un estudio de OI).
4. **Definición exacta del "abort por colapso de momentum":** qué mide y con
   qué umbral. Si ya es un ROC/aceleración, puede reusarse como feature en
   C2/C3 sin escribir nada nuevo.
5. **Specs de la VM** (RAM/cores): para dimensionar C1 a 2 años día a día y
   decidir si el estudio corre en horas o en días.
6. **¿Hay flexibilidad de reloj?** Los tres estudios miran horizontes de
   1h-72h; si algo pasa, el bot resultante puede terminar operando más cerca
   de 1h-4h que de 15m. Confirmar que eso es aceptable para el proyecto (el
   fee drag mejora aún más; la frecuencia de trades baja).
7. **¿Un solo activo es restricción dura?** Si ETH-perp entra al universo,
   C1 y C3 duplican muestra casi gratis (mismo downloader, mismo harness).
   No lo propuse como accionable porque tu informe fija BTC/USDT, pero es la
   palanca de muestra más barata que existe.

---

## 8. Orden de ejecución sugerido

| # | Ítem | Depende de | Esfuerzo |
|---|------|-----------|----------|
| 1 | A1 + A2 (retirar señal muerta y gates sin efecto) | — | Bajo |
| 2 | B2 paso 1 (desactivar gate cvd) + B3 (retirar/decidir gates inertes) + D4 (invariante) | — | Bajo |
| 3 | D2 (funding + klines 2 años) | Respuesta a faltante #3 | Bajo-medio |
| 4 | C2 (sesión — el más barato, corre con datos actuales) | — | Una tarde |
| 5 | C1 (funding) | D2, D1 | Medio |
| 6 | C3 (cascadas) + B2 paso 2 (ratio taker) | D1 | Medio |
| 7 | D3 (paper con disparador sintético) | Camino GTX live | Bajo |
| 8 | B1 (calm_filter) y B4 | Solo si hay señal candidata / si el bug existe | Bajo |

Si los tres estudios de C fallan sus umbrales pre-registrados, la conclusión
del ciclo no es "probar más combinaciones": es mover el proyecto a momentum
multi-día (klines gratis multi-año, fee drag irrelevante, mejor soporte en
literatura) o congelar la búsqueda de señal y conservar la infraestructura —
que hoy es el activo real del proyecto.

---

*Disclaimer: esto es estrategia de investigación sobre tu sistema, no
asesoramiento financiero. Los priors marcados como inferencia deben morir o
sobrevivir en tus datos, no en mi opinión.*
