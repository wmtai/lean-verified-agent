# Supplied system implementation

The learner writes Lean programs/proofs and the agent's generation/repair
decisions. The system implementation supplies execution, transport, limits,
records, and experiment machinery as each exercise reaches them.

## Working interfaces now

| Component | File | Input → output |
| --- | --- | --- |
| Trusted task snapshot | [agent/task.py](../agent/task.py) | Repository root and task ID → immutable metadata, specification, template, and digest. |
| Proposal format | [agent/proposal.py](../agent/proposal.py) | JSON text → two validated implementation/proof body strings. |
| Candidate assembly | [agent/render.py](../agent/render.py) | Task and proposal → Lean source with fixed surrounding declarations. |
| Process management | [agent/sandbox.py](../agent/sandbox.py) | Reviewed command and limits → capped byte diagnostics, exit code, timing, and execution-limit flags. |
| Isolated Lean execution | [agent/sandbox.py](../agent/sandbox.py) | Task, source, and immutable worker image → `LeanRunResult` with retained source/log/report paths. |
| Worker setup | [scripts/prepare_exercise03_image.py](../scripts/prepare_exercise03_image.py) | Installed Lean toolchain and selected trusted files → built image and identity report. |
| Lean feedback lesson | [scripts/exercise03_review.py](../scripts/exercise03_review.py) | Reviewed examples and learner proof → preserved case observations and latest summary. |
| Trusted acceptance | [agent/acceptance.py](../agent/acceptance.py), [verification/](../verification/) | Candidate source → isolated declaration export → fresh Comparator comparison/axiom check/kernel replay → acceptance result and checked artifact. |
| Acceptance lesson | [scripts/exercise04_review.py](../scripts/exercise04_review.py) | Three learner repairs, or separate reviewed rejection fixtures → focused check results and retained reports. |
| Agent-visible task | [agent/task_view.py](../agent/task_view.py) | Trusted task → allowlisted immutable view without paths, metadata, or reference answers. |
| Model transport | [agent/model_client.py](../agent/model_client.py) | Prompt → one replayed or OpenAI Responses API result, visible text, measured/fixture usage, and explicit model status. |
| One-shot services and records | [agent/generation.py](../agent/generation.py) | Learner-controlled sequence of generate/parse/render/check calls → preserved run evidence and classified outcome. |
| Generation lesson | [scripts/exercise05_run.py](../scripts/exercise05_run.py), [scripts/exercise05_review.py](../scripts/exercise05_review.py) | Prompt inspection, explicit replay/live runs, learner/replay checks, and discovery of current-code live evidence. |
| Repair services | [agent/repair_support.py](../agent/repair_support.py) | Ordered frozen observations, current budget state, and a learner-selected action → retained attempt and updated resource observations. |
| Repair lesson | [scripts/exercise06_run.py](../scripts/exercise06_run.py), [scripts/exercise06_review.py](../scripts/exercise06_review.py) | Deterministic sequences or explicit live repair calls → history, limits, failures/success, and review evidence. |

The completed Exercise 2 interfaces remain part of the system. Process and
container internals are now provided implementations, with regression tests.

```python
from pathlib import Path

from agent.proposal import Proposal
from agent.render import render_candidate
from agent.sandbox import DockerLeanRunner, WorkerImage
from agent.task import Task

root = Path.cwd()
task = Task.load(root, "checked_subtraction")
proposal = Proposal.from_json(
    (root / "exercises/02-tasks-and-submissions/fixtures/proposal.json").read_text()
)
source = render_candidate(task, proposal)
image = WorkerImage.load(root / "runs/exercise03/image.json")
result = DockerLeanRunner(image).check(
    task, source, artifact_root=root / "runs/my-checks"
)
print(result.status)
print(result.report_path)
```

For Exercise 3's feedback lesson, use the shorter command:

```bash
.venv/bin/python -m scripts.exercise03_review
```

## Execution and evidence contract

The controller checks the trusted task/image identity, local Docker endpoint,
resource enforcement, and actual compiler version. A fresh worker receives
only a read-only `Candidate.lean` input directory. The image contains the
compiler and selected trusted specification library. It contains no project
reference answers or model credentials.

Defaults are twenty seconds per attached compiler invocation, 512 MiB memory
including swap, one CPU, 64 processes, and 64 KiB combined captured output.
Separate control-command deadlines bound Docker setup and cleanup. Version
measurement and candidate checking use distinct fresh workers.

Each attempt retains:

```text
attempt-<unique identifier>/
    Candidate.lean
    stdout.log
    stderr.log
    result.json
```

The report records source/task/image identity, measured compiler version,
limits, process/container observations, and cleanup evidence. Failed attempts
remain available after later successful runs. Infrastructure failure produces
an explicit status; candidates are never run through a host Lean fallback.

`ELABORATED` and `ELABORATION_FAILED` are compiler observations. They do not
replace the later trusted challenge–solution acceptance decision. The
Exercise 3 review command saves observations and leaves lesson completion
pending review of the learner's implementation and check results. Written Q&A
and reflection answers are not required.

Exercise 4's supplied acceptance checker uses an immutable image containing
pinned Comparator/exporter tools. Its export and verification stages have
separate fresh containers. The verifier imports no candidate source or olean;
it checks serialized data against the sealed challenge and returns `VERIFIED`
only after statement/dependency comparison, permitted-axiom checks and kernel
replay. Execution examples provide an additional computability/interface check.
See the [Exercise 4 guide](../exercises/04-trusted-acceptance/README.md) for the
configured trust assumptions and exact practical tasks.

Exercise 5 supplies `OneShotSession.generate`, `parse`, `render`, and `check`.
The learner builds the prompt from `AgentTask` and connects those operations.
The existing task/renderer/checker remain authoritative. Service guards permit
one model call and at most one check of exactly the rendered proposal. Each run
records the task digest, prompt, response, proposal/source when available,
nested checker reports, model settings, token observations, counters, and elapsed
time. Expected provider/format/checker failures stay distinct. Unknown token
usage is `null`; replay usage is synthetic and explicitly labelled.

The real adapter is standard-library HTTP(S) transport with an explicit model,
strict two-field JSON schema, disabled redirects, bounded response bytes, a
configurable socket-operation timeout, and no automatic retries. Credentials
remain in the controller and are absent from prompts, saved transport settings,
and Lean workers. `scripts.exercise05_review` checks recorded live evidence but
never initiates a provider request. Actual live calls require the explicit
`scripts.exercise05_run --live` command and user-supplied account/model settings.
The shared [agent/config.py](../agent/config.py) loads the repository `.env`
for every live adapter instance: `LLM_API_URL` is the full Responses-compatible
endpoint, `LLM_API_KEY` is the credential, and `LLM_MODEL` is the selected model.
File values override terminal settings without changing the process environment;
the key is excluded from configuration representations and run settings.
Replay does not load credentials. `.env` stays ignored by Git, while
[.env.example](../.env.example) provides a shareable template.

Exercise 6 supplies `RepairSession.history`, `budget`, `attempt`, and `finish`.
Attempts reuse the existing one-shot services. A proof-only action checks exact
implementation-body equality before the Lean checker; violations have their
own status. Attempt/call/submission/check caps prevent further operations.
Token totals and elapsed-time thresholds are observed between operations, so
an already-completed operation can exceed a threshold; overages are recorded
and stop subsequent work. Unknown usage blocks further attempts. Per-worker
limits and transport socket timeouts remain active. See the
[Exercise 6 guide](../exercises/06-feedback-repair/README.md) for these semantics.

An optional earlier failed-proof seed is validated, snapshotted, and charged
to the new budget. Reports distinguish seeded and new model/provider calls and
label mixed fixture/provider token observations. Seed evidence alone does not
complete the new live-run requirement. The three learner holes are repair
prompt content, action selection, and loop control; no system plumbing is homework.

## Support supplied in later exercises

| Exercise | System implementation supplied | Learner work |
| --- | --- | --- |
| 7 | Helper assembly/checking, planning-call accounting, and expanded action records. | Implement planning decisions and useful helper invariants. |
| 8–10 | Task packaging, reference-check commands, experiment persistence/aggregation, and release tools. | Audit Lean contracts, compare agent policies, and analyze evidence. |

These later services are planned and are provided when the course reaches their
exercise. Exercises 1–5 passed review. Exercise 6's system support is implemented;
its repair prompt, action selector, and loop are the current learner starter
tasks. Helper/planning support and experiment execution remain later exercises.
