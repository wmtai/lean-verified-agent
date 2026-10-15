"""Run a bounded repair sequence with replay or explicit live .env settings."""

import argparse
from pathlib import Path

from agent.model_client import OpenAIResponsesModel
from agent.repair_support import BudgetLimits, SequenceReplay, execute_repair


ROOT = Path(__file__).resolve().parents[1]
LESSON = ROOT / "exercises/06-feedback-repair"
SCENARIOS = {
    "proof_then_valid": ("proof_error", "valid", "provider_error"),
    "format_then_valid": ("malformed", "valid", "provider_error"),
    "always_bad": ("proof_error", "proof_error", "proof_error", "valid"),
    "provider_failure": ("provider_error", "valid"),
    "refusal": ("refusal", "valid"),
    "incomplete_then_valid": ("incomplete", "valid", "provider_error"),
    "scope_violation": ("proof_error", "changed_implementation", "valid"),
    "already_valid": ("valid", "provider_error"),
}


def replay_model(name):
    return SequenceReplay([
        (LESSON / "fixtures" if item == "changed_implementation"
         else ROOT / "exercises/05-one-shot-generation/fixtures") / (item + ".json")
        for item in SCENARIOS[name]
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replay", choices=SCENARIOS)
    mode.add_argument("--live", action="store_true", help="Make live API requests using .env")
    parser.add_argument("--seed-run", type=Path, help="Previously saved failed-proof result.json; its costs count")
    parser.add_argument("--model", help="Override LLM_MODEL in .env")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-model-calls", type=int, default=3)
    parser.add_argument("--max-checks", type=int, default=3)
    parser.add_argument("--max-submissions", type=int, default=3)
    parser.add_argument("--max-total-tokens", type=int, default=32768)
    parser.add_argument("--wall-seconds", type=float, default=600)
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    args = parser.parse_args(argv)
    try:
        limits = BudgetLimits(args.max_attempts, args.max_model_calls, args.max_submissions,
                              args.max_checks, args.max_total_tokens, args.wall_seconds)
        model = replay_model(args.replay) if args.replay else OpenAIResponsesModel(
            args.model, max_output_tokens=args.max_output_tokens)
    except ValueError as error:
        parser.error(str(error))
    result = execute_repair(ROOT, model, limits=limits, seed_run=args.seed_run)
    print(f"Outcome: {result.status}")
    print(f"Report: {result.report_path}")
    return 0 if result.status == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
