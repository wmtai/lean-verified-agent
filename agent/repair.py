"""Conservative, diagnostic-based repair hints; no invented counterexamples."""

from __future__ import annotations


INFRASTRUCTURE_CATEGORIES = frozenset({
    "infrastructure_error", "infrastructure", "runner_error", "environment_error",
    "toolchain_error", "sandbox_error", "backend_error", "timeout", "resource_limit",
})


def categorize_failure(category: str, diagnostics: str) -> str:
    """Use explicit verifier categories, refining generic Lean errors only."""
    if category and category not in {"lean_error", "verification_failed", "unknown"}:
        return category
    lowered = diagnostics.lower()
    if any(fragment in lowered for fragment in ("unsolved goals", "tactic '")):
        return "proof_incomplete"
    if any(fragment in lowered for fragment in ("type mismatch", "application type mismatch")):
        return "type_error"
    if any(fragment in lowered for fragment in ("unknown identifier", "unknown constant")):
        return "unknown_identifier"
    if any(fragment in lowered for fragment in ("unexpected token", "expected token", "expected term")):
        return "syntax_error"
    if "termination" in lowered:
        return "termination_error"
    return category or "lean_error"


def repair_advice(category: str, diagnostics: str = "") -> str:
    if category == "invalid_json":
        return "Fix the output format: valid JSON with exactly implementation and proof, both nonempty strings."
    if category == "proof_incomplete":
        return (
            "Inspect the remaining proof obligations. Try a suitable case split, induction, "
            "or a strengthened local invariant. Decide whether the implementation needs "
            "a change only after examining the fixed specification; no counterexample "
            "has been established by this diagnostic."
        )
    if category == "termination_error":
        return "Use structurally decreasing recursion and make the decrease visible to Lean."
    if category in {"type_error", "syntax_error", "unknown_identifier"}:
        return "Repair the reported elaboration or syntax issue using declarations available in the trusted imports."
    if category in {"policy_rejected", "acceptance_rejected", "forbidden_syntax", "forbidden_identifier"}:
        return "Remove the reported forbidden construct and satisfy the original contract with an ordinary Lean term."
    return "Use the reported Lean diagnostics to revise the term or proof; the diagnosis does not establish an incorrect implementation."
