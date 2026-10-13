# Validation record

The initial implementation was checked with Python 3.14.6, Lean 4.34.1, and
the provided Docker image.

- All 56 tests passed with real Lean integration enabled, including direct
  audit rejection of unfinished proofs and transitive custom axioms.
- All ten reviewed development references passed the Docker verifier's
  initial audit and fresh recheck.
- The recorded checked-subtraction demo returned `VERIFIED` after two model
  replay calls, two attempts, and three Lean checks. The first attempt failed
  with `unsolved_goals`; the second implementation and proof passed both checks.
- Task listing, empty evaluation handling, trace aggregation, invalid budget
  handling, and whitespace checks passed.

These checks establish the supplied workflow and fixtures, not a held-out
solve rate or improvement over another method. A live commercial model was
not called; configure your provider and credentials for live experiments.

To repeat the direct audit tests on a reviewed local Lean installation:

```bash
RUN_LEAN_INTEGRATION=1 LEAN_BINARY=/path/to/lean python3 -m unittest discover -s tests
```

For the default isolated workflow, run `python3 -m agent check-fixtures` and
`python3 -m agent demo` after building the verifier image.

## T01 expression boundary — 2026-10-13

The working-tree changes following baseline commit `3f3eb6a` were checked with
Python 3.14.6 and the pinned Lean 4.34.1 compiler.

- All 64 tests passed with local Lean integration enabled, including the
  existing direct dependency-audit cases and six new term-boundary tests.
- All six term-boundary integration tests passed in the rebuilt Docker image.
  The tests cover both output fields, trailing command input, parsing both
  fields before elaboration, escaped-data transport, local recursion/invariants,
  and a rejected candidate followed by an accepted repair.
- All ten development references passed both Docker checks.
- The recorded Docker demo returned `VERIFIED` after two attempts, two replay
  calls, and three Lean checks, with the first failure categorized as
  `unsolved_goals`.
- `git diff --check` passed. No live provider was called.

The rebuilt image `lean-verified-agent-verifier:4.34.1` had image ID
`sha256:0d5e1813bd45c71056183a4b7e210342e0476a5f5ea35e73ca30843ef442798c`.
Local Docker fixture/demo records were written to
`/tmp/lean-agent-t01-docker-fixtures` and `/tmp/lean-agent-t01-docker-demo`;
these temporary paths are not portable repository artifacts.

Commands for the full reviewed local test suite and the Docker boundary suite:

```bash
RUN_LEAN_INTEGRATION=1 LEAN_TEST_BACKEND=local LEAN_BINARY=/path/to/lean \
  python3 -m unittest discover -s tests -v
bash scripts/build-verifier.sh
RUN_LEAN_INTEGRATION=1 LEAN_TEST_BACKEND=docker \
  python3 -m unittest discover -s tests -p test_candidate_boundary.py -v
python3 -m agent check-fixtures
python3 -m agent demo
```

The default Python test command skips all eight Lean integration tests.
The CI Docker job explicitly enables the six boundary tests. These checks
establish the structural expression boundary for the tested grammar and
workflow; the compiler/kernel, trusted modules/tasks, and container runtime
remain part of the verification assumptions described in
[verification details](verification.md).
