# Exercise 6 — Repair a proposal using Lean feedback

Exercises 1–5 passed review. You now turn one-shot generation into a bounded
repair loop. Your work is confined to three functions: a repair prompt, an
action decision, and the loop that connects them. History, budgets, transport,
parsing, source assembly, checking, and saved artifacts are supplied.

There are no written questions or reflection files. Your first **ok** requests
implementation review; another **ok** after passing feedback authorizes Exercise 7.

## First task — build the repair prompt

Implement `build_repair_prompt(task, previous, action)` in
[agent/repair_prompts.py](../../agent/repair_prompts.py).

| Input | Meaning |
| --- | --- |
| `task: AgentTask` | The same public specification, headers, template, imports, examples, and toolchain as Exercise 5. |
| `previous: Attempt` | The last actual observation and the proposal that produced it. |
| `action: RepairAction` | Either `REPAIR_PROOF` or `REGENERATE`. |
| Return value | `Prompt(system=..., user=...)`, using the same two-field JSON output format. |

Start from `build_generation_prompt(task)`, which you can reuse rather than
copying all the fixed-task formatting. Extend its messages with the selected
action, previous status, previous proposal, and actual diagnostics. Explain
what may change; retain the original response rules and fixed contract.

The most useful fields on `previous` are:

```python
previous.status              # e.g. "ELABORATION_FAILED"
previous.proposal            # Proposal, or None if parsing failed
previous.proposal.implementation_body  # only when proposal is not None
previous.proposal.proof_body
previous.diagnostics         # actual compiler/checker or format diagnostics
previous.response_text       # previous assistant text; useful after invalid JSON
```

For `REPAIR_PROOF`, explicitly tell the model to copy `implementation_body`
**exactly**, including its whitespace, and replace only `proof_body`. It still
returns both fields. The supplied service checks this equality before invoking
Lean. A changed implementation yields `EDIT_SCOPE_VIOLATION`; it is not silently
accepted as a proof repair.

For `REGENERATE`, permit both bodies to change while preserving all trusted
declarations and the specification. If `previous.proposal is None`, include
the previous response text and format error instead of accessing nonexistent
body fields. `dataclasses.asdict(previous.proposal)` and `json.dumps` are useful
for displaying the previous parsed proposal. Never serialize the whole session
or private configuration into a prompt.

For example, a repair user message might contain:

```text
Selected action: REPAIR_PROOF
Previous outcome: ELABORATION_FAILED

Previous proposal:
<the two actual body strings>

Observed Lean diagnostics:
<the actual error text>

Copy implementation_body exactly. Repair only proof_body.
Return the complete two-field JSON object.
```

The angle-bracket lines above describe where to insert actual input values;
do not send those placeholders to the model. You do not need to supply a solved
proof inside your prompt.

Your failed live run from Exercise 5 is a concrete example. Its implementation
was checked subtraction. Its proof used `simp [candidate]`, which changed the
goals to `b ≤ a` and `a < b`, then tried rewriting a conditional that was no
longer present. The feedback supports revising the proof. It does not establish
that the implementation is wrong. Send the observed goals to the model and let
it propose a repair.

Check only this first task, without Docker or an API key:

```bash
.venv/bin/python -m scripts.exercise06_review --only prompt
```

## Second task — choose the next action

Implement `choose_action(history, budget)` in
[agent/repair.py](../../agent/repair.py). `history` is a tuple of frozen `Attempt`
observations; `history[-1]` is the latest. `budget.can_attempt` and
`budget.reason` are computed by the supplied service. Return a `RepairAction`:

| Observation | Action |
| --- | --- |
| No history and budget available | `GENERATE` |
| Latest attempt is `VERIFIED` | `STOP` |
| No budget available | `STOP` |
| `ELABORATION_FAILED`, parsed proposal available, no behavioral counterexample | `REPAIR_PROOF` |
| Independently reviewed behavioral counterexample | `REGENERATE` |
| `ELABORATION_FAILED` without a parsed proposal | `REGENERATE` |
| `INVALID_PROPOSAL`, `MODEL_INCOMPLETE`, `SUBMISSION_REJECTED`, `TIMEOUT`, or `OUTPUT_LIMIT_EXCEEDED` | `REGENERATE` |
| `MODEL_ERROR`, `MODEL_REFUSED`, `INFRASTRUCTURE_ERROR`, `EDIT_SCOPE_VIOLATION`, `CONTROLLER_ERROR`, `EXERCISE_INCOMPLETE`, `BUDGET_EXHAUSTED`, or unknown status | `STOP` |

Success and unavailable budget take precedence over another attempt.
`REGENERATE_STATUSES` and `TERMINAL_ERRORS` are supplied sets you can use.

`previous.behavioral_counterexample` is optional, independently reviewed
evidence. A policy test supplies a synthetic counterexample to exercise this
distinction. The current real checker summaries do not synthesize this field
from an error or exit code. When it is `None`, do not invent a counterexample.
This lesson's default is proof-only repair after elaboration failure; that is
a search policy, not a proof that the implementation is correct.

```bash
.venv/bin/python -m scripts.exercise06_review --only policy
```

## Third task — connect the loop

Implement `run_repair(task, session)` in the same file. Each iteration:

1. Read the current `session.history` and `session.budget` and choose an action.
2. For `STOP`, return `session.finish()` immediately.
3. For `GENERATE`, build the original generation prompt.
4. For `REPAIR_PROOF` or `REGENERATE`, build a repair prompt from the latest observation.
5. Call `session.attempt(prompt, action)`, which records the result, then repeat.

The service returns an `Attempt`, updates history and counters, and retains
failure evidence. Read the refreshed properties on the next iteration. Do not
call the provider or checker directly, manually update counters, catch errors
to fabricate success, or continue after accepted success.

Run all **17 learner tests** without Docker/API access:

```bash
.venv/bin/python -m unittest discover \
  -s exercises/06-feedback-repair/tests -v
```

The three starter functions initially raise `NotImplementedError`. The learner
loop tests use a spy checker; the complete review also uses the real Lean checker.

## Replay through real Lean

```bash
.venv/bin/python -m scripts.exercise06_run --replay proof_then_valid
.venv/bin/python -m scripts.exercise06_run --replay always_bad
.venv/bin/python -m scripts.exercise06_run --replay scope_violation
```

The first sequence should be:

```text
GENERATE     -> ELABORATION_FAILED
REPAIR_PROOF -> VERIFIED
STOP
```

A third saved response is deliberately present. It must never be consumed after
success. Replays return fixture responses rather than generate fresh proofs;
they test the control flow and trusted checking path. Their token counts are
synthetic and labelled `fixture`.

| Replay | Final outcome | Model operations | Acceptance checks |
| --- | --- | --- | --- |
| `proof_then_valid` | `VERIFIED` | 2 | 2 |
| `format_then_valid` | `VERIFIED` | 2 | 1 |
| `always_bad` | `BUDGET_EXHAUSTED` | 3 | 3 |
| `provider_failure` | `MODEL_ERROR` | 1 | 0 |
| `refusal` | `MODEL_REFUSED` | 1 | 0 |
| `incomplete_then_valid` | `VERIFIED` | 2 | 1 |
| `scope_violation` | `EDIT_SCOPE_VIOLATION` | 2 | 1 |
| `already_valid` | `VERIFIED` | 1 | 1 |

Single-run commands return nonzero for outcomes other than `VERIFIED`.
Expected budget exhaustion/rejection is therefore nonzero. The review command
labels a case passing when its outcome and exact operation counts match.

## Supplied limits and records

The default limits are 3 attempts, 3 model calls, 3 candidate submissions,
3 acceptance checks, a 32,768 reported-token threshold, and a 600-second elapsed
time threshold. CLI options configure each independently. The transport's
per-call output cap defaults to 8192 and is reduced to the remaining token
allowance when necessary.

Attempt/call/submission/check counters are guarded before another attempt.
Malformed output consumes an attempt and a call, even though no candidate is
checked. Reasoning tokens are already included in output tokens. No automatic
transport retries are hidden from these counters.

**Token and elapsed-time thresholds are checked at operation boundaries.**
Total input/output usage becomes known after a provider response; a completed
request can exceed the token threshold. The run records that overrun, stops
before checking that response, and issues no further calls. Unknown usage also
stops further work. These are not claims of a prepaid token ceiling or a hard
wall-clock kill switch. Existing per-worker deadlines and resource limits still
apply, and the HTTP adapter retains its socket-operation timeout. A check that
finishes after the run time threshold is retained but the run is budget-exhausted.
The checked candidate's mathematical acceptance remains available in its own report.

Each new run under `runs/exercise06/attempts/run-*/` has:

```text
task.json          fixed public task snapshot and digest
history.json       ordered observations and actions
attempts/run-*/    prompt, response, proposal, source, and full checker evidence
seed/              snapshot/provenance if continuing an earlier failed run
result.json        outcome, limits, remaining budget, counters, source hashes
```

Diagnostic excerpts and previous raw response text are capped at 16 KiB for
prompt inputs. Complete diagnostics and responses remain in the nested attempts.
History records, parsed proposals, and public task views are immutable objects.

## Run with your real model

All calls reuse the shared `.env` URL, key, and model configuration. No new
credential setup or transport implementation is needed.

```bash
.venv/bin/python -m scripts.exercise06_run --live
```

To repair your specific failed Exercise 5 live attempt, use its existing report:

```bash
.venv/bin/python -m scripts.exercise06_run --live \
  --seed-run runs/exercise05/attempts/run-fw0odzm5/result.json
```

That report exists in this workspace and contains the failed rewrite proof.
On another checkout, use an actual failed-proof report produced there. Seed
loading validates the task, proposal/source equality, and checker source hash;
it retains a local snapshot and points to the original full evidence. Its
attempt, model call, reported tokens, check, and elapsed time count toward the
new run's limits. Do not delete the original seed artifacts. A seed alone does
not satisfy the requirement for a new live model attempt.

The loop can make multiple paid calls, bounded by the configured counters.
A real run need not solve the task: retained unsuccessful repair/budget outcomes
are useful evidence. Provider/configuration/infrastructure failures must be
resolved before completion. No live API call is made during lesson preparation
or by the review command.

## Review

```bash
.venv/bin/python -m scripts.exercise06_review
```

This runs learner tests and all eight real-checker replays, and looks for a
saved new live-model attempt produced by the current three learner/prompt files.
It never makes a model request. Keep real runs in the default artifact directory
for discovery. It saves the latest summary at `runs/exercise06/review.json` and
preserves review sessions under `runs/exercise06/reviews/`.

After the evidence is ready, say **ok** for review. I will give feedback and wait
for your next **ok** before preparing Exercise 7.
