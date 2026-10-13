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
