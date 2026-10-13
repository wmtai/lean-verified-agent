"""A conservative boundary around the two untrusted Lean expression holes.

This lexical gate is defense in depth, not a sandbox or a Lean parser. Lean's
kernel and the trusted dependency audit establish the mathematical contract;
the Docker runner limits the effects of elaboration. Task text is trusted.
"""

from __future__ import annotations

import re
import unicodedata

from agent.schema import Candidate, Task


class PolicyViolation(ValueError):
    """A generated expression exceeds the deliberately narrow allowed surface."""


# Command keywords, code-executing tactics, and known kernel bypass mechanisms.
# Over-rejection is intentional: only ordinary terms and proof tactics are used
# by this initial benchmark. Local helpers use `let rec` or `have`.
FORBIDDEN_TOKENS = frozenset({
    "sorry", "sorryAx", "admit", "axiom", "unsafe", "partial", "opaque",
    "def", "abbrev", "theorem", "lemma", "example", "constant", "constants",
    "inductive", "structure", "class", "instance", "mutual", "namespace",
    "section", "end", "import", "export", "open", "attribute", "initialize",
    "builtin_initialize", "syntax", "macro", "macro_rules", "elab", "elab_rules",
    "declare_syntax_cat", "notation", "infix", "infixl", "infixr", "prefix",
    "postfix", "set_option", "run_tac", "run_elab", "native_decide",
    "variable", "variables", "universe", "universes", "include", "omit",
    "noncomputable", "public", "private", "protected", "scoped", "local",
    "implemented_by", "extern", "eval_expr", "ofReduceBool", "ofReduceNat",
    "trustCompiler", "addDecl", "addAndCompile", "evalConst", "evalExpr",
    "getEnv", "setEnv", "modifyEnv", "withoutModifyingEnv", "command",
    "dbg_trace",
})
FORBIDDEN_NAMESPACES = frozenset({"Lean", "IO", "System", "Meta", "Elab", "Environment"})


def _strip_comments(source: str) -> str:
    """Remove nested Lean comments, retaining whitespace and rejecting literals.

    String/name quotations and escaped identifiers are not needed by the seed
    tasks and would complicate this small lexical policy. Unbalanced comments
    are rejected so they cannot swallow the trusted suffix.
    """
    result: list[str] = []
    index = 0
    depth = 0
    while index < len(source):
        pair = source[index:index + 2]
        if depth:
            if pair == "/-":
                depth += 1
                index += 2
            elif pair == "-/":
                depth -= 1
                index += 2
            else:
                result.append("\n" if source[index] == "\n" else " ")
                index += 1
            continue
        if pair == "/-":
            depth = 1
            result.append(" ")
            index += 2
        elif pair == "--":
            newline = source.find("\n", index)
            if newline < 0:
                result.append(" ")
                break
            result.append("\n")
            index = newline + 1
        elif pair == "-/":
            raise PolicyViolation("Unmatched closing block comment")
        else:
            character = source[index]
            if character in {'"', '`', '«', '»', '#'}:
                raise PolicyViolation("Commands, quotations, strings, and escaped identifiers are disallowed")
            if unicodedata.category(character).startswith("C") and character not in "\n\t\r":
                raise PolicyViolation("Control and formatting characters are disallowed")
            result.append(character)
            index += 1
    if depth:
        raise PolicyViolation("Unclosed block comment")
    return "".join(result)


def _identifiers(source: str) -> set[str]:
    # Unicode letters support standard Lean variables such as α. A dot is kept
    # so `Nat.sorryAx` and qualified forbidden functions cannot hide the token.
    return set(re.findall(r"[^\W\d][\w'.]*", source, flags=re.UNICODE))


def validate_candidate(task: Task, candidate: Candidate) -> None:
    for label, source in (("implementation", candidate.implementation), ("proof", candidate.proof)):
        if not isinstance(source, str) or not source.strip():
            raise PolicyViolation(f"The {label} must be a nonempty expression")
        if len(source.encode("utf-8")) > 32768:
            raise PolicyViolation(f"The {label} exceeds 32 KiB")
        clean = _strip_comments(source)
        names = _identifiers(clean)
        for name in names:
            components = name.split(".")
            if any(part in FORBIDDEN_TOKENS for part in components):
                raise PolicyViolation(f"Disallowed token in {label}: {name}")
            if any(part in FORBIDDEN_NAMESPACES for part in components):
                raise PolicyViolation(f"Metaprogramming namespace in {label}: {name}")
        if label == "implementation":
            # Whitespace around qualification punctuation is normalized too.
            qualified = re.sub(r"\s*\.\s*", ".", clean)
            identifiers = _identifiers(qualified)
            for forbidden in task.forbidden_identifiers:
                if forbidden in identifiers or any(name.endswith("." + forbidden) for name in identifiers):
                    raise PolicyViolation(f"Task forbids implementation identifier: {forbidden}")


def _indent_expression(source: str) -> str:
    return "\n".join("  " + line for line in source.strip().splitlines())


def render_candidate(task: Task, candidate: Candidate, acceptance_token: str) -> str:
    """Build the entire file from the immutable task and two bounded holes."""
    validate_candidate(task, candidate)
    if not re.fullmatch(r"[a-f0-9]{32}", acceptance_token):
        raise ValueError("Acceptance token must be a fresh UUID hex string")
    return (
        "import Std\nimport Trusted.Audit\n\n"
        "set_option maxHeartbeats 400000\n"
        "namespace Generated\n\n"
        + task.specification.strip() + "\n\n"
        + f"def candidate {task.signature.strip()} := (\n"
        + _indent_expression(candidate.implementation) + "\n)\n\n"
        + "theorem candidate_correct : Spec candidate := (\n"
        + _indent_expression(candidate.proof) + "\n)\n\n"
        + "example : Spec candidate := candidate_correct\n\n"
        + "end Generated\n\n"
        + f'#audit_candidate "{acceptance_token}"\n'
    )


def has_acceptance_marker(output: str, token: str) -> bool:
    return f"LEAN_VERIFIED_ACCEPTED:{token}" in output
