"""Exercise 6 tasks 2–3: decide the next action and connect the repair loop."""

from agent.prompts import build_generation_prompt
from agent.repair_prompts import build_repair_prompt
from agent.repair_support import (Attempt, BudgetState, RepairAction, RepairOutcome,
                                  RepairSession, REGENERATE_STATUSES, TERMINAL_ERRORS)
from agent.task_view import AgentTask


def choose_action(history: tuple[Attempt, ...], budget: BudgetState) -> RepairAction:
    """Use the decision table in the guide, including success/error/budget stops."""
    if not budget.can_attempt:
        return RepairAction.STOP
    if not history:
        return RepairAction.GENERATE

    latest = history[-1]
    if latest.status in TERMINAL_ERRORS or latest.status in {"VERIFIED", "BUDGET_EXHAUSTED"}:
        return RepairAction.STOP
    if latest.status == "ELABORATION_FAILED":
        if latest.behavioral_counterexample or latest.proposal is None:
            return RepairAction.REGENERATE
        return RepairAction.REPAIR_PROOF
    if latest.status in REGENERATE_STATUSES:
        return RepairAction.REGENERATE
    return RepairAction.STOP


def run_repair(task: AgentTask, session: RepairSession) -> RepairOutcome:
    """Choose action -> build generation/repair prompt -> session.attempt, repeat.

    Read session.history and session.budget each iteration. STOP must return
    session.finish(). Limits, records, model calls, parsing, and checking are
    supplied services. Never catch failures to invent a successful result.
    """
    while True:
        action = choose_action(session.history, session.budget)
        if action == RepairAction.STOP:
            return session.finish()
        if action == RepairAction.GENERATE:
            prompt = build_generation_prompt(task)
        else:
            prompt = build_repair_prompt(task, session.history[-1], action)
        session.attempt(prompt, action)
