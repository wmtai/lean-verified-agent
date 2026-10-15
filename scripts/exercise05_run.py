"""Supplied entry point: inspect a prompt, replay a response, or call a model."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from agent.generation import execute_one_shot
from agent.model_client import OpenAIResponsesModel, ReplayModel
from agent.task import Task
from agent.task_view import public_task


ROOT = Path(__file__).resolve().parents[1]
LESSON = ROOT / "exercises/05-one-shot-generation"
REPLAYS = ("valid", "proof_error", "malformed", "refusal", "incomplete", "provider_error")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prompt-only", action="store_true", help="Save your prompt; no model/checker")
    mode.add_argument("--replay", choices=REPLAYS, help="Use a supplied provider-response fixture")
    mode.add_argument("--live", action="store_true", help="Make one real OpenAI API request")
    parser.add_argument("--model", help="Override LLM_MODEL from the repository .env")
    parser.add_argument("--max-output-tokens", type=int, default=8192)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--task", default="checked_subtraction")
    parser.add_argument("--artifact-root", type=Path, default=ROOT / "runs/exercise05/attempts")
    args = parser.parse_args(argv)
    if args.prompt_only:
        from agent.prompts import build_generation_prompt
        try:
            prompt = build_generation_prompt(public_task(Task.load(ROOT, args.task)))
            prompt.validate()
        except (ValueError, NotImplementedError) as error:
            print(f"Prompt not ready: {error}")
            return 1
        output = ROOT / "runs/exercise05/prompt.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(asdict(prompt), indent=2, ensure_ascii=False) + "\n")
        print(f"Prompt: {output}")
        return 0
    try:
        model = (ReplayModel(LESSON / "fixtures" / (args.replay + ".json")) if args.replay
                 else OpenAIResponsesModel(args.model, max_output_tokens=args.max_output_tokens,
                                           timeout_seconds=args.timeout_seconds))
    except ValueError as error:
        parser.error(str(error))
    result = execute_one_shot(ROOT, model, task_id=args.task, artifact_root=args.artifact_root)
    print(f"Outcome: {result.status}")
    print(f"Report: {result.report_path}")
    if result.status == "EXERCISE_INCOMPLETE":
        print("Complete agent/prompts.py and agent/oneshot.py, then rerun.")
    return 0 if result.status == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
