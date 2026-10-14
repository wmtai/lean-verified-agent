# Fixed-Spec Lean Agent

A guided project in which Python will control the generation, checking, and
repair of Lean implementations and correctness proofs. The formal specification
and acceptance rules remain fixed throughout a run.

**Current exercise: 1 — Build a reproducible project environment.** This checkout
contains the environment, a trusted checked-subtraction task, reviewed fixtures,
and a learner starter file. Follow the
[Exercise 1 guide](exercises/01-environment/README.md), then say **OK** when you
are ready to advance. Each later exercise will add concepts, worked examples,
starter code, and acceptance tests to this same repository.

## Get started

Use [`uv`](https://docs.astral.sh/uv/getting-started/installation/) for the Python
environment and either [`elan`](https://github.com/leanprover/elan#installation)
or a standalone installation of the pinned Lean toolchain. The project uses
**Python 3.12.15** and
**Lean 4.34.1**. There are no third-party Python runtime dependencies in Exercise 1.

From the repository root:

```bash
uv sync --locked --python 3.12.15
.venv/bin/python -m scripts.check_environment \
  --report runs/exercise01/environment.json
.venv/bin/python -m unittest discover -s tests -v
```

If Lake is not on your `PATH`, select a pinned standalone installation explicitly:

```bash
.venv/bin/python -m scripts.check_environment \
  --lake /path/to/lean-4.34.1-linux/bin/lake \
  --report runs/exercise01/environment.json
```

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
| `lean/` | Pinned toolchain and Lake library configuration |
| `tasks/development/checked_subtraction/` | Trusted metadata, specification, and candidate template |
| `exercises/01-environment/fixtures/` | Reviewed examples with contrasting outcomes |
| `exercises/01-environment/starter/Candidate.lean` | Your implementation and proof exercise |
| `scripts/check_environment.py`, `tests/` | Environment checks and regression tests |
| `runs/` | Generated local reports |

The [roadmap](docs/roadmap.md) distinguishes the ten exercises you complete from
the programming tasks the eventual agent will attempt. The full
[project brief](docs/project-brief.md) defines the final design, including ten
development tasks and twenty held-out evaluation tasks.

The earlier implementation was archived at
`/tmp/lean-verified-agent-before-guided-rewrite-20261014-323ded13.tar.gz`; its Git
history remains available at commit `6dca91f`. This rewrite starts the guided
curriculum at Exercise 1.
