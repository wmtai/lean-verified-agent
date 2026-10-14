# Exercise 1 validation — 2026-10-14

The new guided project was checked with Python **3.12.15**, Lean **4.34.1**,
and Lake **5.0.0-src+5045d00**. Python has no third-party runtime dependencies;
the Lake manifest has no external packages.

The Python environment was synchronized from `uv.lock` using the installed,
pinned interpreter. The environment checker built the trusted task library and
recorded all three expected observations:

| Fixture | Lean exit code | Observation |
| --- | --- | --- |
| `Correct.lean` | 0 | The theorem elaborated; executions printed `none` and `some 5`. |
| `WrongImplementation.lean` | 0 | The well-typed function printed `some 0` on underflow. |
| `WrongProof.lean` | 1 | The fixed correctness theorem had an unsolved underflow goal. |

All **15 tests** passed with real Lean integration enabled: fourteen offline
tests plus one integration test of the pinned environment and reviewed fixtures.
The starter intentionally retains two `sorry` holes for the learner. These
fixture checks do not complete that handwritten exercise or advance the course.

Commands used from the repository root:

```bash
uv --cache-dir /tmp/fixed-spec-lean-agent-uv-cache sync \
  --locked --offline --python 3.12.15
.venv/bin/python -m scripts.check_environment \
  --lake /tmp/lean-4.34.1-linux/bin/lake \
  --report runs/exercise01/environment.json
RUN_LEAN_INTEGRATION=1 LAKE_BINARY=/tmp/lean-4.34.1-linux/bin/lake \
  .venv/bin/python -m unittest discover -s tests -v
```

The `/tmp` paths are specific to this development environment. Use your installed
pinned Lake and the normal `uv sync --locked` command on another machine.
The generated report records actual versions, fixture diagnostics, and SHA-256
hashes of the configuration, lockfiles, task specification, and reviewed fixtures.

The earlier implementation is preserved in Git at `6dca91f` and in the local
archive `/tmp/lean-verified-agent-before-guided-rewrite-20261014-323ded13.tar.gz`.
The old source files and generated results were removed from this checkout.
CI has been configured for the new exercise; hosted CI was not run here.

No model was called. These are local checks of reviewed educational code.
Sandboxing and final challenge–solution acceptance remain Exercises 3 and 4;
this exercise makes no final-agent `VERIFIED` claim.
