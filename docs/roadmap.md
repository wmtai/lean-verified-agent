# Ten cumulative exercises

**Exercise 1 is current.** Each exercise extends the same repository. Its lesson
will introduce concepts with worked examples, provide starter code and acceptance
tests, and remain current until you say **OK**. This roadmap describes the later
work; it does not mark those capabilities as implemented.

The generated programs and proofs will be Lean 4 source. Python will load tasks,
call the model, run checks, preserve evidence, and manage resources. The required
signature, formal specification, trusted definitions, and acceptance policy stay
fixed while proposed implementations and proofs change.

## Checking infrastructure

| Exercise | What you build | Completion criterion |
| --- | --- | --- |
| **1. Reproducible environment** | Pinned Python and Lean setup, one trusted checked-subtraction specification, correct and unsuccessful reviewed fixtures, and a learner starter. | Actual versions/configuration are recorded, and the correct proof, well-typed wrong program, and failed contract proof produce their expected outcomes. |
| **2. Tasks and submissions** | Task metadata, immutable task data, structured proposal fields, loader, and trusted renderer. | Valid proposals produce the intended file; missing fields, wrong types, unexpected declarations, and signature changes are rejected predictably. Structural validation is not presented as complete semantic protection. |
| **3. Sandboxed Lean runner** | Isolated work directories, restricted execution, resource limits, bounded diagnostics, and structured results. | Syntax/proof failures and timeouts are distinguished, timed-out work terminates, logs survive, and candidates cannot access protected files or credentials. |
| **4. Trusted acceptance gate** | Fixed challenge–solution checking, allowed implementation holes, an explicit permitted-axiom policy, and final validation in a fresh checking context. | Valid solutions pass; unfinished dependencies, custom axioms, altered contracts, and missing declarations fail. A missing checker or failed validation produces an explicit non-success result. |

Exercise 4 follows the pinned challenge–solution checking approach described in
the brief, including Comparator integration. An initial successful Lean process
is an observation, not the final acceptance decision. Acceptance is established
before autonomous generation is introduced.

## Generation and repair

| Exercise | What you build | Completion criterion |
| --- | --- | --- |
| **5. One-shot generation** | A replaceable model interface, fake/replay client, one real provider adapter, generation prompt, response parser, and one-shot command. | A command loads a task, obtains a proposal, checks it, and saves the full outcome. Model/API failures are distinguished from unsuccessful Lean submissions. |
| **6. Verifier-guided repair** | Preserved attempt history, repair feedback, remaining-budget checks, and stopping conditions. | A replayed failed/corrected sequence is deterministic, respects all caps, preserves every attempt, and stops immediately after accepted success. The loop is also exercised with the real model. |
| **7. Helpers and planning** | Controlled helper declarations, logged planning, proof-only repair, and implementation-and-proof revision modes. | Helper dependencies pass the same acceptance policy, planning consumes the budget, and proof-only repair actually preserves the implementation. Accumulator reversal demonstrates a generalized invariant without weakening the main theorem. |

The initial proposal interface will contain `implementation_body` and
`proof_body`. Exercise 7 will introduce controlled helper fields around the
implementation. Those fields describe permitted content; they do not themselves
establish a security boundary.

Budgets will cover candidate submissions, model calls, input/output tokens, Lean
checks, and elapsed time. Planning and malformed responses consume resources.
Feedback will distinguish observed diagnostics from interpretations: an unsolved
proof goal alone does not establish that the implementation is wrong.

## Data, comparisons, and release

| Exercise | What you build | Completion criterion |
| --- | --- | --- |
| **8. Audited task suite** | Ten development tasks and twenty held-out evaluation tasks, reviewed contracts, checked references, documented library restrictions, and split provenance. | Each included task has a contract audit and checked reference; evaluation data is distinct from development/prompt tuning, and references live outside the agent workspace. |
| **9. Controlled comparisons** | One-shot, independent sampling, verifier-guided repair, and planning-plus-repair under a common experiment interface. | Saved configurations reproduce a small comparison; matched budgets include all model work, repeated runs retain failures, and infrastructure reruns follow a predetermined policy. |
| **10. Analysis and release** | Representative failure analysis, one predefined repair-policy variation, reproducible artifacts, and a report. | The repository contains the working CLI, acceptance tests, configuration snapshots, results, and an explanation of what helped, failed, and remains unestablished. A negative experimental result is acceptable. |

The **ten exercises** are the implementation steps you complete. The **ten
development and twenty evaluation tasks** are Lean programming problems attempted
by the completed agent. A small pilot can precede the full suite without changing
that target.

Evaluation will compare sampling and feedback methods under comparable total
budgets. One-shot is a reference baseline. Reports will include solve rate,
resource use, implementation/proof/helper changes, failure categories, and
uncertainty across repetitions. Public examples, larger budgets, and familiar
development fixtures do not establish broad generalization.

## Where to begin

Open the [Exercise 1 guide](../exercises/01-environment/README.md). Complete its
environment checks and starter implementation/proof, inspect the recorded
outcomes, then say **OK** to advance. The
[full brief](project-brief.md) remains the design reference for the later exercises.
