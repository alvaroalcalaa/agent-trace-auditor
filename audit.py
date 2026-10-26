"""Offline audit of completed agent tool-call traces. Python 3.10+."""
import argparse
from collections import defaultdict
import html
import json
import math
from pathlib import Path

FIELDS = {"event_id", "run_id", "tool", "arguments", "status", "duration_ms"}
MAX_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 10000


def strict_json(text):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Clave JSON duplicada")
            result[key] = value
        return result
    def reject(value):
        raise ValueError("Constante JSON no válida")
    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject)


def validate_event(event):
    if not isinstance(event, dict) or set(event) != FIELDS:
        raise ValueError("Cada evento necesita exactamente: " + ", ".join(sorted(FIELDS)))
    for key in ("event_id", "run_id", "tool"):
        if not isinstance(event[key], str) or not event[key].strip() or len(event[key]) > 120:
            raise ValueError(f"{key} debe ser texto no vacío de hasta 120 caracteres")
    if event["status"] not in ("ok", "error"):
        raise ValueError("status debe ser ok o error")
    duration = event["duration_ms"]
    if (type(duration) not in (int, float) or not math.isfinite(duration)
            or not 0 <= duration <= 3600000):
        raise ValueError("duration_ms debe estar entre 0 y 3600000 y ser finito")
    if not isinstance(event["arguments"], dict):
        raise ValueError("arguments debe ser un objeto JSON")
    json.dumps(event["arguments"], allow_nan=False, sort_keys=True)
    return event


def read_trace(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Archivo demasiado grande: máximo 8 MiB")
    events, ids = [], set()
    for line, text in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not text.strip():
            continue
        try:
            event = validate_event(strict_json(text))
            if event["event_id"] in ids:
                raise ValueError("event_id duplicado")
            ids.add(event["event_id"])
            events.append(event)
            if len(events) > MAX_EVENTS:
                raise ValueError("Demasiados eventos: máximo 10000")
        except (ValueError, TypeError, RecursionError) as error:
            raise ValueError(f"Línea {line}: {error}") from error
    return events


def audit(events, max_calls=8, repeat_threshold=3):
    if type(max_calls) is not int or not 1 <= max_calls <= MAX_EVENTS:
        raise ValueError("max_calls debe estar entre 1 y 10000")
    if type(repeat_threshold) is not int or not 2 <= repeat_threshold <= MAX_EVENTS:
        raise ValueError("repeat_threshold debe estar entre 2 y 10000")
    runs, seen = defaultdict(list), set()
    for event in events:
        validate_event(event)
        if event["event_id"] in seen:
            raise ValueError("event_id duplicado")
        seen.add(event["event_id"])
        runs[event["run_id"]].append(event)
    reports = []
    for run_id, calls in sorted(runs.items()):
        findings, signatures, tools = [], defaultdict(list), defaultdict(int)
        for call in calls:
            signature = (call["tool"], json.dumps(call["arguments"], sort_keys=True,
                         ensure_ascii=False, allow_nan=False, separators=(",", ":")))
            signatures[signature].append(call["event_id"])
            tools[call["tool"]] += 1
        if len(calls) > max_calls:
            findings.append({"type": "call_budget", "actual": len(calls), "limit": max_calls})
        for (tool, _), event_ids in signatures.items():
            if len(event_ids) >= repeat_threshold:
                findings.append({"type": "repeated_call", "tool": tool,
                                 "count": len(event_ids), "event_ids": event_ids})
        errors = [call["event_id"] for call in calls if call["status"] == "error"]
        if errors:
            findings.append({"type": "tool_errors", "count": len(errors), "event_ids": errors})
        reports.append({
            "run_id": run_id, "status": "attention" if findings else "ok",
            "calls": len(calls), "errors": len(errors),
            "summed_tool_duration_ms": round(sum(c["duration_ms"] for c in calls), 3),
            "tools": dict(sorted(tools.items())), "findings": findings,
        })
    return {"events": len(seen), "runs": len(reports),
            "runs_with_findings": sum(r["status"] == "attention" for r in reports),
            "policy": {"max_calls": max_calls, "repeat_threshold": repeat_threshold},
            "results": reports}


def render_html(report):
    esc = lambda value: html.escape(str(value))
    rows, details = [], []
    for run in report["results"]:
        rows.append("<tr>" + "".join(f"<td>{esc(run[k])}</td>" for k in
                    ("run_id", "status", "calls", "errors", "summed_tool_duration_ms")) + "</tr>")
        entries = "".join(f"<li><code>{esc(f['type'])}</code> — {esc(json.dumps(f, ensure_ascii=False))}</li>"
                          for f in run["findings"])
        details.append(f"<section><h2>{esc(run['run_id'])}</h2><ul>{entries or '<li>Sin hallazgos.</li>'}</ul></section>")
    return f"""<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width"><title>Agent Trace Auditor</title>
<style>body{{font:16px system-ui;background:#0d1525;color:#edf4ff;margin:0}}
main{{max-width:1080px;margin:auto;padding:40px 24px}}h1{{font-size:36px}}
p,li{{color:#bdcbe0;line-height:1.6}}.card{{background:#18273e;padding:20px;border-radius:14px}}
table{{width:100%;border-collapse:collapse}}td,th{{padding:12px;text-align:left;border-bottom:1px solid #304159}}
th,code{{color:#75e3ce}}.scroll{{overflow:auto}}li{{overflow-wrap:anywhere}}section{{margin-top:28px}}
</style><main><p>OBSERVABILIDAD LOCAL · REGISTROS DE HERRAMIENTAS</p>
<h1>Agent Trace Auditor</h1>
<div class="card">{report["events"]} eventos · {report["runs"]} ejecuciones ·
{report["runs_with_findings"]} con hallazgos</div>
<p>Política: máximo {report["policy"]["max_calls"]} llamadas por ejecución;
repetición a partir de {report["policy"]["repeat_threshold"]} llamadas iguales.</p>
<div class="scroll"><table><thead><tr><th>Ejecución</th><th>Estado</th><th>Llamadas</th>
<th>Errores</th><th>Suma de duraciones (ms)</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>
{"".join(details)}<p>Los argumentos no se exportan. Los identificadores y nombres de herramientas sí.
Repetir una llamada no demuestra un bucle; revisa el contexto. Las duraciones se suman
y pueden solaparse: no son el tiempo real de ejecución.</p></main></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json", type=Path, dest="json_path")
    parser.add_argument("--html", type=Path, dest="html_path")
    parser.add_argument("--fail-on-findings", action="store_true")
    args = parser.parse_args()
    outputs = [p.resolve() for p in (args.json_path, args.html_path) if p]
    if args.trace.resolve() in outputs or len(outputs) != len(set(outputs)):
        parser.error("Las salidas deben ser distintas entre sí y de la entrada")
    try:
        report = audit(read_trace(args.trace), args.max_calls, args.repeat)
        payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.json_path:
            args.json_path.write_text(payload, encoding="utf-8")
        if args.html_path:
            args.html_path.write_text(render_html(report), encoding="utf-8")
        print(payload, end="")
    except (OSError, ValueError, TypeError, RecursionError) as error:
        parser.exit(2, f"Error: {error}\n")
    parser.exit(1 if args.fail_on_findings and report["runs_with_findings"] else 0)


if __name__ == "__main__":
    main()
