from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from agent.schema import RunResult
from experiments.analyze import analyze_results


class AnalysisTests(unittest.TestCase):
    def test_failures_and_errors_remain_in_solve_rate_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, status in enumerate(("VERIFIED", "UNSOLVED_WITHIN_BUDGET", "ERROR")):
                run = root / str(index)
                run.mkdir()
                row = RunResult(task_id=str(index), strategy="repair", status=status,
                                llm_calls=2, lean_checks=3, input_tokens=10,
                                output_tokens=20, elapsed_seconds=6,
                                failure_categories={"unsolved_goals": 1})
                (run / "result.json").write_text(json.dumps(asdict(row)))
            summary = analyze_results(root, root / "summary.csv")[0]
            self.assertAlmostEqual(summary["solve_rate"], 1 / 3)
            self.assertEqual(summary["error_runs"], 1)
            self.assertEqual(summary["mean_tokens"], 30)
            self.assertEqual(summary["failure_categories"], {"unsolved_goals": 3})
            self.assertTrue((root / "summary.csv").exists())

    def test_no_success_does_not_invent_time_to_solution(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "result.json"
            source.write_text(json.dumps(asdict(RunResult("x", "sampling", "ERROR"))))
            row = analyze_results(source)[0]
            self.assertIsNone(row["mean_seconds_to_verified"])
            self.assertEqual(row["solve_rate"], 0)

    def test_empty_or_unknown_results_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "No result"):
                analyze_results(root)
            (root / "result.json").write_text('{"strategy":"repair","status":"CLAIMED"}')
            with self.assertRaisesRegex(ValueError, "Unrecognized"):
                analyze_results(root)


if __name__ == "__main__":
    unittest.main()
