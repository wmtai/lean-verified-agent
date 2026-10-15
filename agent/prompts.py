"""Exercise 5 learner task 1: design the generation prompt."""

from agent.model_client import Prompt
from agent.proposal import DISALLOWED_WORDS, MAX_BODY_BYTES
from agent.task_view import AgentTask


def build_generation_prompt(task: AgentTask) -> Prompt:
    """Return system/user messages using only this public task view.

    Include the actual specification, signature, fixed declaration headers,
    template, toolchain, permitted imports, public examples, and the two-field
    JSON/body contract. Do not include reviewed answers or previous attempts.
    See exercises/05-one-shot-generation/README.md for examples and checks.
    """
    system = (
        "You are a Lean 4 expert. Implement the required function and prove that "
        "it satisfies the supplied formal specification for all inputs.\n"
        "Preserve the fixed signature, declaration names, theorem statement, "
        "trusted specification, and surrounding template. Use only the supplied "
        "permitted imports; do not add imports or top-level declarations.\n"
        "Return only one valid JSON object with exactly two fields: "
        '"implementation_body" and "proof_body". Both values must be nonempty '
        "strings containing Lean bodies only, without declaration headers. "
        "A tactic proof body must begin with by. Encode newlines and quotes "
        "correctly inside JSON strings. Do not return Markdown fences, "
        "explanations, or extra fields.\n"
        f"Each body must be at most {MAX_BODY_BYTES} UTF-8 bytes. "
        "Neither body may contain a # command marker or any of these whole "
        f"words, including inside comments: {', '.join(sorted(DISALLOWED_WORDS))}. "
        "Do not leave unfinished proofs or assume extra axioms. Local let "
        "bindings and proof-local have statements are permitted.\n"
        "Public examples illustrate the task; the proof must establish the "
        "entire formal contract."
    )
    imports = "\n".join(task.permitted_imports)
    examples = "\n".join(
        f"Arguments: {example.arguments} => {example.expected}"
        for example in task.public_examples
    ) or "No public examples supplied."
    user = f"""Task: {task.title}
Task ID: {task.id}
Lean toolchain: {task.lean_toolchain}

Required function type:
{task.implementation_type}

Fixed implementation header:
{task.implementation_header}

Fixed correctness theorem header:
{task.theorem_header}

Trusted specification:
```lean
{task.specification_source}
```

Permitted imports already controlled by the template:
{imports}

Candidate template:
```lean
{task.template_source}
```

Public examples:
{examples}

Generate implementation_body and proof_body to fill the two template holes.
Return only the JSON object described in the system message.
"""
    prompt = Prompt(system=system, user=user)
    prompt.validate()
    return prompt
