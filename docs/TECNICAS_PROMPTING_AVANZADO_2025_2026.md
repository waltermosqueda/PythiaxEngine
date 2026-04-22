# Tecnicas Avanzadas de Prompting 2025-2026
## Guia Completa para Obtener Mejores Resultados de LLMs

*Compilado: Abril 2026*

---

## INDICE

1. [Frameworks de Razonamiento Avanzado](#1-frameworks-de-razonamiento-avanzado)
2. [Meta-Prompting y Encadenamiento](#2-meta-prompting-y-encadenamiento)
3. [Ingenieria de System Prompts](#3-ingenieria-de-system-prompts)
4. [Tecnicas de Output Estructurado](#4-tecnicas-de-output-estructurado)
5. [Tecnicas para Analisis Cuantitativo/Financiero](#5-tecnicas-para-analisis-cuantitativofinanciero)
6. [Patrones Multi-Agente y Orquestacion](#6-patrones-multi-agente-y-orquestacion)
7. [Optimizacion de Prompts](#7-optimizacion-de-prompts)
8. [Tecnicas Emergentes 2025-2026](#8-tecnicas-emergentes-2025-2026)
9. [Aplicacion Practica para Proyecto TITAN](#9-aplicacion-practica-para-proyecto-titan)

---

## 1. Frameworks de Razonamiento Avanzado

### 1.1 Chain-of-Thought (CoT) - La Base

**Que es:** Forzar al modelo a razonar paso a paso antes de dar una respuesta final.

**Por que funciona:** Los LLMs generan tokens secuencialmente. Si les pides la respuesta directa, "saltan" pasos logicos. Al obligarlos a escribir los pasos intermedios, cada token generado condiciona mejor al siguiente.

**Mejora promedio:** +6% de accuracy vs. prompts directos.

**Variantes:**
- **Zero-Shot CoT:** Simplemente agregar "Piensa paso a paso" al final del prompt
- **Few-Shot CoT:** Dar 2-3 ejemplos con razonamiento explicito antes de la pregunta
- **Auto-CoT:** El modelo genera sus propios ejemplos de razonamiento

**Ejemplo practico:**
```
MALO:  "Cual es el mejor momento para comprar NVDA?"
BUENO: "Analiza paso a paso las condiciones actuales de NVDA:
        1. Primero evalua el RSI actual y su tendencia
        2. Luego compara el precio vs SMA50
        3. Despues considera el regimen del mercado (SPY)
        4. Finalmente, da tu conclusion basada en estos datos"
```

**Cuando usarlo:** Cualquier tarea que requiera logica, analisis o multiples pasos de razonamiento.

---

### 1.2 Tree of Thoughts (ToT) - Exploracion Ramificada

**Que es:** En lugar de un solo camino de razonamiento (CoT), el modelo explora multiples caminos en paralelo, como un arbol de decisiones, y elige el mejor.

**Diferencia clave vs CoT:** CoT es lineal (A -> B -> C). ToT es ramificado: genera multiples opciones en cada paso, evalua cual es mas prometedora, y puede hacer backtracking si un camino no funciona.

**Ejemplo practico:**
```
"Necesito evaluar si entrar en AAPL. Genera 3 hipotesis diferentes:

Hipotesis 1: Caso alcista - lista las evidencias a favor
Hipotesis 2: Caso bajista - lista las evidencias en contra
Hipotesis 3: Caso neutral - lista las razones para esperar

Para cada hipotesis, evalua la fuerza de la evidencia del 1-10.
Luego selecciona la hipotesis mas robusta y explica por que."
```

**Cuando usarlo:** Problemas complejos con multiples soluciones posibles, decisiones de inversion, analisis de escenarios.

---

### 1.3 Self-Consistency - Multiples Muestras, Una Respuesta

**Que es:** Generar multiples respuestas al mismo problema (cada una con diferente razonamiento) y tomar la respuesta mas frecuente como la correcta.

**Principio:** Si un problema tiene una respuesta correcta, multiples caminos de razonamiento deberian converger en ella. La respuesta "ganadora por mayoria" suele ser la correcta.

**Implementacion practica (sin API):**
```
"Quiero que analices este trade 3 veces con enfoques diferentes:

Analisis 1: Desde perspectiva tecnica pura (RSI, SMA, volumen)
Analisis 2: Desde perspectiva de momentum y tendencia
Analisis 3: Desde perspectiva de riesgo/recompensa

Despues de los 3 analisis, indica cual es la conclusion en la que
al menos 2 de 3 coinciden."
```

**Cuando usarlo:** Decisiones criticas donde quieres mayor confianza en la respuesta.

---

### 1.4 ReAct (Reasoning + Acting) - Razonamiento con Herramientas

**Que es:** El modelo alterna entre PENSAR (razonar sobre la situacion) y ACTUAR (usar herramientas, buscar datos, ejecutar codigo). Es el patron base de todos los agentes AI.

**Flujo:**
1. Pensamiento: "Necesito saber el RSI actual de NVDA"
2. Accion: Busca el dato en la base de datos
3. Observacion: "RSI = 23.5"
4. Pensamiento: "RSI < 25, cumple el filtro. Ahora necesito el SMA50..."
5. Accion: Calcula SMA50
6. (continua hasta completar el analisis)

**Ya lo usas:** Claude Code opera con este patron cuando ejecuta codigo, lee archivos y razona entre pasos.

---

## 2. Meta-Prompting y Encadenamiento

### 2.1 Prompt Chaining (Encadenamiento)

**Que es:** Dividir una tarea compleja en subtareas, donde la salida de un prompt alimenta el siguiente.

**Por que es superior a un solo prompt largo:**
- Cada paso tiene un objetivo claro y acotado
- Puedes verificar resultados intermedios
- Reduces errores acumulados
- El modelo mantiene mejor el foco

**Ejemplo para analisis de portafolio:**
```
Paso 1: "Lista los 10 activos con peor performance relativa esta semana"
         -> Output: lista de tickers

Paso 2: "Para cada ticker de esta lista [output paso 1], calcula RSI(14)
         y distancia a SMA50"
         -> Output: tabla con metricas

Paso 3: "De esta tabla [output paso 2], filtra solo los que cumplen
         RSI < 25 Y SMA50 dist < -10%"
         -> Output: candidatos filtrados

Paso 4: "Para los candidatos [output paso 3], evalua el regimen de SPY
         y genera recomendacion final"
```

---

### 2.2 Meta-Prompting - El Prompt que Crea Prompts

**Que es:** Usar el LLM para generar o mejorar prompts para si mismo u otros modelos. No te enfocas en el contenido sino en la ESTRUCTURA del prompt.

**Variante avanzada - Recursive Meta Prompting (RMP):**
El modelo genera un prompt, lo ejecuta, evalua la calidad del resultado, y refina el prompt original en un ciclo iterativo.

**Ejemplo practico:**
```
"Eres un experto en prompt engineering. Necesito un prompt que analice
senales de trading de forma consistente y estructurada.

El prompt debe:
- Producir output en formato tabla
- Considerar RSI, SMA50, volumen, y regimen de mercado
- Incluir un score numerico de 0-100
- Tener un formato reproducible para cualquier ticker

Genera el prompt optimo para esta tarea."
```

**Cuando usarlo:** Cuando necesitas un prompt que vas a reutilizar muchas veces y quieres la version mas pulida posible.

---

### 2.3 Skeleton-of-Thought (SoT) - Esqueleto Primero

**Que es:** El modelo primero genera un esqueleto/estructura de la respuesta, y luego rellena cada seccion en paralelo.

**Ventaja:** Respuestas mas organizadas y completas. Reduce la tendencia a "olvidar" secciones.

**Ejemplo:**
```
"Primero genera SOLO el esqueleto (titulos de secciones) de un analisis
completo del sector semiconductores. No escribas contenido aun.

[Modelo genera esqueleto]

Ahora desarrolla cada seccion del esqueleto con datos y analisis."
```

---

## 3. Ingenieria de System Prompts

### 3.1 Principios de Anthropic para Claude (Oficial 2025-2026)

Segun la documentacion oficial de Anthropic:

**Principio 1: Claridad > Complejidad**
El mejor prompt NO es el mas largo ni el mas complejo. Es el que logra el objetivo con la minima estructura necesaria.

**Principio 2: Usa XML para estructurar**
Claude fue entrenado con tags XML en sus datos. Usar `<ejemplo>`, `<contexto>`, `<instruccion>` mejora significativamente la adherencia a instrucciones.

```xml
<contexto>
Eres un analista cuantitativo. Tus decisiones se basan SOLO en datos.
</contexto>

<reglas>
1. Nunca recomiendes sin evidencia numerica
2. Siempre incluye el RSI y SMA50 en tu analisis
3. Si no tienes datos suficientes, di "datos insuficientes"
</reglas>

<formato_output>
| Ticker | RSI | SMA50_dist | Score | Senal |
</formato_output>
```

**Principio 3: Instrucciones en el Human Message > System Message**
Claude sigue mejor las instrucciones que estan en el mensaje del usuario que las del system prompt. Usar el system prompt para contexto general y el user message para instrucciones especificas.

**Principio 4: Dale tiempo para pensar**
Incluir "Piensa paso a paso" o "Antes de responder, razona internamente" mejora la calidad en tareas analiticas.

**Principio 5: Context Engineering**
La ingenieria de contexto consiste en encontrar el conjunto minimo de tokens de alta senal que maximicen la probabilidad del resultado deseado. Menos texto irrelevante = mejor rendimiento.

---

### 3.2 Estructura de System Prompt de 10 Pasos (Profesional)

Estructura recomendada por practicantes avanzados:

```
1. IDENTIDAD: Quien es el modelo (rol, expertise)
2. OBJETIVO: Que debe lograr
3. CONTEXTO: Informacion de fondo relevante
4. REGLAS: Restricciones inviolables
5. FORMATO: Como debe estructurar la salida
6. EJEMPLOS: 1-2 ejemplos del output deseado
7. EDGE CASES: Que hacer en situaciones ambiguas
8. ANTI-PATRONES: Que NO debe hacer
9. EVALUACION: Como saber si la respuesta es buena
10. FALLBACK: Que hacer si no puede completar la tarea
```

---

### 3.3 Prompt Scaffolding (Andamiaje Defensivo)

Tecnica de envolver el input del usuario en una estructura que limita respuestas no deseadas:

```
<sistema>
Tu rol es [ROL]. Responde UNICAMENTE sobre [DOMINIO].
Si la pregunta esta fuera de tu dominio, responde:
"Eso esta fuera de mi area de analisis."
</sistema>

<formato_obligatorio>
Toda respuesta debe incluir:
- Datos concretos (numeros, fechas)
- Nivel de confianza (alto/medio/bajo)
- Fuente o razonamiento
</formato_obligatorio>

<pregunta_usuario>
{input del usuario aqui}
</pregunta_usuario>
```

---

## 4. Tecnicas de Output Estructurado

### 4.1 Forzar Formato JSON/Tabla

**Principio:** Forzar la salida a un formato estructurado reduce alucinaciones y mejora la consistencia dramaticamente.

```
"Analiza estos 5 tickers y devuelve tu respuesta UNICAMENTE en este
formato JSON. No incluyas texto adicional:

{
  "fecha_analisis": "YYYY-MM-DD",
  "tickers": [
    {
      "symbol": "XXXX",
      "rsi_14": float,
      "sma50_dist_pct": float,
      "score": int (0-100),
      "senal": "COMPRAR" | "ESPERAR" | "EVITAR",
      "confianza": "alta" | "media" | "baja",
      "razon_principal": "string (max 20 palabras)"
    }
  ]
}
```

### 4.2 Tecnica de Calibracion de Confianza

Pedir al modelo que exprese su nivel de confianza obliga a "auto-evaluarse":

```
"Para cada prediccion, asigna un porcentaje de confianza (0-100%)
y explica que la haria subir o bajar. Si tu confianza es menor
a 60%, marca la prediccion como 'REQUIERE MAS DATOS'."
```

### 4.3 Pre-mortem Prompting

Tecnica poderosa para decision-making:

```
"Imagina que seguimos esta estrategia y falla completamente en 6 meses.
Haz un 'post-mortem' desde el futuro:
1. Que salio mal?
2. Que senales ignoramos?
3. Que deberiamos haber hecho diferente?

Ahora, con esas lecciones, ajusta la recomendacion original."
```

---

## 5. Tecnicas para Analisis Cuantitativo/Financiero

### 5.1 Estado del Arte en Finanzas + LLMs

Segun investigacion academica reciente (2025):
- **Graph-of-Thought** logra 15-25% mas accuracy en razonamiento financiero complejo vs metodos baseline
- **Chain-of-Table** mejora 8.69% en tareas de datos tabulares
- Solo 10-15% de instituciones financieras han explorado Graph-of-Thought (oportunidad)
- Los LLMs son AUXILIARES en trading cuantitativo: sirven para analisis de sentimiento, generacion de hipotesis y validacion de logica, NO para optimizacion numerica directa

### 5.2 Framework GuruAgents

Tecnica emergente que emula filosofias de inversores reconocidos usando agentes LLM especializados:

```
"Analiza NVDA desde 3 perspectivas de inversion:

AGENTE 1 - Value Investor (estilo Buffett):
- Evalua fundamentales, moat, precio vs valor intrinseco

AGENTE 2 - Momentum Trader (estilo O'Neil):
- Evalua fuerza relativa, breakouts, volumen

AGENTE 3 - Quant Analyst (estilo Renaissance):
- Evalua anomalias estadisticas, mean reversion, RSI

Cada agente da su veredicto. Luego, un AGENTE MODERADOR
pondera las 3 opiniones y da la recomendacion final."
```

### 5.3 Alpha-GPT: Generacion de Senales con Prompts

Tecnica de usar LLMs para generar hipotesis de alpha (senales de trading) que luego se validan con backtest:

```
"Dado el siguiente dataset de OHLCV para [TICKER]:
- Periodo: [FECHAS]
- Metricas disponibles: [LISTA]

Genera 5 hipotesis de trading originales que podrian producir alpha.
Para cada hipotesis:
1. Describe la logica detras
2. Define las reglas exactas de entrada y salida
3. Indica que datos necesitas para validarla
4. Estima la frecuencia esperada de trades

Prioriza hipotesis simples (max 3-4 variables) sobre complejas."
```

### 5.4 Prompt para Validacion Cruzada de Estrategias

```
"Actua como un comite de riesgo. Revisa esta estrategia de trading:
[DESCRIPCION DE LA ESTRATEGIA]

Evalua:
1. OVERFITTING: Hay senales de sobreajuste? Los filtros son demasiados?
2. ROBUSTEZ: Funcionaria en diferentes regimenes de mercado?
3. SESGO DE SUPERVIVENCIA: Estamos ignorando activos que deslistaron?
4. DATA SNOOPING: Se usaron datos futuros en algun paso?
5. COSTOS OCULTOS: Slippage, comisiones, impacto de mercado?

Para cada punto, da un rating de riesgo: BAJO / MEDIO / ALTO
y una recomendacion especifica."
```

---

## 6. Patrones Multi-Agente y Orquestacion

### 6.1 Contexto: La Explosion de Multi-Agente

Los workflows multi-agente crecieron 327% entre junio y octubre 2025. En pruebas controladas (348 trials), los sistemas multi-agente lograron 80x mejor especificidad y 140x mejor correccion que agentes individuales.

### 6.2 Patron: Especialista + Critico + Sintetizador

```
AGENTE 1 (Especialista): Genera la respuesta/analisis inicial
AGENTE 2 (Critico): Revisa, encuentra errores, cuestiona supuestos
AGENTE 3 (Sintetizador): Combina el analisis original con las criticas
                          y produce la version final mejorada
```

**Implementacion en un solo prompt (sin framework):**
```
"Ejecuta este analisis en 3 fases:

FASE 1 - ANALISTA:
Analiza [TAREA] con todos los datos disponibles. Se exhaustivo.

FASE 2 - CRITICO:
Ahora cambia de rol. Eres un critico esceptico. Revisa el analisis
de la Fase 1 y lista TODOS los puntos debiles, supuestos no validados,
y posibles errores.

FASE 3 - DIRECTOR:
Combina la Fase 1 y Fase 2. Produce el analisis final que incorpora
las criticas validas y descarta las que no aplican."
```

### 6.3 Patron: Router (Orquestador)

Un agente "router" decide cual especialista debe manejar cada subtarea:

```
"Eres un orquestador. Recibiras consultas sobre trading.

Para consultas TECNICAS (RSI, SMA, patrones): usa enfoque cuantitativo
Para consultas de SENTIMIENTO (noticias, earnings): usa enfoque cualitativo
Para consultas de RIESGO (sizing, drawdown): usa enfoque de gestion de riesgo

Primero, clasifica la consulta. Luego responde con el enfoque correcto."
```

### 6.4 Frameworks Principales (2026)

- **LangChain/LangGraph:** El mas adoptado (126K+ stars GitHub). LangGraph para flujos stateful y multi-paso
- **CrewAI:** Enfocado en equipos de agentes con roles definidos
- **AutoGen (Microsoft):** Para conversaciones multi-agente
- **OpenAI Agents SDK:** Orquestacion nativa de OpenAI
- **DSPy (Stanford):** Programacion declarativa, no prompting

---

## 7. Optimizacion de Prompts

### 7.1 Few-Shot vs Zero-Shot

| Tecnica | Descripcion | Mejora |
|---------|-------------|--------|
| Zero-Shot | Sin ejemplos, solo instrucciones | Baseline |
| Zero-Shot CoT | "Piensa paso a paso" | +6% avg |
| Few-Shot (2-3 ejemplos) | Ejemplos del output deseado | +80% eficiencia |
| Few-Shot CoT | Ejemplos CON razonamiento | Mejor combinacion |

**Regla practica:** Si la tarea es simple, Zero-Shot basta. Si necesitas formato especifico o razonamiento complejo, usa Few-Shot con 2-3 ejemplos de alta calidad.

### 7.2 DSPy: Optimizacion Automatica de Prompts

DSPy (Stanford) es un framework que PROGRAMA en vez de promptear:
- **BootstrapFewShot:** Selecciona automaticamente los mejores ejemplos few-shot
- **MIPROv2:** Optimiza instrucciones Y ejemplos simultaneamente usando optimizacion bayesiana
- Combinar optimizacion de instrucciones + ejemplos produce los mejores resultados

**Hallazgo clave:** La optimizacion automatica de prompts supera consistentemente a los prompts escritos manualmente, especialmente en tareas complejas.

### 7.3 Tecnica de Refinamiento Iterativo

```
"[Tu prompt original]

Ahora evalua tu propia respuesta:
- Es completa? Falta algo critico?
- Es precisa? Hay errores facticos?
- Es util? Le sirve al usuario para tomar accion?

Si la respuesta a cualquiera es NO, reescribe la respuesta mejorada."
```

### 7.4 Constitutional AI Prompting

Definir "principios constitucionales" que el modelo debe seguir:

```
"Antes de dar tu respuesta final, verifica que cumpla estos principios:
1. Toda afirmacion tiene evidencia numerica que la respalda
2. No hay recomendaciones basadas en emocion o narrativa
3. Los riesgos estan explicitamente mencionados
4. El nivel de confianza es honesto (no sobre-confiado)

Si tu respuesta viola alguno, corrigela antes de presentarla."
```

---

## 8. Tecnicas Emergentes 2025-2026

### 8.1 Graph-of-Thought (GoT)

Evolucion de Tree-of-Thought. Los pensamientos se modelan como NODOS en un GRAFO, permitiendo conexiones no lineales entre ideas.

- Complejidad y Flexibilidad: 5/5
- Explicabilidad: 2/5
- Mejora en razonamiento financiero: +15-25% vs baseline
- Reduce alucinaciones: -25-30%
- Limitacion: Alto costo computacional

### 8.2 Context Engineering (Ingenieria de Contexto)

Termino acunado por Anthropic en 2025. El enfoque cambia de "como escribo el prompt" a "que contexto le doy al modelo."

**Principio central:** Encontrar el MINIMO conjunto de informacion de ALTA senal que maximice la probabilidad del resultado deseado.

**Aplicacion practica:**
- NO enviar toda la base de datos. Enviar solo los datos relevantes.
- NO dar instrucciones redundantes. Cada token debe aportar valor.
- Pre-procesar datos antes de enviarlos al modelo.

### 8.3 Prompting Multimodal

En 2026, los modelos procesan texto + imagenes + codigo simultaneamente:
- Enviar graficos de precios como imagenes para analisis visual
- Combinar datos tabulares con charts para analisis holista
- Razonamiento multimodal chain-of-thought (texto + visual)

### 8.4 Domain-Specialized Prompting

Prediccion para 2026: prompts especializados por dominio superan a los genericos:
- Prompts financieros con vocabulario y marcos especificos del sector
- Templates pre-construidos para tipos de analisis recurrentes
- Conocimiento de dominio embebido en la estructura del prompt

### 8.5 Prompt Caching y Optimizacion de Costos

Tecnica practica: disenar prompts con un prefijo largo y estable (system prompt, contexto, ejemplos) que se cachea, y un sufijo corto y variable (la pregunta especifica). Reduce costos hasta 90% en uso repetitivo.

---

## 9. Aplicacion Practica para Proyecto TITAN

### 9.1 Prompt Optimizado para Scanner

Basado en todas las tecnicas anteriores, un prompt optimizado para analisis de senales:

```xml
<rol>
Analista cuantitativo. Solo decisiones basadas en datos.
</rol>

<reglas_inviolables>
1. RSI: Wilder's smoothing (ewm com=13), NUNCA rolling mean
2. Solo senales donde RSI(14) < 25 Y SMA50 dist < -10% Y Score > 30
3. SPY debe estar sobre SMA50 con vol < 1%
4. Sin repetir ticker en 5 dias (anti-knife)
</reglas_inviolables>

<formato>
Devuelve SOLO formato tabla:
| Ticker | RSI | SMA50% | Score | Senal | Confianza |
</formato>

<verificacion>
Antes de devolver resultados:
- Confirma que RSI usa Wilder's smoothing
- Confirma que SPY cumple condiciones de regimen
- Confirma que ningun ticker aparecio en ultimos 5 dias
</verificacion>
```

### 9.2 Template para Evaluacion de Nueva Estrategia

```
"Evalua esta propuesta de cambio al scanner usando el framework
Especialista-Critico-Director:

PROPUESTA: [descripcion del cambio]

FASE 1 - ANALISTA:
- Cual es la hipotesis detras del cambio?
- Que mejora esperas en WR, Sharpe, o MDD?
- Datos historicos que la soportan?

FASE 2 - CRITICO:
- Puede ser overfitting?
- Se sostiene en out-of-sample?
- Agrega complejidad innecesaria? (recuerda: 4 reglas Sharpe 14
  vs 40 features ML Sharpe -0.65)

FASE 3 - VEREDICTO:
- Proceder con backtest? SI/NO
- Si SI, que metricas monitorear
- Si NO, por que"
```

### 9.3 Prompt para Backtest Review

```
"Actua como auditor de backtests. Revisa estos resultados:
[RESULTADOS]

Checklist de validacion:
[ ] Look-ahead bias: se usaron datos futuros?
[ ] Survivorship bias: se excluyeron tickers deslistados?
[ ] Periodo suficiente: al menos 18 meses de datos?
[ ] Out-of-sample: hay validacion fuera de muestra?
[ ] Walk-forward: se probo con ventanas moviles?
[ ] Transaction costs: se incluyeron comisiones?
[ ] Slippage: se modelo el deslizamiento?

Para cada item, indica PASS/FAIL/NO VERIFICABLE."
```

---

## Resumen: Las 10 Tecnicas Mas Impactantes

| # | Tecnica | Impacto | Dificultad | Uso Recomendado |
|---|---------|---------|------------|-----------------|
| 1 | Chain-of-Thought | Alto | Baja | Todo analisis complejo |
| 2 | Few-Shot (2-3 ejemplos) | Alto | Baja | Output con formato especifico |
| 3 | XML Structuring | Alto | Baja | Prompts largos/complejos |
| 4 | Prompt Chaining | Alto | Media | Tareas multi-paso |
| 5 | Self-Consistency | Medio | Media | Decisiones criticas |
| 6 | Pre-mortem Prompting | Alto | Baja | Evaluacion de riesgos |
| 7 | Especialista-Critico | Alto | Media | Analisis profundo |
| 8 | Output Estructurado (JSON) | Alto | Baja | Datos para procesamiento |
| 9 | Context Engineering | Alto | Media | Todo (menos es mas) |
| 10 | Calibracion de Confianza | Medio | Baja | Predicciones/recomendaciones |

---

## Fuentes

- [Prompt Engineering Guide - Tecnicas](https://www.promptingguide.ai/techniques)
- [Anthropic - Prompting Best Practices](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
- [Anthropic - Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [IBM - Chain of Thought](https://www.ibm.com/think/topics/chain-of-thoughts)
- [IBM - Tree of Thoughts](https://www.ibm.com/think/topics/tree-of-thoughts)
- [ArXiv - Self-Consistency (2203.11171)](https://arxiv.org/abs/2203.11171)
- [ArXiv - Meta Prompting (2311.11482)](https://arxiv.org/abs/2311.11482)
- [ArXiv - LLMs in Quantitative Investment](https://arxiv.org/html/2503.21422v1)
- [ArXiv - GuruAgents](https://arxiv.org/html/2510.01664v1)
- [ArXiv - Multi-Agent Orchestration](https://arxiv.org/abs/2511.15755)
- [Frontiers - LLMs in Equity Markets](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1608365/full)
- [DSPy Framework - Stanford](https://dspy.ai/)
- [Lakera - Prompt Engineering Guide 2026](https://www.lakera.ai/blog/prompt-engineering-guide)
- [K2View - Prompt Engineering Techniques 2026](https://www.k2view.com/blog/prompt-engineering-techniques/)
- [Deloitte - Prompt Engineering for Finance](https://www.deloitte.com/us/en/services/consulting/articles/prompt-engineering-for-finance.html)
- [Springer - Taxonomy of Prompt Engineering](https://link.springer.com/article/10.1007/s11704-025-50058-z)
