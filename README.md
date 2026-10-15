# Fixed-Spec Lean Agent

A guided project in which Python will control the generation, checking, and
repair of Lean implementations and correctness proofs. The formal specification
and acceptance rules remain fixed throughout a run.

**Current exercise: 6 — Repair a proposal using Lean feedback.**
**Exercise 6 passed review; awaiting your next OK before Exercise 7.**
Exercises 1–6 are complete. From Exercise 3 onward, lessons focus on Lean
reasoning and the agent's generation/check/repair decisions. Process management,
Docker isolation, logging, and other system plumbing are supplied implementations.
Follow the
[Exercise 6 guide](exercises/06-feedback-repair/README.md), then say **OK**
when you finish. I will review your implementation and check results and give feedback. After a
passing review, say **OK** again to advance. Each later exercise will add
concepts, worked examples, starter code, and acceptance tests to this same repository.

## Get started

Open
[`agent/repair_prompts.py`](agent/repair_prompts.py).
Implement `build_repair_prompt(task, previous, action)`. Reuse your generation
prompt, add the previous proposal and observed diagnostics, and describe what
may change. A proof-only repair must copy the implementation exactly. First run:

```bash
.venv/bin/python -m scripts.exercise06_review --only prompt
```

Then implement action selection and the repair loop in
[`agent/repair.py`](agent/repair.py), check deterministic sequences, and run the
real model. The focused prompt checks need no API key or Docker. History,
budget guards, transport, parsing, artifact records, and trusted acceptance are
supplied. The guide explains each input and output.
For live calls, fill in `LLM_API_URL`, `LLM_API_KEY`, and `LLM_MODEL` in the
repository `.env`; the adapter loads them automatically. The URL is the full
Responses-compatible endpoint. See [.env.example](.env.example) for the format.
Written questions and reflections are not required in this or later exercises.
Lean checking uses the supplied Docker workers and pinned Comparator checker;
the [Exercise 6 guide](exercises/06-feedback-repair/README.md) includes replay
and live-model configuration. Earlier completed-exercise tests remain available.

Use [`uv`](https://docs.astral.sh/uv/getting-started/installation/) for the Python
environment and either [`elan`](https://github.com/leanprover/elan#installation)
or a standalone installation of the pinned Lean toolchain. The project uses
**Python 3.12.15** and
**Lean 4.34.1**. There are no third-party Python runtime dependencies.

From the repository root:

```bash
uv sync --locked --python 3.12.15
.venv/bin/python -m scripts.check_environment \
  --report runs/exercise01/environment.json
.venv/bin/python -m unittest discover -s tests -v
```

If elan is installed but Lake is not on your `PATH`, select its executable explicitly:

```bash
.venv/bin/python -m scripts.check_environment \
  --lake "$HOME/.elan/bin/lake" \
  --report runs/exercise01/environment.json
```

For a standalone installation, use its actual Lake executable path instead.
`LAKE_BINARY` can also select that Lake executable. To include the real Lean
integration tests:

```bash
RUN_LEAN_INTEGRATION=1 .venv/bin/python -m unittest discover -s tests -v
```

The ordinary test command skips those integration tests. The environment checker
builds the trusted task library and checks the reviewed fixtures. It records the
actual tool versions and observed outcomes in the requested JSON report.

## What Exercise 1 demonstrates

The correct checked-subtraction fixture compiles with its correctness theorem.
The wrong implementation also compiles when checked on its own: it is a
well-typed Lean program. Its attempted proof of the fixed contract fails. These
three outcomes show why compiling an implementation and establishing its
correctness are separate obligations.

This is a development exercise using reviewed files. Sandboxed execution is
introduced in Exercise 3; the trusted final acceptance gate is introduced in
Exercise 4, before model-generated Lean. The environment report records checks;
it does not issue the final agent's `VERIFIED` verdict.

## Project map

| Location | Role now |
| --- | --- |
| `configs/environment.json` | Expected versions and fixture timeout |
| `.python-version`, `pyproject.toml`, `uv.lock` | Python interpreter and dependency configuration |
| `lean-toolchain`, `lakefile.toml`, `lake-manifest.json` | Pinned Lean toolchain and Lake project configuration |
| `tasks/development/checked_subtraction/` | Trusted metadata, specification, and candidate template |
| `exercises/01-environment/fixtures/` | Reviewed examples with contrasting outcomes |
| `exercises/01-environment/starter/Candidate.lean` | Your implementation and proof exercise |
| `agent/task.py`, `agent/proposal.py`, `agent/render.py` | Completed Exercise 2 interfaces |
| `exercises/02-tasks-and-submissions/` | Completed lesson, reviewed proposal, and regression tests |
| `agent/sandbox.py` | Supplied process management, isolated Docker execution, and run records |
| `exercises/03-sandboxed-runner/starter/` | Your proof-repair exercise |
| `exercises/03-sandboxed-runner/` | Completed guide, worker Dockerfile, reviewed probes, and infrastructure regressions |
| `scripts/prepare_exercise03_image.py`, `scripts/exercise03_review.py` | Supplied worker setup and learner review command |
| `agent/acceptance.py`, `verification/` | Supplied pinned Comparator integration, trusted challenge, and fresh-data verification |
| `exercises/04-trusted-acceptance/starter/` | Three Lean acceptance-repair exercises |
| `scripts/prepare_exercise04_checker.py`, `scripts/exercise04_review.py` | Acceptance image setup and focused/all-repairs check commands |
| `agent/prompts.py`, `agent/oneshot.py` | Completed generation prompt and one-shot orchestration |
| `agent/model_client.py`, `agent/generation.py`, `agent/task_view.py` | Supplied replay/API transport, run records, parsing/checking services, and public task view |
| `exercises/05-one-shot-generation/`, `scripts/exercise05_run.py`, `scripts/exercise05_review.py` | Completed one-shot guide, replay responses, learner tests, run CLI, and review checks |
| `agent/repair_prompts.py`, `agent/repair.py` | Current learner tasks: repair prompt, action decisions, and loop |
| `agent/repair_support.py`, `exercises/06-feedback-repair/` | Supplied history, budget guards, replay sequences, current guide, and learner tests |
| `scripts/exercise06_run.py`, `scripts/exercise06_review.py` | Bounded replay/live repair entry point and no-API review command |
| `exercises/progress.json` | Current exercise and review/advancement state |
| `scripts/check_environment.py`, `tests/` | Environment checks and regression tests |
| `runs/` | Generated local reports |

The [roadmap](docs/roadmap.md) distinguishes the ten exercises you complete from
the programming tasks the eventual agent will attempt. The full
[project brief](docs/project-brief.md) defines the final design, including ten
development tasks and twenty held-out evaluation tasks.
The [system implementation](docs/system-implementation.md) lists the supplied
components, their inputs/outputs, and the support added in later lessons.

The earlier implementation was archived at
`/tmp/lean-verified-agent-before-guided-rewrite-20261014-323ded13.tar.gz`; its Git
history remains available at commit `6dca91f`. This rewrite starts the guided
curriculum from its first exercise and extends it cumulatively.
