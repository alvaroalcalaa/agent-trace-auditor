# Agent Trace Auditor 🔎🤖

Revisa trazas de llamadas a herramientas de agentes de IA para detectar repeticiones, errores y ejecuciones que exceden un presupuesto de llamadas. Genera informes JSON y HTML sin enviar los registros a un servicio externo.

Creado el **26 de octubre de 2026**. **Python 3.10+, sin dependencias externas.**

## Probar en un minuto

```bash
git clone https://github.com/alvaroalcalaa/agent-trace-auditor.git
cd agent-trace-auditor
python audit.py examples/demo.jsonl --max-calls 3 --repeat 3 --json report.json --html report.html
python -m unittest -v
```

Abre `report.html` en un navegador. En algunos sistemas utiliza `python3`. Las carpetas de salida deben existir.

La demo tiene **6 eventos y 2 ejecuciones**, con datos ficticios:

| Ejecución | Llamadas | Resultado |
|---|---:|---|
| `healthy` | 2 | Sin hallazgos |
| `retry-loop` | 4 | Exceso de llamadas, repetición y un error |

El nombre `retry-loop` es solo una etiqueta de la demo; el auditor no prueba que exista un bucle infinito.

## Formato de entrada

Archivo UTF-8 JSONL: un objeto JSON por línea. Se permiten líneas vacías.

```json
{"event_id":"e1","run_id":"demo","tool":"search_docs","arguments":{"query":"combat"},"status":"ok","duration_ms":12}
```

Cada evento necesita exactamente estos seis campos:

| Campo | Contrato |
|---|---|
| `event_id` | Identificador único en todo el archivo, texto de 1–120 caracteres |
| `run_id` | Identificador de ejecución, texto de 1–120 caracteres |
| `tool` | Nombre de herramienta, texto de 1–120 caracteres |
| `arguments` | Objeto JSON con los argumentos registrados |
| `status` | `ok` o `error`: evento ya finalizado |
| `duration_ms` | Número finito no negativo, máximo 3 600 000 |

Se rechazan IDs duplicados para evitar contar dos veces el mismo evento de telemetría. El archivo tiene un límite de 8 MiB y 10 000 eventos. Un archivo vacío produce cero ejecuciones, no una prueba de que un agente funcionó correctamente.

## Reglas que aplica

- **`call_budget`:** una ejecución contiene más llamadas que `--max-calls` (por defecto 8).
- **`repeated_call`:** misma herramienta y mismos argumentos al menos `--repeat` veces dentro de una ejecución (por defecto 3).
- **`tool_errors`:** uno o más eventos tienen estado `error`.

La comparación de argumentos normaliza el orden de las claves JSON, también en objetos anidados. Conserva valores, orden de listas y representación numérica: `1` y `1.0` se consideran distintos. Las repeticiones no tienen que ser consecutivas. Se conservan los IDs de evento como evidencia, sin copiar los argumentos al informe.

La suma de duraciones de herramientas se llama `summed_tool_duration_ms`. **No es tiempo de pared**: las llamadas podrían ejecutarse en paralelo y solaparse.

## Usarlo como comprobación automática

```bash
python audit.py examples/demo.jsonl --fail-on-findings
```

| Código | Significado |
|---|---|
| 0 | Informe generado; por defecto los hallazgos no fallan el proceso |
| 1 | Hay hallazgos y se activó `--fail-on-findings` |
| 2 | Entrada, argumentos o escritura inválidos |

Los informes incluyen las ejecuciones ordenadas por identificador, los recuentos por herramienta y evidencia de cada regla. Las salidas no pueden coincidir con el archivo de entrada ni entre ellas. Los archivos de salida existentes se reemplazan.

## Privacidad y alcance

Los valores de `arguments` se usan en memoria para comparar llamadas y **no se exportan** al JSON ni al HTML. Los nombres de herramientas, IDs de ejecución y evento sí aparecen: revísalos antes de compartir el informe. El archivo de entrada original sigue conteniendo sus argumentos; el auditor no lo anonimiza ni lo borra.

El programa no ejecuta herramientas, no llama a modelos ni se conecta a un sistema de observabilidad. Debes adaptar las trazas de tu agente al formato JSONL descrito. Los registros originales incluidos son completamente sintéticos.

## Límites honestos y pruebas

Repetir una búsqueda puede ser legítimo y un error puede ser un reintento esperado. Estos hallazgos son señales para revisar, no diagnósticos automáticos de calidad, seguridad o coste. No detecta ciclos alternos con argumentos diferentes, no interpreta respuestas y no calcula tokens, precios ni causalidad. Solo ve los eventos presentes: una traza incompleta puede ocultar problemas.

El análisis agrupa todos los eventos de un `run_id`; no utiliza timestamps ni ventanas temporales. Carga el archivo en memoria. No hay adaptadores probados con LangGraph, MCP, OpenTelemetry o proveedores concretos.

Las pruebas cubren resultados conocidos, normalización JSON, separación de ejecuciones, límites, argumentos omitidos del informe, escape HTML, eventos inválidos, duplicados, lectura con número de línea y exportación real del CLI.
