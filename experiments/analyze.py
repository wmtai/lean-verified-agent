"""Summarize saved outcomes without dropping unsuccessful or error runs."""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
from statistics import mean


def analyze_results(path: Path, csv_path: Path | None = None) -> list[dict]:
    paths = [path] if path.is_file() else sorted(path.rglob("result.json"))
    groups: dict[str, list[dict]] = defaultdict(list)
    for source in paths:
        row = json.loads(source.read_text(encoding="utf-8"))
        if row.get("status") not in {"VERIFIED", "UNSOLVED_WITHIN_BUDGET", "ERROR"}:
            raise ValueError(f"Unrecognized run status in {source}")
        groups[row["strategy"]].append(row)
    if not groups:
        raise ValueError("No result.json traces found")
    summaries = []
    for strategy, rows in sorted(groups.items()):
        failures: Counter = Counter()
        for row in rows:
            failures.update(row.get("failure_categories", {}))
        verified = [row for row in rows if row["status"] == "VERIFIED"]
        summaries.append({
            "strategy": strategy, "runs": len(rows),
            "tasks": len({row["task_id"] for row in rows}),
            "verified_runs": len(verified), "solve_rate": len(verified) / len(rows),
            "error_runs": sum(row["status"] == "ERROR" for row in rows),
            "mean_llm_calls": mean(row["llm_calls"] for row in rows),
            "mean_lean_checks": mean(row["lean_checks"] for row in rows),
            "mean_tokens": mean(row["input_tokens"] + row["output_tokens"] for row in rows),
            "mean_seconds": mean(row["elapsed_seconds"] for row in rows),
            "mean_seconds_to_verified": mean(row["elapsed_seconds"] for row in verified)
                if verified else None,
            "implementation_revisions": sum(row["implementation_revisions"] for row in rows),
            "proof_revisions": sum(row["proof_revisions"] for row in rows),
            "failure_categories": dict(failures),
        })
    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
            writer.writeheader()
            writer.writerows({**row, "failure_categories": json.dumps(row["failure_categories"])}
                             for row in summaries)
    return summaries


if __name__ == "__main__":
    from agent.cli import main
    import sys
    raise SystemExit(main(["analyze", *sys.argv[1:]]))
