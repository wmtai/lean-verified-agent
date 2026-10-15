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
tests plus one integration test of the pinned environment, reviewed fixtures,
and Lake's editor setup for the learner file.
The supplied starter initially contained two `sorry` holes for the learner.
Fixture checks alone do not complete that handwritten exercise or advance the course.

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

The Lake configuration, dependency manifest, and toolchain pin now live in the
repository root. This fixes editor discovery for Lean files in `tasks/` and
`exercises/`; the previous nested `lean/` configuration was available only to
commands that explicitly selected that directory. The integration test checks
that the learner file belongs to the root project and that `lake setup-file`
resolves its task import to the built `.olean` artifact.

The learner's completed Exercise 1 implementation was subsequently reviewed.
It elaborated without errors or warnings; its proof depended only on `propext`,
with no unfinished proof dependency. Execution checks covered zero, equality,
valid subtraction, and underflow, and all fifteen tests passed again with real
Lean integration. The review is recorded in `runs/exercise01/review.json`.
Exercise 1 passed review, and the learner's subsequent **OK** authorized
Exercise 2. The reviewed learner source remains unchanged.

## Exercise 2 preparation

Exercise 2 supplies three Python starter modules with six unimplemented methods
or functions, a reviewed JSON proposal, a two-region trusted template, a wiring
script, and twenty-three acceptance test methods with additional input subcases.
The new suite was collected and run: all reported errors came from the intended
`NotImplementedError` starter holes. This is not a claim that the learner's
Exercise 2 implementation passes; that implementation is still to be written.

The reviewed proposal was mechanically inserted into the supplied template in
a temporary instructor check. The resulting Lean source elaborated successfully
with the pinned compiler. All fifteen earlier regression tests still passed
with real Lean integration enabled. The new modules and test file also passed
Python syntax compilation, and local documentation links were checked.

The existing CI job runs completed-exercise regressions. The deliberately
unfinished Exercise 2 suite is separate and is run using the command in its
[guide](../exercises/02-tasks-and-submissions/README.md).

## Exercise 2 review

The completed task loader, proposal validator, and renderer passed review.
All twenty-three Exercise 2 acceptance tests and all fifteen Exercise 1
regression tests passed, including real Lean integration. The demo assembled
the reviewed proposal, and the resulting `runs/exercise02/Candidate.lean`
elaborated with exit code zero and no diagnostics.

The renderer validates direct objects and substitutes the two original
placeholders in one pass, preserving inserted placeholder-like text. Task
snapshots are immutable and their digest tracks loaded metadata and sources.
These checks satisfy the introductory interfaces and assembly exercise;
sandboxing and final challenge–solution acceptance remain later exercises.
The review and source hashes are recorded in `runs/exercise02/review.json`.
After this review, the user's subsequent **ok** authorized Exercise 3.

## Exercise 3 preparation — original infrastructure assignment

The next lesson supplies five runner holes in `agent/sandbox.py`, frozen result
records, configuration validation, reviewed sandbox probes, a filtered worker
image builder, and a demo. The lesson starts with bounded process management.
Offline acceptance tests exercise subprocess behavior and mocked Docker
lifecycle/records; five opt-in integration tests exercise the actual worker.
At that stage, the learner runner still had unimplemented starter holes.

The supplied setup checks passed: all twenty root regression/setup tests and
all twenty-three completed Exercise 2 tests passed. The five new setup tests
check worker image identities, resource configuration, container-state parsing,
and exclusion of protected project files from the build context.

The local rootless Docker daemon supports the required Linux cgroup controls.
The filtered image was built successfully using the installed toolchain and
four allowlisted trusted files. A separate instructor smoke check, using only
reviewed fixtures in restricted containers, confirmed the actual Lean version
4.34.1, successful elaboration, syntax/proof diagnostics, timeout removal, and
the IO isolation probe. The probe checked a fake host environment secret,
protected host canary, denied protected writes, effective memory/process caps,
no-new-privileges, and loopback-only networking. All six smoke observations
passed, and each temporary container was removed.

Image provenance is in `runs/exercise03/image.json`; reviewed image checks are
in `runs/exercise03/image-smoke.json`. These checks validate the supplied setup,
not the then-unimplemented learner runner or final task acceptance. The original
plan required runner acceptance tests before lesson review. That assignment is
superseded by the Lean-focused redesign below.

## Lean and agent-flow redesign — 2026-10-15

The learner requested exercises centered on Lean and agent flow, with system
implementation supplied. The revised roadmap retains ten exercises and the
first-OK review/second-OK advancement protocol. Exercises 1 and 2 remain complete;
Exercise 3 now assigns reading diagnostics, repairing only a Lean proof, and
explaining the repair decision. Process/Docker work is no longer learner homework.

All five system functions are implemented. The runner bounds both byte streams
while reading, terminates process groups, validates a local Docker endpoint and
resource support, selects an immutable image, measures the actual compiler,
uses candidate-only read-only inputs, collects container exit state, removes
workers, and preserves attempt records. Missing/malformed infrastructure cannot
be treated as proof success or trigger a host Lean fallback.

All 47 offline infrastructure tests passed. All five real Docker integration
tests also passed, including protected-file/environment isolation, effective
resource limits, proof/syntax failures, and timeout cleanup. The twenty existing
environment/setup tests passed with real Lean integration; all twenty-three
Exercise 2 tests passed. Four added lesson-wiring tests passed, checking the
fixed-prefix teaching preflight, preserved observations, stopping on an
infrastructure failure, and review remaining pending after successful checks.

The new `scripts.exercise03_review` command was run with real Docker. Reviewed
syntax/proof errors produced `ELABORATION_FAILED`, and the reviewed complete
candidate produced `ELABORATED`. The learner starter produced its intended
unsolved second-branch goal; its proof and reflection remain the learner task.
The latest observation summary is `runs/exercise03/review.json`, with immutable
session summaries and full attempt logs under `runs/exercise03/lean-feedback/`.
These observations do not automatically pass Exercise 3 or issue final acceptance.

The user's partial subprocess implementation and previous assignment documents
were preserved under
`runs/exercise03/previous-system-exercise/20261015T023745Z/` before replacement.

## Exercise 3 review and removal of written Q&A

The learner's repaired proof elaborated, all four diagnostic cases matched
their expected outcomes, and the fixed implementation/theorem prefix was
preserved. The initial review left only the reflection worksheet pending.
The learner then requested skipping question-answering parts in all remaining
exercises. Written Q&A, reflections, and oral explanations are therefore no
longer completion requirements. The reviewed source hash is unchanged.

Exercise 3 now passes review based on its implementation and check results.
The updated review is in `runs/exercise03/implementation-review.json`; the prior
partial review is preserved alongside it. The next **OK** authorizes Exercise 4.

## Exercise 4 preparation — 2026-10-15

The learner's subsequent **OK** authorized Exercise 4. The lesson supplies three
Lean repair files and no written questions. The first replaces a used axiom with
a proved theorem; the second finishes an indirect helper dependency; the third
restores the fixed correctness statement. All three original starters currently
receive the intended `SUBMISSION_REJECTED` result.

The system integrates Comparator revision
`d03acab154d269c06e60e4de7e4cc85deebff94b` and lean4export revision
`076e8e57707e813375e8f9da8bf989799ace9680`. Their upstream toolchain pin is 4.34.0;
the trusted sources were built and tested with the project's actual 4.34.1
compiler. The checked bridge retains upstream comparison, axiom checking, and
kernel replay code, removing only its combined build CLI entry point.

Candidate compilation/export and execution examples run in a restricted Docker
worker. Only bounded serialized proof data reaches a different fresh worker,
which compares against a sealed trusted challenge and replays the environment
into Lean's kernel. No candidate source or olean is imported by the verifier.
Only `propext`, `Quot.sound`, and `Classical.choice` are permitted axiom
dependencies. No independent external kernel is enabled. The checked serialized
environment is retained beside the proposed Lean source; the policy and image
identities bind the trusted task/checker inputs.

All twelve new acceptance support tests passed, including three real Docker
integration tests. The integration cases accepted the complete reviewed proof
and rejected direct/indirect unfinished proofs, a used custom axiom, a changed
theorem, a weakened same-name specification, a missing theorem, a printed fake
verdict, noncomputable code without executable output, and malformed proof data.
The exporter uses its `--ignore-missing` option so missing required declarations
reach Comparator for an explicit rejection rather than causing an exporter
panic. Required declarations remain mandatory in the fresh comparison.

All earlier tests also passed: twenty-four environment/setup/lesson tests,
twenty-three submission tests, and fifty-two sandbox tests including its five
real Docker checks. This is **111 passing support tests** in total. CI includes
offline acceptance regressions; real Docker checks were run locally.

Temporary instructor repairs for all three new learner files received `VERIFIED`
without changing the starter files. The learner still needs to implement those
repairs. Image provenance is in `runs/exercise04/image.json`, initial learner
results in `runs/exercise04/review.json`, and instructor validation in
`runs/exercise04/instructor-repairs.json`. The next review remains pending the
learner's implementation and **OK**.

## Exercise 4 review

The learner completed all three repairs. Each received `VERIFIED` with Lean
4.34.1: compilation and execution examples succeeded, and the separate trusted
Comparator worker accepted the statement/dependencies and kernel replay. The
used axiom was replaced with a proved theorem, the helper proof was completed,
and the third file proved `TaskSpec.CheckedSubSpec candidate`. No fixes remain.
The review and source hashes are in `runs/exercise04/implementation-review.json`.
The learner's subsequent **OK** authorized preparing Exercise 5.

## Exercise 5 preparation — 2026-10-15

Exercise 5 supplies two learner starter functions: the prompt in
`agent/prompts.py` and the one-shot flow in `agent/oneshot.py`. All model/API,
parsing, checking, and record persistence code is supplied. The public task view
excludes metadata/path/reference fields. Generation begins with replay, then
requires an explicit real-model run; no written Q&A is required.

The real adapter uses the Responses API and a strict two-string JSON schema.
It requires a user-selected model and an environment API key, never forwards
credentials to Lean, disables redirect following, caps response bytes, handles
refusal/incomplete/error states, and performs no automatic retries. Its socket
timeout is an operation timeout, not a hard total request deadline. Provider
usage is retained when supplied; missing values remain unknown. Replayed token
counts are explicitly synthetic. The review command only discovers existing
live evidence and never makes a paid call.

All 21 new system support tests passed, covering transport requests and
failures, usage extraction, replay, service sequencing, record preservation,
and separation of model/format/checker outcomes. Combined completed-exercise
regressions passed: 45 root tests including real pinned-Lean integration,
23 submission tests, 47 offline sandbox tests, and 9 offline acceptance tests
for **124 passing regression tests**. The five older Docker sandbox tests and
three acceptance integration tests were not rerun for this generation-only
addition; their earlier successful runs remain documented above.

Temporary in-memory instructor implementations passed all seven new learner
tests without changing either starter source. The complete review path also
ran all six replay cases against the supplied system. The valid response
received `VERIFIED` from the real Docker acceptance checker; the incomplete
proof received `ELABORATION_FAILED`. Malformed JSON, refusal, incomplete output,
and a provider failure stopped before Lean and matched their distinct expected
statuses. Initial starter failures are retained in
`runs/exercise05/scaffold.json`; instructor validation is in
`runs/exercise05/instructor-validation.json`. These are setup checks rather
than learner completion evidence. Local Markdown links were checked.

The real HTTP request/response boundary was tested with mocked provider packets;
**no live API request was made**. Account access, the chosen real model, and a
real saved outcome remain part of the learner's Exercise 5 work. Both learner
functions still raise their intended `NotImplementedError`, and progress waits
for their implementation and review.

## Shared .env model configuration

At the learner's request, the repository now has an ignored `.env` with blank
key/model fields and a shareable `.env.example`. All live adapter instances
load the full endpoint URL, API key, and model through `agent/config.py`.
File values override old terminal exports; the loader does not execute shell
commands, expand variables, mutate the environment, or include keys in its
configuration representation. The existing Responses wire protocol is retained;
custom endpoints must implement that protocol. No live request was made.

Nine configuration tests and the existing 21 model/session support tests passed.
They verify file precedence, literal parsing, invalid input, custom URL/key/model
use in a mocked request, explicit model overrides, omitted credentials in
representations, and credential-free replay. The learner prompt/flow functions
and course progress were not changed by this configuration work.

## Exercise 5 implementation review

The completed prompt and one-shot flow passed implementation review. All seven
learner tests passed, and all six replay outcomes matched their expectations
through the supplied checker. The flow calls prompt construction, generation,
strict parsing, rendering, and checking in order; it returns the checker's own
result and allows expected failures to reach the recorder without retries.

Two saved live runs match the current learner source hashes, task digest, exact
prompt, rendered candidate, and checker source hash. One received `VERIFIED`
after compilation, execution examples, and trusted Comparator/kernel replay.
The other received `ELABORATION_FAILED` with retained failed-rewrite diagnostics.
Each records one model operation, one provider request, one acceptance check,
provider-reported token observations, and immutable artifacts. The accepted
proof emitted deprecated-lemma warnings, which do not require a repair here.
No new live model request was made during review.

The review is recorded in `runs/exercise05/implementation-review.json`.
Exercises 1–5 are complete. The next **OK** authorizes preparing Exercise 6;
no written Q&A is required.

## Exercise 6 preparation — 2026-10-15

The learner's next **OK** authorized Exercise 6. The lesson supplies three
starter functions: `build_repair_prompt`, `choose_action`, and `run_repair`.
The prompt, policy, and loop focus on the fixed Lean task and actual feedback;
history, model calls, parsing, checking, resource observations, replay, and
artifact persistence are provided. There are no written-answer requirements.

The supplied service freezes attempt observations and exposes current budget
state. It rejects an implementation change during a proof-only repair before
invoking Lean. Attempt/model/submission/check counters guard the next operation;
reported token usage and elapsed time are checked between operations. Completed
operations can exceed token/time thresholds, and that overrun is recorded and
stops further work. Unknown usage also stops further work. This implementation
does not claim a prepaid total-token ceiling or hard run-wide wall-clock kill.

An optional failed-proof seed validates the task digest, proposal/source,
checker source hash, operation counts, and elapsed time. It is snapshotted with
provenance, and earlier resource use is charged to the new limits. New and
seeded model/provider calls are separate report fields; mixed replay/provider
token observations are labelled. Original full seed artifacts remain available.

All fourteen new supplied-service tests passed. The complete root suite passed
**68 tests**, including real pinned-Lean environment integration, and all seven
completed Exercise 5 learner tests passed. CI now includes that completed suite.
Earlier sandbox/acceptance sources were retained; the new repair sequences
exercise the existing Docker acceptance checker directly.

Temporary in-memory instructor functions passed all **17 new learner tests**
without changing the starters. Eight real-checker replay sequences matched the
expected status and exact model/check counts: proof repair, format recovery,
attempt exhaustion, provider failure, refusal, incomplete-output recovery,
proof-only edit rejection, and immediate accepted success. A corrected replay
also repaired the learner's actual failed Exercise 5 seed with prior costs
counted and zero new provider requests. Initial focused-starter observations
are in `runs/exercise06/scaffold.json`; complete setup validation is in
`runs/exercise06/instructor-validation.json`.

No new live API request was made. All three learner functions remain their
intended `NotImplementedError` starters. Python syntax, local Markdown links,
and progress records were checked. The course is on Exercise 6, awaiting learner
implementation; Exercises 1–5 remain complete.

## Exercise 6 function implementation

At the learner's request, the three starter functions are implemented. Repair
prompts reuse the public generation task and include the previous proposal or
unparsed response, actual diagnostics, selected action, and permitted edit scope.
Proof-only prompts require exact implementation-body preservation. The policy
stops for accepted success, unavailable budgets, terminal errors, and unknown
statuses; it selects proof-only repair or regeneration from the supplied evidence.
The loop refreshes history/budget each iteration and returns the session's own
finish result.

All 17 learner tests passed with the actual implementations. All eight replay
sequences also passed against the real Docker Lean acceptance checker, including
their exact model/check counts. The summary is `runs/exercise06/review.json`,
with source hashes and implementation-check metadata in
`runs/exercise06/implementation-check.json`. No live API request was made.
Exercise 6 still awaits current-code live evidence and implementation review;
the course has not advanced to Exercise 7.

## Exercise 6 implementation review

All 17 learner tests and eight real-checker replay sequences passed again.
Review inspected two current-code live traces. One generated an unsuccessful
proof, repaired only the proof on attempt 2, received `VERIFIED`, and stopped.
The other retained three failed proofs and stopped at the configured limit.
Every proof-only action preserved the implementation body exactly.

Saved prompts match the current prompt builder and prior observations. Proposed
bodies, rendered sources, task/policy identities, and checker source hashes
match their retained evidence. The accepted repair passed execution examples
and fresh trusted Comparator/kernel replay. Model/check counts and token sums
match the nested records; these traces stayed within their configured limits.
No new live model request was made during review, and no fixes remain.

The passing review and source hashes are in
`runs/exercise06/implementation-review.json`. CI includes the completed repair
tests. Exercises 1–6 are complete; another **OK** authorizes preparing Exercise 7.
