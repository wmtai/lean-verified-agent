"""Assemble the reviewed Exercise 2 proposal once the learner code is complete.

This command writes source only. It does not call a model or execute Lean.
"""

from pathlib import Path
import sys

from agent.proposal import Proposal
from agent.render import render_candidate
from agent.task import Task


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    try:
        task = Task.load(ROOT, "checked_subtraction")
        path = ROOT / "exercises/02-tasks-and-submissions/fixtures/proposal.json"
        proposal = Proposal.from_json(path.read_text(encoding="utf-8"))
        source = render_candidate(task, proposal)
        digest = task.digest
        output = ROOT / "runs/exercise02/Candidate.lean"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(source, encoding="utf-8")
    except (NotImplementedError, ValueError, OSError) as error:
        print(f"Exercise 2 assembly is incomplete or rejected: {error}", file=sys.stderr)
        return 1
    print(f"Task snapshot: {digest}")
    print(f"Assembled source: {output}")
    print("Source assembled; Lean checking and final acceptance are separate steps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
