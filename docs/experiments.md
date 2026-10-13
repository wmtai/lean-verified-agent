# Controlled experiments

Development fixtures diagnose engineering failures. They are not held-out
evidence: the agent developer can inspect their reference proofs. No audited
evaluation tasks are shipped. `--split eval` fails clearly until evaluation
contracts have been added; do not relabel familiar development exercises and
call that generalization.

Use a common provider and model, task hashes, import set, verifier image,
and call/token/time/Lean-check caps for sampling versus repair. A separate
planning request counts as a model call and consumes tokens. The one-shot
baseline uses one generation; its lower solve rate under a larger repair
budget alone cannot establish that feedback helps.

`evaluate` creates an experiment manifest and independent run folders for all
tasks, methods, and repetitions. Strategy order rotates between repetitions.
It does not set a provider seed or guarantee reproducible model completions.
Keep the raw prompts/responses and record provider deployment/version changes
when they matter. Use repeated runs to assess stochastic variation.

Analysis includes every saved run, including `ERROR` and unsuccessful outcomes.
With one repetition, `solve_rate` is verified tasks divided by tasks. With
multiple equally populated repetitions, it is the mean solve rate across
task-run pairs. Do not mix unequal task sets or unfinished experiment folders
when comparing methods. Infrastructure error counts are reported separately;
rerun affected comparisons rather than silently dropping them.

Metrics include LLM calls, reported input/output tokens (or explicitly flagged
estimates when usage is unavailable), Lean invocations,
elapsed seconds, and implementation/proof-only changes between candidates.
Time to verification is averaged over successful runs and reported alongside
all-run mean time to expose that selection effect. Planning time is included.
Failure categories summarize observable diagnostics; they cannot establish
that an implementation is false without a checked counterexample.

The controller preflights a prompt estimate and caps completion length with
remaining token headroom. Provider-reported usage is authoritative after each
request. Tokenization differs between providers, so a request can exceed the
cap if the preflight estimate undercounts; the controller must stop subsequent
requests. These limits bound search effort, not external billing precisely.
The HTTP adapter uses socket timeouts. A slowly delivered response may return
after the run deadline; the controller will not verify a late candidate, but
cannot cancel a provider's computation or guarantee its billing cutoff.

Suggested next experiment: compare unrestricted repair with a policy that
chooses proof repair, implementation revision, local invariant introduction,
or replanning. Keep all model requests, including policy decisions, within the
same caps. Report solve rate with uncertainty intervals and inspect failed
traces before claiming a research contribution.
