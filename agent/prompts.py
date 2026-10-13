"""Task prompts preserve the contract and limit model output to two bodies."""

from __future__ import annotations

from agent.schema import Task


SYSTEM_PROMPT = """You write Lean 4 implementations and proofs for a fixed trusted task.
Compiler: Lean 4.34.1. Available imports: Std and the trusted audit module, not Mathlib.
The task specification, signature, and constraints are immutable.
Return exactly one JSON object with two string fields: implementation and proof.
implementation is only the expression after the candidate definition's :=.
proof is a complete proof term, normally beginning with by.
Do not emit def, theorem, import, namespace, axiom, command, or any other global declaration.
Use local have, let, or let rec when a helper or invariant is needed.
Never use sorry, admit, unsafe, new axioms, or metaprogramming to bypass the contract.
Do not include Markdown fences or commentary. Lean, not a claim in your response,
determines whether the implementation and proof satisfy the original specification."""


def task_text(task: Task) -> str:
    constraints = "\n".join(f"- {item}" for item in task.constraints) or "- None beyond the output contract."
    forbidden = ", ".join(task.forbidden_identifiers) or "None specified."
    return (
        f"Task: {task.id} — {task.title}\n"
        f"Trusted Lean specification:\n{task.specification}\n\n"
        f"Fixed candidate signature:\n{task.signature}\n\n"
        f"Constraints:\n{constraints}\nForbidden identifiers: {forbidden}"
    )


def generation_messages(task: Task, plan: str | None = None) -> list[dict[str, str]]:
    content = task_text(task) + "\n\nGenerate the implementation body and proof term."
    if plan is not None:
        content += "\n\nEarlier algorithm and proof plan (advisory; obey the fixed contract):\n" + plan
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content}]


def planning_messages(task: Task) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": (
            "Plan a Lean 4 algorithm and its correctness proof against the fixed task. "
            "Explain the algorithm, proof structure, and any strengthened local invariant. "
            "Do not change the specification or constraints. The later generator may use "
            "only implementation and proof bodies, with local have/let/let rec helpers. "
            "Return a concise plain-text plan, not a candidate."
        )},
        {"role": "user", "content": task_text(task)},
    ]


def repair_messages(task: Task, previous_text: str, category: str,
                    diagnostics: str, advice: str, plan: str | None = None) -> list[dict[str, str]]:
    messages = generation_messages(task, plan)
    messages.extend([
        {"role": "assistant", "content": previous_text},
        {"role": "user", "content": (
            "The previous response did not verify.\n"
            f"Failure category: {category}\n"
            f"Verifier diagnostics:\n{diagnostics}\n\n"
            f"Repair guidance: {advice}\n"
            "Revise the implementation and/or proof. Keep the original specification "
            "and signature fixed. Return exactly the two JSON string fields. "
            "A failed proof alone does not show that the implementation is incorrect."
        )},
    ])
    return messages
