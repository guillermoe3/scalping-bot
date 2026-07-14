# Momentum multi-día/semanal en BTC: soporte académico y espacio de diseño

Fecha: 2026-07-14
Propósito: documento de insights para repensar en el futuro el pivote de
estrategia desde scalping intradía hacia momentum multi-día/semanal
(time-series momentum, TSMOM). Diseñado como **insumo para una sesión de
brainstorming** (Claude Code u otra): concentra la evidencia académica al
máximo detalle accionable, el espacio de diseño de señales, los costos a
este horizonte, el diseño de estudios de tasa base compatible con el harness
existente, y las decisiones abiertas que el brainstorming debe resolver.

Convención de este documento: **[V]** = verificado contra la fuente citada
(papers/URLs en sección 10). **[I]** = inferencia o conocimiento general mío
sin verificación puntual hoy. **[D]** = decisión de diseño abierta para el
brainstorming.

---

## 1. Por qué este espacio encaja con las condiciones del proyecto

El argumento no es "el momentum es bueno"; es que **es el único espacio de
señal donde las restricciones del proyecto dejan de ser desventajas**:

| Restricción del proyecto | En scalping 15m | En momentum multi-día |
|---|---|---|
| Sin ventaja de latencia | Fatal: competís contra MM/HFT | Irrelevante: la señal vive días/semanas |
| Datos públicos gratis | Todos ven lo mismo que vos | Ídem, pero el edge (si existe) viene de límites de arbitraje, no de información privada |
| Capital chico (cientos-miles USDT) | Márgenes finos vs fees | Ventaja: capacidad ilimitada a tu escala, cero impacto de mercado |
| Fee drag | Fue tu problema #1 (1.31R→0.17R) | Despreciable: pocas operaciones/mes |
| Un solo activo (BTC) | Limita muestra de eventos | TSMOM es *por definición* un solo activo (vs cross-sectional que necesita muchos) |
| VM chica | OK | Sobra: klines diarias, cómputo trivial |
| Risk layer ATR + harness + pre-registro | Construido | 100% reutilizable |

**[I]** El costo del cambio: frecuencia bajísima de señales (el problema de
muestra se agrava, ver sección 7), drawdowns largos, y exposición a
"momentum crashes" (sección 4.7). No es un espacio mejor gratis; es un
espacio donde el edge residual documentado y tus condiciones son
compatibles.

---

## 2. Marco teórico: qué es exactamente lo que la literatura respalda

### 2.1 Dos familias que no hay que mezclar

- **Time-series momentum (TSMOM):** el retorno pasado del *propio activo*
  predice su retorno futuro. Señal: `sign(ret[t-k, t])`. Es lo aplicable a
  un bot de un solo activo. **[V]** Formalizado por Moskowitz, Ooi &
  Pedersen (2012) en 58 futuros: persistencia del retorno de 1 a 12 meses,
  con reversión parcial después. **[I]** Hurst, Ooi & Pedersen extendieron
  la evidencia a más de un siglo de datos multi-activo ("A Century of
  Evidence on Trend-Following Investing") — el trend-following es
  probablemente la anomalía más persistente y replicada de las finanzas
  empíricas.
- **Cross-sectional momentum:** comprar los ganadores relativos y vender
  los perdedores relativos *dentro de un universo de activos*. **[V]** Liu,
  Tsyvinski & Wu (2022, Journal of Finance) lo documentan en crypto con
  1.827 monedas (cap > 1M USD, 2014–jul 2020): un long/short de momentum
  con formación de 1-4 semanas rinde ~3% semanal en exceso, y el momentum es
  uno de los 3 factores (mercado, tamaño, momentum) que explican la sección
  cruzada de retornos cripto. Dobrynskaya (2023) llega a conclusiones
  similares con las 2.000 monedas más grandes.
  **Relevancia para vos: solo si el universo se amplía** (BTC+ETH+top-N).
  Con un activo, esta rama queda como opción futura, no como plan.

### 2.2 Por qué existiría el efecto (mecanismos, no magia)

**[V]** Detzel, Liu, Strauss, Zhou & Zhu (2021) proponen el mecanismo más
convincente para BTC específicamente: en activos con fundamentals
"difíciles de valuar" (sin cash flows), los inversores racionales *aprenden*
del precio mismo, y ese aprendizaje genera endógenamente predictibilidad vía
análisis técnico — el mismo patrón aparece en small-caps, empresas jóvenes,
acciones con poca cobertura de analistas y el NASDAQ de la era dotcom.
**[V]** El BIS (WP 1087, "Crypto carry") cita evidencia (Kogan et al.) de
que los traders retail en cripto son trend-followers, y que la atención del
inversor se correlaciona con la demanda de exposición apalancada.
**[V]** Liu & Tsyvinski (2021, Review of Financial Studies) documentan que
proxies de atención (búsquedas de Google) predicen retornos a 1-2 semanas:
+1.84% y +2.30% semanal por desvío estándar de búsquedas.
**[I]** Síntesis de mecanismos: (a) subreacción inicial + herding posterior
de retail, (b) aprendizaje racional sin ancla fundamental, (c) capital
institucional lento (flujos de ETF que tardan semanas en ajustarse). Ninguno
de estos mecanismos requiere velocidad para explotarse — por eso el espacio
es compatible con retail.

### 2.3 Por qué no estaría totalmente arbitrado — y la contra honesta

**[I]** Los límites clásicos: el trend-following exige tolerar drawdowns
largos y rachas de señales falsas (career risk institucional), y en crypto
el costo de shortear (funding, riesgo de squeeze) limita el arbitraje del
lado corto. **[I]** La contra: la institucionalización post-ETF (enero
2024) puede estar comprimiendo exactamente este edge — más capital
sistemático persiguiendo las mismas señales de tendencia. La sección 5 trata
esto como el riesgo #1 del pivote.

---

## 3. La evidencia, paper por paper (con lo implementable de cada uno)

### 3.1 Moskowitz, Ooi & Pedersen (2012) — "Time Series Momentum" (JFE)

- **[V/I]** Qué midieron (V el resultado central, I los detalles finos de
  memoria): 58 futuros líquidos (equity, FX, commodities, bonos),
  1965-2009. El retorno en exceso de los últimos 12 meses predice el
  retorno del mes siguiente; la persistencia dura 1-12 meses y revierte
  parcialmente a 2-5 años.
- **Qué extraer para implementar:** (a) la construcción canónica de la
  posición: `posición = sign(ret 12m) × (σ_target / σ_ex-ante)` — el
  **volatility scaling** es parte de la definición, no un adorno; (b) el
  resultado sobrevive en cada clase de activo por separado → el prior de que
  aplique a BTC no es ad-hoc; (c) la reversión a largo plazo advierte contra
  lookbacks demasiado largos.
- **Caveat:** pre-crypto, activos con estructura institucional distinta.

### 3.2 Liu & Tsyvinski (2021, RFS; WP NBER 24877, 2018) — "Risks and Returns of Cryptocurrency"

- **[V]** Qué midieron: BTC (2011-2018 en el WP), Ripple y Ethereum.
  Momentum de series de tiempo significativo a frecuencia **diaria y
  semanal**: un aumento de 1 desvío estándar en el retorno diario de BTC
  predice +0.33% en el retorno del día siguiente. Agrupando retornos
  semanales por quintiles, los quintiles altos superan a los bajos en
  horizontes de 1 a 4 semanas: a 1 semana, quintil alto 11.22%/semana
  (Sharpe 0.45) vs quintil bajo 2.60%/semana (Sharpe 0.19). En Ethereum el
  efecto es más débil que en BTC y Ripple.
- **Qué extraer:** (a) el horizonte dulce documentado para BTC es **1-4
  semanas de formación** — eso acota tu grilla de lookbacks; (b) la
  predictibilidad existe también a 1 día (relevante para frecuencia de
  rebalanceo); (c) la atención (Google Trends) como feature complementaria
  con predictibilidad a 1-2 semanas.
- **Caveats críticos [I]:** la muestra 2011-2018 está dominada por el
  régimen retail/bull temprano; los niveles absolutos (11%/semana) son
  irrepetibles — lo trasladable es el *signo y la estructura* del efecto, no
  la magnitud. Todo número de este paper debe re-estimarse en 2017-2026.

### 3.3 Detzel, Liu, Strauss, Zhou & Zhu (2021, Financial Management) — el paper más implementable

- **[V]** Qué midieron: ratios de precio a sus medias móviles de **5 a 100
  días** predicen retornos **diarios** de BTC, in-sample y **out-of-sample**
  (la distinción importa: usan métodos OOS estilo Goyal-Welch para no
  sobrestimar). Estrategias basadas en esos ratios generan alfa
  económicamente significativo y mejoras de Sharpe vs buy-and-hold, y el
  mecanismo de la mejora es **reducir la duración y severidad de los
  drawdowns** (no ganarle al bull). Mismo patrón en Ripple y en NASDAQ
  dotcom.
- **Qué extraer:** (a) la familia de señal concreta: `P_t / MA_n(P)` con
  n ∈ [5, 100] días — es la especificación con mejor evidencia OOS para BTC;
  (b) rebalanceo diario al cierre; (c) la métrica de éxito correcta para tu
  estudio no es "retorno > buy-and-hold" sino "Sharpe y drawdown mejores que
  buy-and-hold" — el trend-following en BTC es ante todo un *reductor de
  colas izquierdas*; (d) el modelo teórico justifica por qué BTC en
  particular (fundamentals difíciles de valuar).
- **Caveat [I]:** muestra hasta ~2018-2019; la era institucional no está.

### 3.4 Hudson & Urquhart (2021, Annals of Operations Research) — "Technical trading and cryptocurrencies"

- **[V]** Qué midieron: ~15.000 reglas técnicas de las 5 clases principales
  (filter, MA, support/resistance, channel breakouts, oscilador) sobre dos
  mercados de Bitcoin y tres cryptos más. Encuentran predictibilidad y
  rentabilidad significativa en cada clase y cada crypto; los costos de
  transacción de breakeven son sustancialmente mayores que los típicos del
  mercado; y — lo más valioso metodológicamente — aplican procedimientos de
  **hipótesis múltiples** (control de data-snooping) y los resultados
  sobreviven.
- **Qué extraer:** (a) la existencia de predictibilidad técnica en BTC no
  depende de una regla mágica — es un fenómeno de familia amplia, lo cual
  reduce el riesgo de que tu grilla particular sea suerte; (b) el estándar
  metodológico a imitar: si probás una grilla de reglas, el control por
  multiplicidad no es opcional (White's Reality Check / SPA test o, mínimo,
  tu split temporal estricto); (c) el breakeven de costos alto confirma que
  a este horizonte tu 0.17R maker es ruido.

### 3.5 Liu, Tsyvinski & Wu (2022, Journal of Finance) — "Common Risk Factors in Cryptocurrency"

- **[V]** Ya resumido en 2.1: 3 factores (mercado, tamaño, momentum),
  formación 1-4 semanas, ~3% semanal el long/short de momentum
  (2014-jul 2020, 1.827 monedas).
- **Qué extraer:** el plano de expansión futura. Si algún día el universo
  pasa de 1 a N activos, la evidencia cross-sectional es más fuerte y
  diversificada que la de un solo activo. Para hoy: confirma que el
  momentum es *el* factor de la clase de activo, no una curiosidad de BTC.

### 3.6 "Cryptocurrency momentum has (not) its moments" (2025, Financial Markets and Portfolio Management)

- **[V]** Qué midieron: comportamiento de colas de estrategias de momentum
  cripto. Hallazgos: el momentum cripto sufre **crashes severos** (una sola
  moneda puede volver insignificante el retorno del portfolio); la **gestión
  por volatilidad** (volatility management, en línea con Moreira & Muir para
  equities) mitiga los crashes; y el momentum aparece asociado a **large
  caps** — buena noticia para un bot de BTC.
- **Qué extraer:** (a) el overlay de vol targeting no es opcional en crypto
  momentum: es el seguro contra el modo de falla dominante; (b) que el
  efecto viva en large caps valida BTC como el activo correcto para TSMOM.

### 3.7 Contexto teórico del riesgo: momentum crashes y vol management

- **[I]** Daniel & Moskowitz (2016, "Momentum Crashes", JFE): en equities,
  el momentum colapsa en rebotes tras pánicos (el lado corto explota). Para
  TSMOM long/flat/short en BTC, el análogo es el latigazo post-capitulación:
  la señal queda short/flat justo cuando el mercado rebota 30% en semanas.
- **[I]** Moreira & Muir (2017, "Volatility-Managed Portfolios", JF):
  escalar la exposición por la inversa de la varianza realizada reciente
  aumenta el Sharpe en la mayoría de los factores. Combinado con 3.6, define
  el overlay estándar: `exposición ∝ σ_target / σ_realizada(t-1)` con tope.

---

## 4. La advertencia de régimen (el riesgo #1 de este pivote)

Toda la evidencia núcleo (3.2, 3.3, 3.4, 3.5) usa muestras que terminan
entre 2018 y mediados de 2020. Desde entonces el mercado cambió de
estructura, y hay señales de que el cambio importa:

- **[V]** ETFs spot de BTC aprobados en enero 2024; la correlación
  BTC-Nasdaq llegó a ~0.87 en 2024 (vs ~-0.10 pre-2021), reflejando
  integración institucional.
- **[V]** El rally post-halving 2024 fue mucho menor que en ciclos previos,
  con volatilidad comprimida atribuida a adopción institucional; BTC tocó su
  ATH de $126,198 el 6 de octubre de 2025 y para marzo 2026 caía ~46% desde
  ahí.
- **[V]** Cobertura de mercado de junio 2026 describe a BTC "perdiendo el
  momentum trade", con la correlación histórica con equities rota en el
  período reciente.
- **[I]** Implicancia directa para tu método: **el split temporal no es un
  refinamiento, es la pregunta central del estudio.** La hipótesis a testear
  no es "¿hubo momentum en BTC?" (respuesta conocida: sí, 2013-2020) sino
  "¿sobrevive el momentum en el régimen institucional 2024-2026?". El
  diseño de la sección 7 pone la ventana 2024-2026 como verificación
  intocable por esa razón. Si el efecto no sobrevive ahí, la conclusión
  honesta es que llegaste tarde a esta anomalía también — y eso el estudio
  lo dice en horas de cómputo, no en meses de paper trading.

Punto a favor que balancea: **[V]** la caída del 46% desde el ATH de octubre
2025 es exactamente el tipo de movimiento sostenido multi-mes donde el
trend-following gana su prima histórica (reduciendo el drawdown vs
buy-and-hold, per Detzel et al.). El período 2024-2026 contiene al menos un
ciclo completo de subida y bajada — es una ventana de verificación exigente
pero informativa.

---

## 5. Espacio de diseño de señales (el menú para el brainstorming)

Familia priorizada por soporte académico:

### S1 — Price-to-MA ratio (Detzel et al.) — prior más alto
`señal_n(t) = P(t) / MA_n(P, t)`, n ∈ {5, 10, 20, 50, 100} días.
Long si > 1, flat (o short) si < 1. Variante continua: usar el ratio como
score con banda muerta alrededor de 1 (histéresis anti-churn). **[D]**
long/flat vs long/short.

### S2 — TSMOM clásico (MOP 2012 adaptado a los horizontes de Liu-Tsyvinski)
`señal_k(t) = sign(ret[t-k, t])`, k ∈ {7, 14, 28, 56, 90} días
(la evidencia cripto concentra el efecto en 1-4 semanas; 90 como control).

### S3 — Combinación multi-horizonte
Promedio (o voto) de S1/S2 en varios n/k, estilo trend-following
institucional **[I]**. Reduce la dependencia de un lookback puntual —
importante porque tu muestra no soporta optimizar n fino.

### S4 — Overlay de vol targeting (obligatorio por 3.6/3.7)
`exposición(t) = min(cap, σ_target / σ_realizada_d(t-1)) × señal(t)`
con σ realizada de 20-30 días y cap de exposición (ej. 1×). **[D]** σ_target
(15-40% anualizado es el rango típico de la literatura **[I]**).

### S5 — Features complementarias de segundo orden (no para v1)
Atención/Google Trends (predictibilidad 1-2 semanas per Liu-Tsyvinski
**[V]**), funding como condicionante (conecta con el estudio C1 ya
planificado), y el detector de calma reconvertido (B1 del documento de
accionables) como posible filtro. **[D]** cuáles entran al harness y cuándo.

### Reglas de ejecución a este horizonte
- Evaluación 1×/día al cierre UTC de la vela diaria. **[D]** ¿cierre 00:00
  UTC o ventana propia?
- Entrada/salida maker con timeout como ya tenés; a este horizonte, si el
  limit no llena, cruzar como taker cuesta 0.05% sobre un trade que apunta a
  varios % — irrelevante. Simplifica el modelo de fills.
- Histéresis: no cambiar de estado salvo que la señal cruce la banda muerta
  N días seguidos, o banda en precio (ej. ±1% alrededor de la MA). Reduce el
  churn en mercados laterales, que es donde el trend-following sangra.

### La decisión estructural del instrumento **[D — importante]**
Mantener un long por semanas en **perp** paga funding cuando el funding es
positivo (**[V]** la media histórica de la prima de funding fue ~8% anual
con baja vol en 2020-2025, aunque comprimiéndose). Opciones: (a) pata long
en **spot** y perp solo para short/flat (elimina el drag de funding en el
estado más frecuente), (b) todo en perp aceptando el funding como costo
modelado, (c) long/flat puro en spot (sin short). La elección cambia el
backtest: el funding histórico debe entrar al modelo de costos si se elige
(b). Nota: esto reabre parcialmente la pregunta spot vs futures del origen
del proyecto, con la respuesta probablemente invertida a este horizonte.

---

## 6. Costos y microestructura a este horizonte

- **[I]** Turnover esperado de S1/S2 con histéresis: entre 1 y 6 cambios de
  estado por mes según el lookback (los cortos giran más). Con 0.02% maker
  (o incluso 0.05% taker) por lado, el fee drag anual queda en pocas décimas
  de %, contra movimientos objetivo de decenas de %: el problema que mató al
  scalping no existe acá.
- **[I]** El costo dominante pasa a ser: (a) funding si se usa perp para la
  pata long (ver S5-instrumento), (b) el whipsaw en rangos (costo de la
  estrategia, no de ejecución — se mide en el backtest, no se "arregla"),
  (c) slippage despreciable a tu tamaño.
- **[V]** Hudson & Urquhart: los breakeven de costos de las reglas técnicas
  en crypto son sustancialmente mayores que los costos reales típicos —
  a este horizonte los fees no son la variable de decisión.

---

## 7. Diseño de estudios de tasa base (pre-registro, formato del harness)

Datos: klines **diarias** BTC/USDT de Binance (Vision), 2017-08 → hoy
(~8.5 años, ~3.100 días). **[D]** extender pre-2017 con otras fuentes
(Bitstamp/Coinbase) suma ciclos pero mezcla venues — decidir en el
brainstorming; mi recomendación **[I]**: v1 solo Binance por consistencia, y
un chequeo de robustez posterior con la serie larga.

**Advertencia estadística central [I]:** con horizontes forward de 7-30
días, los retornos se **superponen** → los errores están autocorrelacionados
→ los t-stats ingenuos mienten. Usar errores Newey-West (lag ≥ horizonte) o
submuestreo sin superposición. Y aunque haya ~3.100 días, BTC tiene ~4
ciclos macro independientes: el n efectivo para "¿funciona en distintos
regímenes?" es 4, no 3.100. Esto obliga a humildad en los claims.

### M1 — Tasa base TSMOM (sin operar, el análogo de tu autopsia)
- **Evento:** cada día t, feature = `sign(ret[t-k, t])` para k ∈ {7, 14,
  28, 56, 90}.
- **Forward:** retorno firmado por la señal a 1, 7, 14 y 28 días.
- **Métricas:** mediana Y media firmadas, hit rate, y la comparación clave
  de Detzel: Sharpe y max drawdown de la serie "señalada" vs buy-and-hold.
- **Split:** calibración 2017-08→2023-12; **verificación 2024-01→hoy
  (intocable)** — por la advertencia de régimen de la sección 4.
- **Multiplicidad:** 5 lookbacks × 4 horizontes = 20 celdas; pre-registrar
  que solo cuenta lo que pasa en calibración Y sostiene signo y magnitud en
  verificación. **[I]** Ideal: reportar también el deflated Sharpe ratio
  (Bailey & López de Prado) o como mínimo el número de celdas miradas.
- **Umbral de adopción propuesto (a refinar en brainstorming):** en la
  ventana de verificación, mediana y media del mismo signo, Sharpe de la
  estrategia > Sharpe de buy-and-hold, y max drawdown < al de buy-and-hold.
  n mínimo: la verificación completa (~2.5 años, sin cherry-picking de
  subventanas).

### M2 — Réplica de Detzel en tus datos
- **Evento:** quintiles de `P/MA_n` para n ∈ {10, 20, 50, 100}.
- **Forward y métricas:** como M1; el contraste es quintil alto vs bajo.
- **Objetivo:** verificar que la especificación con mejor evidencia OOS de
  la literatura sobrevive 2024-2026. Si M1 y M2 discrepan, la discrepancia
  es información (sensibilidad a especificación = fragilidad).

### M3 — Overlay de vol targeting (condicional a que M1 o M2 pasen)
- **Test:** la versión vol-managed de la mejor señal vs la versión cruda.
- **Métrica:** Sharpe, drawdown, y colas (peor mes, peor trimestre) — el
  overlay se adopta si mejora colas sin destruir media, per 3.6.

### M4 — Costo de instrumento (si se considera perp para la pata long)
- Con el funding histórico (ya planificado bajar para C1): restar el
  funding acumulado a la serie long del backtest y comparar contra la
  alternativa spot. Decide la cuestión de instrumento con números, no con
  opinión.

Presupuesto de cómputo: klines diarias — todo esto corre en minutos en la
VM, día a día ni hace falta.

---

## 8. Cómo conviven el bot actual y este pivote

- El harness de ablación se reutiliza: la señal momentum se expresa como
  disparador (cambio de estado de S1/S2) + gates (vol regime, calm_filter,
  eventualmente funding). El invariante backtest=live (D4 del documento de
  accionables) aplica igual.
- La capa de riesgo necesita **[D]** una decisión: el stop 1.5×ATR y el
  time-exit de 15 minutos son de scalping; en momentum diario el "stop"
  natural es la propia señal (salir cuando la señal gira) + el vol
  targeting. Mantener un stop catastrófico ATR-diario como red está bien;
  trasplantar la gestión intradía entera, no. El kill switch diario
  probablemente pasa a semanal/mensual.
- Los estudios C1 (funding) y C2 (sesión) del ciclo actual no compiten con
  esto: C1 alimenta a M4 y a S5; C2 es irrelevante a horizonte diario (se
  archiva su resultado como conocimiento).

---

## 9. Preguntas abiertas para la sesión de brainstorming

1. **Instrumento:** ¿spot long / perp short (mi prior **[I]**), todo perp
   con funding modelado, o long/flat spot puro? (decide M4)
2. **Long/flat vs long/short:** el lado short de BTC históricamente pierde
   plata en promedio pero es donde el trend-following protege — ¿se acepta
   la asimetría de un long/flat?
3. **Grilla de lookbacks:** ¿fijar 3-5 valores pre-registrados (mi
   recomendación) o combinación multi-horizonte S3 desde el día uno?
4. **Histéresis:** ¿banda en señal, en precio, o confirmación de N días?
   ¿Con qué valores pre-registrados?
5. **σ_target del vol overlay** y cap de exposición.
6. **Ventana de datos:** ¿solo Binance 2017+ o serie extendida multi-venue?
7. **Umbral de adopción exacto** de M1/M2 (el propuesto en sección 7 es
   borrador).
8. **¿ETH entra al universo?** Duplicaría muestra de M1/M2 casi gratis y
   abre la puerta cross-sectional (3.5), pero Liu-Tsyvinski encontraron el
   efecto más débil en ETH **[V]** — testearlo por separado, no promediado.
9. **Convivencia operativa:** ¿el bot momentum es un proceso nuevo separado
   del scalper (mi prior: sí, comparte librerías pero no runtime) o un modo
   del mismo binario?
10. **Qué mata al proyecto:** pre-registrar también el criterio de abandono
    del pivote (ej.: si M1 y M2 fallan la verificación 2024-2026, no se
    optimiza nada — se acepta que la anomalía no sobrevivió a la
    institucionalización y se congela la búsqueda de señal).

---

## 10. Referencias

- Moskowitz, T., Ooi, Y.H., Pedersen, L.H. (2012). "Time Series Momentum".
  Journal of Financial Economics 104(2). [conocimiento general; paper
  canónico de TSMOM]
- Hurst, B., Ooi, Y.H., Pedersen, L.H. "A Century of Evidence on
  Trend-Following Investing". Journal of Portfolio Management.
  [conocimiento general]
- Liu, Y., Tsyvinski, A. (2021). "Risks and Returns of Cryptocurrency".
  Review of Financial Studies 34(6), 2689-2727.
  https://academic.oup.com/rfs/article-abstract/34/6/2689/5912024 —
  WP: https://www.nber.org/system/files/working_papers/w24877/w24877.pdf
- Liu, Y., Tsyvinski, A., Wu, X. (2022). "Common Risk Factors in
  Cryptocurrency". Journal of Finance 77(2), 1133-1177.
- Detzel, A., Liu, H., Strauss, J., Zhou, G., Zhu, Y. (2021). "Learning and
  predictability via technical analysis: Evidence from bitcoin and stocks
  with hard-to-value fundamentals". Financial Management 50(1), 107-137.
  https://onlinelibrary.wiley.com/doi/abs/10.1111/fima.12310
- Hudson, R., Urquhart, A. (2021). "Technical trading and
  cryptocurrencies". Annals of Operations Research.
  https://link.springer.com/article/10.1007/s10479-019-03357-1
- "Cryptocurrency momentum has (not) its moments" (2025). Financial Markets
  and Portfolio Management.
  https://link.springer.com/article/10.1007/s11408-025-00474-9
- Daniel, K., Moskowitz, T. (2016). "Momentum Crashes". Journal of
  Financial Economics. [conocimiento general]
- Moreira, A., Muir, T. (2017). "Volatility-Managed Portfolios". Journal of
  Finance. [conocimiento general]
- BIS Working Paper No. 1087, "Crypto carry".
  https://www.bis.org/publ/work1087.pdf
- Bailey, D., López de Prado, M. — deflated Sharpe ratio / backtest
  overfitting. [conocimiento general; buscar "The Deflated Sharpe Ratio"]
- Contexto de régimen 2024-2026: correlación BTC-Nasdaq post-ETF
  (https://arxiv.org/pdf/2501.09911), ciclo post-halving y ATH oct-2025
  (https://calebandbrown.com/blog/is-bitcoins-four-year-cycle-broken/),
  "losing the momentum trade" (CoinDesk, jun-2026).

---

*Disclaimer: documento de investigación de estrategia, no asesoramiento
financiero. Los niveles de retorno citados de papers con muestras 2011-2020
no son extrapolables; lo trasladable es la estructura del efecto, y su
supervivencia en 2024-2026 es exactamente lo que los estudios M1/M2 deben
responder antes de escribir una línea del bot.*
