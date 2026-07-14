# Analisis fundamentado de estrategia de scalping BTC

Fecha: 2026-06-19

Archivo analizado: `/Users/guillermoe/Downloads/strategy-rationale.md`

> Nota: este documento no es recomendacion financiera. Evalua la logica tecnica, riesgos de implementacion y requisitos de validacion de una estrategia automatizada de scalping para BTC.

## 1. Resumen ejecutivo

La estrategia esta razonablemente estructurada como una codificacion de un setup discrecional de price action: compresion de rango cerca de un nivel relevante, con filtros de regimen, tendencia multi-timeframe, spread, CVD, order book y contexto macro.

El punto fuerte no esta en la prueba del edge, sino en la arquitectura defensiva: sizing por riesgo fijo, stop basado en ATR, salida temporal, kill switch diario y reconciliacion contra el exchange. Eso reduce riesgo operacional y de ruina, pero no demuestra rentabilidad.

La conclusion principal es:

**La estrategia tiene una hipotesis plausible, pero todavia no tiene evidencia suficiente para operar capital real.** Falta demostrar que el setup produce expectancy positiva despues de fees, slippage, spread, latencia y condiciones reales de ejecucion.

## 2. Lectura de la estrategia actual

El pipeline de entrada funciona como una cadena de filtros duros. Para que haya trade, deben cumplirse todas estas condiciones:

1. Regimen conocido.
2. Estado de squeeze activo.
3. Sin posicion abierta.
4. Direccion de squeeze definida.
5. Spread aceptable.
6. No operar contra la tendencia de 15m.
7. Sin bloqueo macro.
8. En regimen breakout, la vela debe confirmar la direccion.
9. Sin divergencia CVD contraria.
10. Sin imbalance del book contrario.

Esta estructura es conservadora y reduce trades de baja calidad, pero tiene un riesgo clasico: muchos filtros pueden eliminar oportunidades sin mejorar necesariamente la expectancy. Por eso es imprescindible hacer un analisis de ablation: probar la estrategia base y luego agregar filtros uno por uno.

## 3. Lo que tiene buen fundamento

### 3.1 Compresion antes de expansion

La idea de operar despues de una compresion de rango tiene sustento conceptual. Los mercados financieros suelen mostrar clustering de volatilidad: periodos de baja volatilidad y alta volatilidad tienden a agruparse. Esto no prueba que una squeeze contra un nivel prediga direccion, pero si hace razonable buscar expansiones luego de compresiones.

Fundamento externo:

- El fenomeno de volatility clustering esta ampliamente documentado en series financieras. Ver: [Measuring Volatility Clustering in Stock Markets](https://arxiv.org/abs/0709.2416).
- Modelos tipo ARCH/GARCH fueron creados precisamente para capturar varianza condicional cambiante en el tiempo.

### 3.2 Filtros de microestructura

CVD e imbalance del order book son mas cercanos a la mecanica real del mercado que un patron visual puro. La intuicion es razonable: si el precio hace nuevo maximo sin confirmacion de delta comprador, podria haber absorcion; si el book muestra presion asimetrica persistente, podria anticipar movimiento de muy corto plazo.

Fundamento externo:

- Hay evidencia de predictibilidad de corto plazo usando datos de order book. Ver: [The Short-Term Predictability of Returns in Order Book Markets](https://arxiv.org/abs/2211.13777).

Limitacion importante: que el order book tenga informacion predictiva no significa que esta implementacion especifica tenga edge. La representacion, latencia, profundidad, ventana, costos y tipo de orden importan muchisimo.

### 3.3 Gestion de riesgo

El bloque de riesgo es el componente mas solido del sistema:

- Riesgo fijo por trade: 0.5% del balance diario inicial.
- Stop loss inicial: 1.5 ATR.
- TP1 parcial en 2R.
- Breakeven.
- Trailing estructural.
- Salida por tiempo.
- Abort por perdida de momentum.
- Kill switch diario por perdida o racha negativa.
- Reconciliacion de estado contra el exchange.

Usar ATR para dimensionar stop y posicion es una practica razonable: adapta el riesgo al regimen de volatilidad. Esto es correcto incluso si la senal no tiene edge. La gestion de riesgo no crea ventaja estadistica, pero evita que un error de senal se transforme en dano descontrolado.

## 4. Riesgos principales detectados

### 4.1 Posible inversion conceptual de la squeeze

Este es el punto mas critico.

El documento indica que la direccion se define asi:

```text
squeeze_direction = LONG si last_price > key_level
```

Pero tambien dice que la direccion esperada deberia ser "hacia el nivel contra el que se comprime". Esto abre una ambiguedad fuerte:

- Si el precio esta justo debajo de una resistencia y comprime contra ella, una ruptura clasica seria LONG.
- Si el precio esta justo encima de un soporte y comprime contra el, una ruptura clasica seria SHORT.

La regla `last_price > key_level => LONG` puede estar modelando continuacion segun el lado del nivel donde esta el precio, no ruptura del nivel. Si esa interpretacion no coincide con el setup original, el bot podria estar entrando al lado contrario de la hipotesis.

Mejora prioritaria:

**Crear tests unitarios y ejemplos visuales etiquetados para confirmar la direccion correcta de la squeeze antes de optimizar cualquier parametro.**

### 4.2 Costos demasiado altos para scalping si se opera taker

El documento usa fee taker de 0.05% por lado. Un trade de entrada y salida completa tiene al menos:

```text
0.05% entrada + 0.05% salida = 0.10% round trip
```

Eso es antes de slippage, spread y ejecuciones parciales.

En scalping, este costo puede comerse gran parte del R. Ejemplo:

| Stop efectivo | Fee round trip | Costo en R aproximado |
|---|---:|---:|
| 0.30% | 0.10% | 0.33R |
| 0.15% | 0.10% | 0.67R |
| 0.10% | 0.10% | 1.00R |
| 0.075% | 0.10% | 1.33R |

Si el stop promedio es chico, la estrategia puede necesitar una tasa de acierto o payoff muy exigente solo para empatar.

Mejora prioritaria:

**Agregar un filtro de costo minimo:** no operar si el movimiento esperado hasta TP1 no cubre fees, spread, slippage y un margen de seguridad.

### 4.3 Filtros no modelados en backtest

El documento reconoce que dos filtros importantes quedan inertes en backtest:

- Imbalance del order book.
- Filtro macro BTC-SPY.

Esto es grave para validacion: cualquier backtest actual no representa el comportamiento real del bot en vivo.

Mejora prioritaria:

**Separar dos modos de evaluacion:**

1. Backtest "core" solo con senales historicamente reproducibles.
2. Replay realista con datos L2/order book y contexto macro real o eliminado.

Si no se puede backtestear un filtro, no deberia ser decisivo para operar capital real.

### 4.4 Dependencia de latencia en order book imbalance

Las estrategias que usan imbalance del book pueden perder valor si la latencia es mala o si otros participantes reaccionan antes. La literatura de microestructura muestra que la rentabilidad de estrategias OBI depende fuertemente de la latencia relativa.

Fundamento externo:

- [The Importance of Low Latency to Order Book Imbalance Trading Strategies](https://arxiv.org/abs/2006.08682).

Mejora prioritaria:

**Medir latencia real extremo a extremo:** tick recibido, senal generada, orden enviada, ack recibido, fill recibido. Guardar estos timestamps en cada trade.

### 4.5 Filtro macro probablemente demasiado lento

El filtro BTC-SPY usa velas de 15m de SPY via `yfinance`, con posible delay. Para scalping de BTC, esto es mas un filtro direccional grueso que una senal accionable de microestructura.

Ademas, la correlacion BTC-SPY no es estable. Puede intensificarse en ciertos regimenes y desaparecer o cambiar en otros.

Fundamento externo:

- Estudios recientes encuentran que la correlacion BTC con indices como S&P 500 y Nasdaq varia por regimen y se intensifico en ciertos periodos institucionales. Ver: [Institutional Adoption and Correlation Dynamics: Bitcoin's Evolving Role in Financial Markets](https://arxiv.org/abs/2501.09911).

Mejora prioritaria:

**Eliminar el filtro macro del scalping o reemplazarlo por un filtro de regimen/evento mas robusto**, por ejemplo:

- calendario de FOMC, CPI, NFP;
- volatilidad implicita o realizada;
- ES/NQ futures en tiempo real;
- DXY;
- filtro de sesion y liquidez.

### 4.6 `trend_5m` calculado pero no usado

El documento indica que `trend_5m` se calcula pero no participa en `check_entry_signal`.

Eso puede ser:

- codigo muerto;
- una feature incompleta;
- una decision intencional mal documentada.

Mejora prioritaria:

**Decidir explicitamente su rol.** Mi preferencia: usar `trend_5m` como confirmacion suave o scoring, no como bloqueo duro.

## 5. Mejoras recomendadas

### Prioridad 1 - Validacion antes de optimizacion

Antes de tocar parametros, validar la logica base:

1. Confirmar direccion correcta de la squeeze con casos etiquetados.
2. Crear backtest reproducible con resultados persistidos.
3. Incluir fees, spread, slippage y latencia estimada.
4. Medir expectancy neta por trade, no solo win rate.
5. Separar resultados por regimen, horario, lado long/short y volatilidad.

Metricas minimas:

- Numero de trades.
- Win rate.
- Average win.
- Average loss.
- Expectancy neta.
- Profit factor neto.
- Max drawdown.
- Racha maxima de perdidas.
- MAE/MFE.
- Tiempo medio en posicion.
- PnL por sesion.
- PnL por regimen.
- Sensibilidad a fees y slippage.

### Prioridad 2 - Ablation de filtros

Probar incrementalmente:

1. Squeeze sola.
2. Squeeze + regimen.
3. Squeeze + regimen + tendencia 15m.
4. Agregar CVD.
5. Agregar spread.
6. Agregar order book.
7. Agregar macro.

El objetivo es saber que filtro mejora expectancy y cual solo reduce frecuencia.

Tabla deseada:

| Variante | Trades | Expectancy neta | Profit factor | Max DD | Observacion |
|---|---:|---:|---:|---:|---|
| Squeeze | | | | | |
| + Regimen | | | | | |
| + Tendencia 15m | | | | | |
| + CVD | | | | | |
| + Spread | | | | | |
| + OB | | | | | |
| + Macro | | | | | |

### Prioridad 3 - Modelo de costos y ejecucion

Implementar costos realistas:

- fee maker/taker segun tipo de orden;
- spread real al momento de entrada;
- slippage por tamano;
- fills parciales;
- latencia;
- funding si mantiene posicion cerca de timestamps relevantes;
- rechazo o timeout de orden;
- diferencia entre backtest mid-price y fill real.

Agregar condicion:

```text
operar solo si expected_move_to_tp1 > estimated_total_cost + safety_margin
```

### Prioridad 4 - Replantear salidas

Revisaria:

- Breakeven debe ser breakeven neto, no precio de entrada.
- El breathing stop no deberia expandir el riesgo maximo inicial.
- El TP1 en 2R puede ser demasiado lejano para scalping si el movimiento medio post-squeeze no llega ahi con frecuencia.
- Salida por momentum deberia validarse por MAE/MFE: puede estar cerrando trades que aun son buenos.

Propuesta:

- hard stop fijo de riesgo maximo;
- salida parcial adaptada a distribucion historica de MFE;
- trailing solo despues de que el trade haya pagado costos;
- breakeven neto con buffer.

### Prioridad 5 - Convertir filtros duros en scoring

En vez de exigir 10 condiciones binarias, usar un score:

```text
score = squeeze_quality
      + regime_score
      + trend_alignment
      + cvd_confirmation
      + book_confirmation
      - cost_penalty
      - latency_penalty
```

Luego operar solo si:

```text
score >= threshold
```

Ventaja: permite distinguir entre una senal excelente con una pequena objecion y una senal mediocre que pasa todos los filtros por casualidad.

### Prioridad 6 - Walk-forward y paper trading

Despues del backtest inicial:

1. Dividir historico en ventanas walk-forward.
2. Ajustar parametros solo en in-sample.
3. Evaluar out-of-sample.
4. Correr paper trading con el mismo codigo de produccion.
5. Comparar fills teoricos vs fills reales.

Fundamento externo:

- En trading algoritmico, el backtest unico es vulnerable a overfitting.
- Estudios recientes sobre BTC bajo costos muestran que senales aparentemente utiles pueden fallar una vez aplicados costos de transaccion. Ver: [Machine Learning-Based Bitcoin Trading Under Transaction Costs](https://arxiv.org/abs/2606.00060).

## 6. Cambios concretos que aplicaria al bot

### Cambio 1 - Tests de direccion de squeeze

Crear casos unitarios:

| Caso | Precio | Nivel | Contexto | Direccion esperada |
|---|---:|---:|---|---|
| Compresion debajo de resistencia | 99 | 100 | resistencia cercana | LONG |
| Compresion encima de soporte | 101 | 100 | soporte cercano | SHORT |

Si el codigo actual no distingue soporte/resistencia y solo usa distancia al nivel mas cercano, hay que enriquecer `key_level` con tipo de nivel.

### Cambio 2 - Registrar `setup_id` y features por trade

Cada trade deberia guardar:

- timestamp de senal;
- regimen;
- ATR;
- spread;
- distancia a nivel;
- tipo de nivel;
- direccion squeeze;
- trend_5m;
- trend_15m;
- CVD;
- OB ratio;
- macro state;
- estimated cost;
- latencia;
- entrada teorica;
- fill real;
- salida teorica;
- fill real;
- razon de salida.

Sin esto, no se puede auditar por que gana o pierde.

### Cambio 3 - Cost gate

Agregar una regla antes de entrar:

```text
min_expected_edge = expected_move_to_tp1 - estimated_total_cost
if min_expected_edge < required_edge:
    reject signal
```

### Cambio 4 - Backtest con reportes persistidos

Guardar automaticamente:

- `backtest_trades.csv`;
- `backtest_summary.md`;
- `equity_curve.csv`;
- `ablation_report.md`;
- `parameter_sensitivity.md`.

### Cambio 5 - Revisar el filtro macro

Opcion recomendada:

- desactivarlo por defecto para scalping;
- mantenerlo como filtro de "no operar en eventos/risk-off extremo";
- no usar `yfinance` como fuente de decision live.

### Cambio 6 - Separar senal de ejecucion

La estrategia deberia distinguir:

- senal direccional;
- decision de operar;
- tipo de orden;
- gestion de fill;
- salida.

Esto permite que una buena senal no sea arruinada por una mala ejecucion.

## 7. Veredicto

La estrategia tiene una hipotesis razonable y una capa de riesgo prudente, pero el edge no esta demostrado. El riesgo mas serio es que la direccion de la squeeze podria estar mal definida. El segundo gran problema es que, al ser scalping, los costos de transaccion pueden destruir la rentabilidad incluso si la senal acierta mas de lo que falla.

Mi recomendacion seria no optimizar parametros todavia. Primero hay que convertir la estrategia en un experimento medible:

1. Corregir o confirmar la direccion de la squeeze.
2. Medir expectancy neta con costos realistas.
3. Hacer ablation de filtros.
4. Validar out-of-sample.
5. Comparar paper trading contra backtest.

Solo despues de eso tendria sentido hablar de capital real.

## 8. Fuentes y fundamentos externos

- [The Short-Term Predictability of Returns in Order Book Markets](https://arxiv.org/abs/2211.13777): evidencia de predictibilidad de corto plazo usando informacion de order book.
- [The Importance of Low Latency to Order Book Imbalance Trading Strategies](https://arxiv.org/abs/2006.08682): impacto de la latencia en estrategias basadas en imbalance del order book.
- [Measuring Volatility Clustering in Stock Markets](https://arxiv.org/abs/0709.2416): documentacion empirica de clustering de volatilidad.
- [Institutional Adoption and Correlation Dynamics: Bitcoin's Evolving Role in Financial Markets](https://arxiv.org/abs/2501.09911): correlacion BTC con indices tradicionales y variacion por regimen.
- [Machine Learning-Based Bitcoin Trading Under Transaction Costs](https://arxiv.org/abs/2606.00060): importancia de costos de transaccion al convertir senales BTC en trades rentables.

