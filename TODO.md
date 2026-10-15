# Guided project progress

The design is [docs/project-brief.md](docs/project-brief.md); the
[roadmap](docs/roadmap.md) states the learner work and supplied support for each
exercise. From Exercise 3 onward, the focus is Lean and agent decisions. System
infrastructure is supplied rather than assigned as implementation homework.

The first **OK** requests review and feedback. After a passing review, another
**OK** advances the course. Required fixes stay on the current exercise.
Written questions and reflection answers are not required. Reviews use
implementations and check results.

**Current exercise: 6 — Passed review; awaiting OK before Exercise 7.**

- [x] Exercise 1: reproducible environment and handwritten checked-subtraction
  solution passed review. Advancement authorized by the learner's next **OK**.
- [x] Exercise 2: task loader/digest, proposal validation, and renderer passed
  review. Advancement authorized by the learner's next **OK**.
- [x] Exercise 3: fixed checked-subtraction proof passed review and all diagnostic
  cases matched their expected outcomes. Written reflection requirement removed
  at the learner's request. Subsequent **OK** authorized Exercise 4.
  The [guide](exercises/03-sandboxed-runner/README.md), bounded process runner,
  Docker policy/lifecycle, log retention, and review command are supplied.
- [x] Exercise 4: repaired `RemoveAxiom.lean`, `FinishHelper.lean`, and
  `RestoreContract.lean`; all three received `VERIFIED` and passed review.
  The [guide](exercises/04-trusted-acceptance/README.md), pinned Comparator/exporter,
  isolated checking stages, policy fixtures, and tests are provided.
- [x] Exercise 5: `build_generation_prompt` and `run_one_shot` passed review;
  all seven learner tests and six replay cases passed. Saved real runs include
  a `VERIFIED` proposal and a failed proof with retained diagnostics. The
  [guide](exercises/05-one-shot-generation/README.md), public task view,
  replay/API adapters, parsing/checking services, CLI, and records are supplied.
- [x] Exercise 6: repair prompt, action decisions, and loop passed review.
  All 17 learner tests and eight replay cases passed. A live proof repair
  reached `VERIFIED` on attempt 2; another live run stopped at its attempt cap.
  Proof-only edits preserved the implementation, and all artifacts were retained. The
  [guide](exercises/06-feedback-repair/README.md), 17 learner tests, deterministic
  sequences, proof-only edit guard, CLI, and retained records are supplied.
- [ ] Exercise 7: write generalized helper invariants and add planning,
  proof-only repair, and implementation redesign decisions.
- [ ] Exercise 8: audit ten development and twenty held-out tasks, their Lean
  contracts, references, permitted libraries, and split provenance.
- [ ] Exercise 9: define matched-budget strategy comparisons and interpret
  repeated results using a supplied experiment runner.
- [ ] Exercise 10: analyze repairs and failures, test one predefined policy
  variation, and write the final report with supplied artifact packaging.

Exercises 1–6 are complete. The Exercise 6 implementation review is recorded in
`runs/exercise06/implementation-review.json`. The next **OK** authorizes preparing
Exercise 7: helper invariants and planning. Later lessons will provide their
infrastructure when reached.
