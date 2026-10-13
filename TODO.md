# Lean Verified Agent TODO

Reviewed on 2026-10-13 against commit `3f3eb6a`.

This backlog covers the Python agent, verifier, trusted Lean audit, all ten task
contracts and reference solutions, replay example, experiments, tests,
documentation, packaging, Docker build, CI, and existing result summaries.
Items marked **confirmed** describe reproduced behavior. **Improvement** and
**research milestone** items extend the current prototype or address documented
limitations; they are not claims that an existing test fails.

Priority: **P1** fixes acceptance, failure handling, or misleading comparisons;
**P2** improves reliability and measurement; **P3** extends the research project
after its prerequisites are ready. Check an item only when its completion
criteria are met.

## Verified baseline

- All 56 tests pass with real Lean integration enabled, using Python 3.14.6 and
  Lean 4.34.1. The ordinary test command skips two integration tests.
- All ten development references pass the initial check and fresh recheck with
  the explicitly selected local backend.
- The recorded repair demo returns `VERIFIED`: two attempts, two replay calls,
  three Lean checks, and one implementation revision.
- `tasks/eval.json` is deliberately empty. Existing saved Docker results show
  successful fixture/demo runs, but this review could not access the Docker
  socket and did not repeat container verification. No live provider was called.
- The engineering workflow is implemented. Held-out performance and a research
  improvement remain unestablished.

## P1 — Acceptance and result integrity

- [x] **T01 — Enforce the expression-only candidate boundary structurally.**
  **Completed on 2026-10-13.** Both fields now travel as escaped string data to
  a trusted Lean command. It parses both as complete terms before constructing
  the fixed declaration syntax. Boundary failures report `policy_rejected`
  and can enter repair; CI runs the reviewed regressions in Docker.
  Validation: all 64 tests passed with local Lean integration; all six boundary
  integration tests, all ten references, and the repair demo passed in the
  rebuilt Docker image. See [validation record](docs/validation.md).
  **Original confirmed issue:** the keyword filter permitted an expression to close its wrapper
  and introduce a harmless extra `simproc`/`simproc_decl` declaration. A review
  probe passed the policy and real Lean compilation, including the trusted
  acceptance marker. The audit traverses dependencies of `candidate` and
  `candidate_correct`, so an unrelated inserted declaration is outside that
  traversal. This establishes a declaration-boundary failure; the probe did
  not establish acceptance of a false theorem. Require each hole to parse as
  exactly one permitted expression, with no trailing command syntax, before
  elaboration. Keep lexical checks as defense in depth and run parsing/checking
  inside the isolated verifier. Adding individual keywords alone does not
  establish this boundary.
  **Completion criteria met:** both holes reject declaration insertion, ordinary local
  helpers/tactics still work, adversarial regressions run with real Lean in
  Docker, and the documentation accurately describes the enforced boundary.
  Implementation: [verifier/acceptance.py](verifier/acceptance.py) lines 120–154;
  [lean/Trusted/Audit.lean](lean/Trusted/Audit.lean) lines 16–34;
  [tests/test_candidate_boundary.py](tests/test_candidate_boundary.py);
  [docs/verification.md](docs/verification.md) lines 9–29.

- [ ] **T02 — Handle malformed model text without escaping the controller.**
  **Confirmed:** deeply nested JSON below the HTTP response-size cap raises an
  uncaught `RecursionError`; lone Unicode surrogates can raise
  `UnicodeEncodeError` during accounting or trace writing. The saved result can
  remain `UNSOLVED_WITHIN_BUDGET` without a failure category, and evaluation can
  stop abruptly. Bound candidate text before decoding, validate its encoding,
  and normalize parser/adapter failures into the appropriate candidate or
  model-error category. Preserve a coherent trace without logging credentials.
  **Done when:** nested JSON and invalid-Unicode fixtures cause no uncaught
  exception, repairable format failures reach the next attempt, and result
  statuses/categories describe what happened.
  Evidence: [agent/schema.py](agent/schema.py) line 55;
  [agent/controller.py](agent/controller.py) lines 139, 156, 197;
  [agent/model_client.py](agent/model_client.py) line 138.

- [ ] **T03 — Separate candidate resource exhaustion from infrastructure errors.**
  **Confirmed:** a candidate verification timeout immediately ends repair with
  `ERROR`, even when total run time, model calls, and Lean checks remain. Both
  `timeout` and `resource_limit` are classified as infrastructure failures.
  Introduce distinct outcomes for candidate exhaustion, total deadline
  exhaustion, and verifier preparation/launch failures. Permit another
  candidate when the remaining budgets allow it; otherwise finish as
  `UNSOLVED_WITHIN_BUDGET` for search exhaustion.
  **Done when:** a timed-out candidate can be followed by a verified repair,
  an exhausted total deadline makes no further calls, and actual Docker or
  toolchain failures still produce `ERROR`. Retain correct check accounting.
  Evidence: [agent/repair.py](agent/repair.py) lines 6–9;
  [agent/controller.py](agent/controller.py) line 265;
  [verifier/lean_runner.py](verifier/lean_runner.py) lines 199–204.

- [ ] **T04 — Validate completeness and comparability before reporting experiments.**
  **Confirmed:** analysis ignores `experiment.json` and groups recursively
  discovered results solely by strategy. A manifest expecting eight runs with
  only one saved success produced a 100% solve rate without an incomplete-run
  warning, despite mismatched provenance. Validate the expected
  task × strategy × repetition matrix, identify missing/duplicate runs, and
  check task hashes, models/providers, budgets, and verifier settings. For
  standalone traces, retain an explicit exploratory-analysis mode that does
  not imply a controlled comparison. Keep saved `ERROR` and unsuccessful runs
  in the denominator; report missing runs separately.
  **Done when:** incomplete or incompatible experiments cannot silently yield
  a complete comparison, and regression tests cover coverage and provenance
  mismatches as well as existing failure-denominator behavior.
  Evidence: [experiments/analyze.py](experiments/analyze.py) lines 13–19, 28–42;
  [docs/experiments.md](docs/experiments.md) lines 21–26.

## P2 — Controller, provider, and input reliability

- [ ] **T05 — Preflight planning before spending a model call.**
  **Confirmed:** planning runs before the two-check feasibility test; with
  `max_lean_checks=1`, it spends a call although acceptance is impossible.
  A single-call planning budget likewise cannot include generation. Check
  these minimum requirements before requesting a plan and record a precise
  stop reason.
  **Done when:** impossible configurations make zero model calls, while usable
  plans retain their existing call/token/time accounting. Update the test that
  currently permits spending the only call on a plan.
  Evidence: [agent/controller.py](agent/controller.py) lines 166–175;
  [tests/test_controller.py](tests/test_controller.py) lines 100–103.

- [ ] **T06 — Validate task JSON shape and field types.**
  **Confirmed:** a top-level JSON array escapes the CLI as `AttributeError`;
  a string-valued `constraints` field silently becomes individual characters.
  Validate required strings, object shape, and arrays of strings for constraints
  and forbidden identifiers. Return actionable `ValueError` messages.
  **Done when:** malformed task files produce a concise CLI error and exit 2,
  scalar strings cannot replace arrays, and existing task digests stay stable.
  Evidence: [agent/schema.py](agent/schema.py) lines 24–36;
  [agent/cli.py](agent/cli.py) line 162.

- [ ] **T07 — Validate integer budget limits in the Python API.**
  **Confirmed:** `Budget(max_calls=float("nan"))` succeeds; fractional and
  infinite count limits also pass. Require positive, nonboolean integers for
  calls, checks, tokens, and output tokens, plus a positive finite real time
  limit. Apply compatible validation at model request boundaries.
  **Done when:** NaN, infinity, fractions, and booleans are rejected for count
  limits before a model call or run directory is created. Normal CLI values
  continue to work.
  Evidence: [agent/schema.py](agent/schema.py) lines 83–95;
  [agent/model_client.py](agent/model_client.py) lines 32–36.

- [ ] **T08 — Make missing-usage accounting explicit and appropriately conservative.**
  **Improvement:** prompt estimates reserve UTF-8 bytes, while missing output
  usage is estimated as bytes divided by four. The latter is not a conservative
  bound for arbitrary Lean text. Choose a documented fallback, such as charging
  the requested output allowance, and distinguish unknown usage from reported
  zero usage if the provider interface permits it.
  **Done when:** missing-usage runs expose their assumptions, cannot silently
  gain search effort through optimistic estimates, and tests cover long or
  Unicode-heavy output without provider usage.
  Evidence: [agent/controller.py](agent/controller.py) lines 32–42, 139–154;
  [agent/model_client.py](agent/model_client.py) lines 141–150.

- [ ] **T09 — Add a total HTTP response deadline.**
  **Improvement:** socket timeouts allow a slowly delivered response to outlast
  the run deadline; this limitation is already documented. Bound transport and
  response reading by remaining wall time. Distinguish a provider transport
  failure from exhaustion of the controller's total deadline. Account for
  verifier cleanup time or document a bounded shutdown grace period.
  **Done when:** a local slow-response fixture terminates within the configured
  allowance, no late candidate is verified, and traces identify the stop cause.
  Evidence: [agent/model_client.py](agent/model_client.py) lines 125–126;
  [verifier/lean_runner.py](verifier/lean_runner.py) lines 165–170;
  [docs/experiments.md](docs/experiments.md) lines 41–43.

## P2 — Verifier and task audits

- [ ] **T10 — Run direct negative audit tests in CI.**
  **Confirmed gap:** the Python CI jobs skip both real-Lean tests. The Lean job
  checks references and the repair demo, but does not execute the direct audit
  tests for unfinished proofs and transitive custom axioms. Run reviewed
  negative fixtures against the trusted module in the Docker job. Extend them
  to unsafe/partial dependencies, wrong theorem shape, and the T01 boundary
  regression where appropriate.
  **Done when:** CI demonstrably runs these cases rather than reporting them
  skipped, and neither a rejected dependency nor a failed fresh recheck can
  produce acceptance.
  Evidence: [.github/workflows/ci.yml](.github/workflows/ci.yml) lines 16, 25–27;
  [tests/test_runner.py](tests/test_runner.py) lines 130–163;
  [lean/Trusted/Audit.lean](lean/Trusted/Audit.lean) lines 18–43.

- [ ] **T11 — Fingerprint the trusted build and record the actual verifier image.**
  **Improvement:** Docker downloads a versioned Lean archive without checking
  an expected checksum, uses a mutable base-image tag, and runs an image tag
  rather than a recorded immutable identity. Pin/check build inputs, record
  the resolved image ID or digest and trusted audit source hash, and identify
  the actual compiler version used. Centralize the repeated Lean version value
  or check all declarations for consistency.
  **Done when:** a changed compiler/archive/audit/image is detected or produces
  distinct provenance, and a run can identify the trusted build it used.
  Evidence: [Dockerfile](Dockerfile) lines 1–12, 20–24;
  [scripts/build-verifier.sh](scripts/build-verifier.sh);
  [verifier/lean_runner.py](verifier/lean_runner.py) lines 22–23, 156;
  [lean/lean-toolchain](lean/lean-toolchain).

- [ ] **T12 — Audit algorithm constraints separately from theorem correctness.**
  **Documented limitation:** lexical identifier restrictions do not enforce
  recursion or prevent equivalent notation/aliases; for example, multiplication
  notation and append notation are not covered by identifier matching alone.
  Choose dependency-based checks, structured implementation restrictions, or
  explicit review for each measured constraint. Record contract acceptance
  and algorithm compliance separately.
  **Done when:** shortcuts that satisfy the theorem but violate the task intent
  are identified, references remain compliant, and reports state which
  constraints are actually enforced.
  Evidence: [verifier/acceptance.py](verifier/acceptance.py) lines 110–116;
  [tasks/doubling/task.json](tasks/doubling/task.json);
  [tasks/list_append/task.json](tasks/list_append/task.json);
  [docs/verification.md](docs/verification.md) lines 23–29.

- [ ] **T13 — Decide whether recursive constant folding belongs in the formal contract.**
  **Task-quality improvement:** the current specification requires semantic
  preservation and folding a direct addition of two literals. A shallow
  top-level transformation can satisfy both while leaving nested literal
  additions unchanged, although the prose asks for folding both children.
  If full recursive folding is required, add an output/normal-form property
  or an explicitly audited algorithm constraint. Version the revised task.
  **Done when:** the intended nested behavior is specified and a shallow
  implementation is rejected by that requirement; the reviewed reference
  still verifies. This is a task-design gap, not a false-proof finding.
  Evidence: [tasks/constant_folding/task.json](tasks/constant_folding/task.json)
  lines 6, 11–12; [docs/tasks.md](docs/tasks.md) lines 19, 39–41.

- [ ] **T14 — Make reference validation available for both task splits.**
  **Confirmed gap:** `check-fixtures` loads only the default development
  manifest. Add a split/all option so newly added evaluation references can
  receive the same audit and fresh recheck. Audit contract non-vacuity,
  preconditions, and representative incorrect candidates when reviewing each
  new task; do not rely solely on one accepted reference.
  **Done when:** every manifest member can be checked explicitly, references
  remain excluded from model prompts, and held-out contracts have recorded
  review and verification results.
  Evidence: [agent/cli.py](agent/cli.py) lines 104–106, 133–135;
  [docs/tasks.md](docs/tasks.md) lines 49–54;
  [tests/test_tasks.py](tests/test_tasks.py).

## P2 — Experiment orchestration and reporting

- [ ] **T15 — Expand and validate experiment provenance.**
  **Confirmed gap:** the manifest omits the requested/resolved model, provider
  endpoint identity, Lean timeout, source revision, trusted source/import
  fingerprints, and completion state. Some of these exist in individual run
  traces. Capture sanitized configuration centrally, link each run to its
  experiment and repetition, and validate consistency using T04/T11.
  **Done when:** the manifest identifies the configuration and trusted build,
  model changes are visible, and credentials never enter saved metadata.
  Evidence: [experiments/evaluate.py](experiments/evaluate.py) lines 25–30;
  [agent/controller.py](agent/controller.py) lines 72–87.

- [ ] **T16 — Preserve token-estimate uncertainty in summaries.**
  **Confirmed gap:** analysis reports `mean_tokens` but drops the controller's
  input/output usage-estimate flags. Report counts or proportions of runs with
  estimated usage and label affected cost metrics; distinguish reported and
  estimated totals where useful.
  **Done when:** JSON and CSV summaries expose missing-usage uncertainty and
  controlled reports cannot present estimates as provider-reported token usage.
  Evidence: [experiments/analyze.py](experiments/analyze.py) lines 28–42;
  [agent/controller.py](agent/controller.py) lines 146–153.

- [ ] **T17 — Test orchestration with offline clients and verifiers.**
  **Confirmed gap:** experiment tests cover aggregation, while the CLI test
  mocks the evaluator itself. Add meaningful `evaluate_tasks` coverage for
  empty splits, bad repetitions, provider preflight, shared budgets, strategy
  deduplication/rotation, independent run directories, and interrupted runs.
  **Done when:** these invariants are checked without live APIs, and an
  orchestration failure cannot silently create a valid-looking comparison.
  Evidence: [tests/test_experiments.py](tests/test_experiments.py);
  [tests/test_cli.py](tests/test_cli.py) line 34;
  [experiments/evaluate.py](experiments/evaluate.py) lines 17–43.

- [ ] **T18 — Support interrupted experiments without overwriting completed runs.**
  **Improvement:** experiment directories must be new, and individual existing
  runs are intentionally protected. Add explicit experiment state, atomic
  manifest/summary updates, and a resume mode that validates the original
  configuration and schedules only missing runs. Define how deliberate reruns
  of infrastructure failures are identified and included.
  **Done when:** interruption/resumption preserves completed artifacts, does
  not duplicate denominators, and T04 accurately reports coverage throughout.
  Evidence: [experiments/evaluate.py](experiments/evaluate.py) lines 24, 30, 43;
  [agent/controller.py](agent/controller.py) lines 61–66, 93–95.

## P3 — Research milestones, in dependency order

- [ ] **T19 — Build the independently audited held-out corpus.**
  **Research milestone:** add the proposed 20–30 genuinely new contracts across
  varied families, including harder invariants, dependent results, and larger
  transformations where supported. Keep development/prompt tuning separate,
  freeze task hashes before comparison, and record reference dependency audits.
  Depends on T12/T14, plus T13 where recursive folding is relevant; this is a
  prerequisite for research claims.
  **Done when:** the evaluation manifest is populated and audited, split
  integrity checks pass, and every evaluation reference passes both checks.
  Evidence: [tasks/eval.json](tasks/eval.json);
  [docs/tasks.md](docs/tasks.md) lines 49–57;
  [docs/project-brief.md](docs/project-brief.md) sections 9 and 12.

- [ ] **T20 — Validate a configured live provider end to end.**
  **Research milestone:** run a small development-only smoke experiment with
  the selected provider/model and default Docker verifier. Verify response
  format, reported token usage, traces, error behavior, and saved artifacts
  before committing to a full benchmark. Record resolved model/version and
  provider configuration using T15. Provider credentials/configuration are
  prerequisites; this review made no live calls.
  **Done when:** the workflow works on real provider responses and accepted
  artifacts can be rechecked from their saved task/candidate data.
  Evidence: [docs/validation.md](docs/validation.md) lines 16–18;
  [README.md](README.md) live model runs.

- [ ] **T21 — Run repeated comparisons under matched budgets.**
  **Research milestone:** compare independent sampling and repair with the same
  model, contracts, imports, verifier, and call/token/time/check caps. Include
  planning costs; retain one-shot as a descriptive baseline. Freeze a run
  protocol with repetitions and a balanced or randomized execution order.
  Depends on T01–T04, T15–T17, T19–T20; T18 is recommended for longer runs.
  **Done when:** complete, provenance-checked experiments retain raw traces,
  report infrastructure failures, and provide a fair feedback comparison.
  Evidence: [docs/experiments.md](docs/experiments.md) lines 9–26;
  [experiments/evaluate.py](experiments/evaluate.py) lines 32–39.

- [ ] **T22 — Add uncertainty and paired outcome analysis.**
  **Research milestone:** extend reports with per-task/category outcomes,
  paired strategy differences, intervals appropriate for repeated task runs,
  and sample sizes. Keep successful-run time separate from all-run time and
  show failure categories and resource tradeoffs. Inspect failed traces without
  treating a failed proof as evidence of an incorrect implementation.
  **Done when:** reports support measured claims with uncertainty and expose
  which contracts and failure types drive the aggregate result.
  Evidence: [experiments/analyze.py](experiments/analyze.py) lines 28–42;
  [docs/experiments.md](docs/experiments.md) lines 28–34, 45–49.

- [ ] **T23 — Implement the proposed repair-action policy and its ablations.**
  **Research milestone:** choose among preserving the implementation and
  repairing its proof, changing the implementation, introducing a local
  invariant, and replanning. Start with a transparent rule-based policy, log
  each decision, and count every policy/model request within the same caps.
  Normalize diagnostic categories so real `unsolved_goals` receives the
  intended proof/invariant guidance. Compare against sampling, unrestricted
  repair, planning, and fixed-action variants after T21/T22.
  **Done when:** decisions and costs are inspectable, implementation-preserving
  actions are enforced, and held-out comparisons quantify any improvement.
  Evidence: [agent/repair.py](agent/repair.py) lines 12–46;
  [agent/controller.py](agent/controller.py) lines 184–188;
  [docs/project-brief.md](docs/project-brief.md) section 11.

- [ ] **T24 — Add structured global helpers when harder tasks require them.**
  **Optional expansion:** the current interface deliberately supports local
  helpers only. Design bounded helper fields with controller-owned declaration
  names/types and audit every helper dependency. Preserve the trusted contract
  and fix T01 before enlarging the candidate surface. Use this to support tasks
  such as insertion sort, then consider curated benchmark imports.
  **Done when:** helpers cannot replace trusted declarations, helper dependencies
  pass the same acceptance rules, and at least one harder audited task works.
  Evidence: [agent/schema.py](agent/schema.py) lines 45–62;
  [verifier/acceptance.py](verifier/acceptance.py) lines 123–140;
  [README.md](README.md) final paragraph.

- [ ] **T25 — Evaluate a separate checker before supporting unrestricted Lean.**
  **Optional expansion:** two fresh elaborations currently use the same
  compiler/kernel. Investigate serialized proof export, comparison with the
  fixed challenge, and an external kernel before allowing unrestricted
  declarations or making stronger adversarial verification claims.
  **Done when:** the additional checker validates the original contract and
  its assumptions independently, and documentation states the exact boundary.
  Evidence: [docs/verification.md](docs/verification.md) lines 38–44.

## P3 — Packaging and reproducible validation

- [ ] **T26 — Exercise installed entry points and keep validation records reproducible.**
  **Improvement:** packaging includes Python modules, while task/Lean assets
  are resolved from the checkout; this is already documented. Add an offline
  installation/CLI smoke check using the documented `--root` path, and decide
  whether a standalone asset-bearing distribution is needed. Save dated
  validation summaries with revision/toolchain/image identity, distinguish
  default skipped tests from full integration, and update the record after
  acceptance changes. Keep generated traces out of version control.
  **Done when:** the supported install workflow works outside the repository,
  and another developer can reproduce the recorded checks and their scope.
  Evidence: [pyproject.toml](pyproject.toml) lines 14–18;
  [agent/cli.py](agent/cli.py) line 17;
  [README.md](README.md) lines 50–60;
  [docs/validation.md](docs/validation.md).

## Commands used for the review baseline

```bash
python3 -m unittest discover -s tests -v
RUN_LEAN_INTEGRATION=1 LEAN_BINARY=/tmp/lean-4.34.1-linux/bin/lean \
  python3 -m unittest discover -s tests -v
LEAN_BINARY=/tmp/lean-4.34.1-linux/bin/lean \
  python3 -m agent check-fixtures --backend local --allow-local \
  --output /tmp/lean-agent-review-fixtures-20261013
LEAN_BINARY=/tmp/lean-4.34.1-linux/bin/lean \
  python3 -m agent demo --backend local --allow-local \
  --output /tmp/lean-agent-review-demo-20261013
python3 -m agent tasks
python3 -m agent tasks --split eval
```

The `/tmp` compiler path and output directories above are specific to this
review environment; choose an installed pinned compiler and fresh output
directories when repeating them. Local runs here used reviewed fixtures.
Use the default Docker backend for live generated candidates.
