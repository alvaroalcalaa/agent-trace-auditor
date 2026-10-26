import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from audit import audit, read_trace, render_html, strict_json, validate_event

ROOT = Path(__file__).parent


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.events = read_trace(ROOT / "examples/demo.jsonl")

    def test_demo_results(self):
        report = audit(self.events, max_calls=3)
        self.assertEqual((report["events"], report["runs"], report["runs_with_findings"]), (6, 2, 1))
        healthy, loop = report["results"]
        self.assertEqual(healthy["status"], "ok")
        self.assertEqual(loop["summed_tool_duration_ms"], 195)
        self.assertEqual({f["type"] for f in loop["findings"]},
                         {"call_budget", "repeated_call", "tool_errors"})

    def test_arguments_order_does_not_hide_repeat(self):
        events = copy.deepcopy(self.events[2:])
        events[0]["arguments"] = {"limit": 5, "query": "missing-map"}
        findings = audit(events)["results"][0]["findings"]
        repeated = next(f for f in findings if f["type"] == "repeated_call")
        self.assertEqual(repeated["count"], 4)

    def test_different_arguments_are_not_same_call(self):
        events = copy.deepcopy(self.events[2:])
        for i, event in enumerate(events):
            event["arguments"] = {"query": str(i)}
        self.assertFalse(any(f["type"] == "repeated_call"
                             for f in audit(events)["results"][0]["findings"]))

    def test_repetitions_do_not_cross_runs(self):
        events = copy.deepcopy(self.events[2:])
        for i, event in enumerate(events):
            event["run_id"] = str(i)
        self.assertFalse(any(f["type"] == "repeated_call"
                             for r in audit(events)["results"] for f in r["findings"]))

    def test_budget_boundary(self):
        report = audit(self.events[:2], max_calls=2)
        self.assertEqual(report["runs_with_findings"], 0)

    def test_empty_trace(self):
        report = audit([])
        self.assertEqual((report["events"], report["runs"]), (0, 0))

    def test_arguments_not_exported(self):
        events = copy.deepcopy(self.events[2:])
        for e in events:
            e["arguments"] = {"secret": "PRIVATE_VALUE"}
        report = audit(events)
        self.assertNotIn("PRIVATE_VALUE", json.dumps(report))
        self.assertNotIn("PRIVATE_VALUE", render_html(report))

    def test_html_escapes_identifiers(self):
        events = copy.deepcopy(self.events[:1])
        events[0]["run_id"] = "<script>alert(1)</script>"
        rendered = render_html(audit(events))
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_invalid_events(self):
        for change in [{"duration_ms": -1}, {"duration_ms": float("inf")},
                       {"duration_ms": True}, {"status": "pending"}, {"arguments": []},
                       {"event_id": " "}, {"run_id": "x" * 121}]:
            event = {**self.events[0], **change}
            with self.assertRaises(ValueError):
                validate_event(event)

    def test_duplicate_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicado"):
            audit([self.events[0], self.events[0]])

    def test_strict_json(self):
        for text in ['{"x":1,"x":2}', '{"x":NaN}']:
            with self.assertRaises(ValueError):
                strict_json(text)

    def test_reader_error_has_line_number(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.jsonl"
            path.write_text(json.dumps(self.events[0]) + "\nINVALID\n")
            with self.assertRaisesRegex(ValueError, "Línea 2"):
                read_trace(path)

    def test_cli_exports_and_optional_exit_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "report.html"
            command = [sys.executable, str(ROOT / "audit.py"), str(ROOT / "examples/demo.jsonl"),
                       "--max-calls", "3", "--html", str(out)]
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["runs_with_findings"], 1)
            self.assertIn("retry-loop", out.read_text())
            failed = subprocess.run(command + ["--fail-on-findings"], capture_output=True)
            self.assertEqual(failed.returncode, 1)

    def test_cli_protects_source(self):
        source = ROOT / "examples/demo.jsonl"
        before = source.read_bytes()
        run = subprocess.run([sys.executable, str(ROOT / "audit.py"), str(source),
                              "--json", str(source)], capture_output=True)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
