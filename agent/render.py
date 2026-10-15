"""Substitute two validated bodies into a fixed trusted template."""

import re

from agent.proposal import Proposal
from agent.task import Task


def render_candidate(task: Task, proposal: Proposal) -> str:
    """Return assembled source without changing trusted portions of the task.

    Validate direct objects, indent each body, and replace original placeholders
    in one pass so inserted placeholder-like text stays literal. This function
    does not write files, launch Lean, or issue a verification verdict.
    """
    task.validate_template()
    proposal.validate()

    bodies = {
        name: "\n".join("  " + line for line in body.strip().splitlines())
        for name, body in (
            ("implementation_body", proposal.implementation_body),
            ("proof_body", proposal.proof_body),
        )
    }
    return re.sub(
        r"\{\{(implementation_body|proof_body)\}\}",
        lambda match: bodies[match.group(1)],
        task.template_source,
    )
