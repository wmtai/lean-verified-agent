"""Allowlisted, in-memory agent view; no root paths or reference answers."""

from dataclasses import dataclass

from agent.task import PublicExample, Task


@dataclass(frozen=True)
class AgentTask:
    id: str
    title: str
    implementation_type: str
    implementation_header: str
    theorem_header: str
    specification_source: str
    template_source: str
    permitted_imports: tuple[str, ...]
    public_examples: tuple[PublicExample, ...]
    lean_toolchain: str


def public_task(task: Task) -> AgentTask:
    return AgentTask(**{name: getattr(task, name) for name in AgentTask.__dataclass_fields__})
