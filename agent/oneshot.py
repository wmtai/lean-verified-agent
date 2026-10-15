"""Exercise 5 learner task 2: connect one generation to one acceptance check."""

from agent.acceptance import AcceptanceResult
from agent.prompts import build_generation_prompt
from agent.task_view import AgentTask
from agent.generation import OneShotSession


def run_one_shot(task: AgentTask, session: OneShotSession) -> AcceptanceResult:
    """Build prompt -> generate -> parse -> render -> check, returning the result.

    Use the supplied session methods. Pass reply.text into session.parse.
    No retries, repair loop, fixture reads, or hand-written candidate bodies.
    Expected model/format failures propagate to the supplied run recorder.
    """
    prompt = build_generation_prompt(task)
    reply = session.generate(prompt)
    proposal = session.parse(reply.text)
    source = session.render(proposal)
    rtn = session.check(source)

    return rtn
