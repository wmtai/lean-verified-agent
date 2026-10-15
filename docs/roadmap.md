# Ten cumulative exercises

**Exercises 1–6 passed review; awaiting OK before preparing Exercise 7.** From Exercise 3
onward, your work focuses on Lean and the agent's reasoning and control flow.
System services are supplied with working implementations and regression tests:
process execution, Docker, log files, API transport, resource accounting, and
experiment persistence are support code rather than learner assignments.

Each exercise supplies only the capabilities needed at that stage. Later
capabilities in this roadmap are plans, not claims of completed implementation.
Your first **OK** requests review. After passing feedback, a second **OK** advances
to the next exercise. Required fixes keep the current exercise active.
There are no required written questions, reflections, or explanation worksheets.
Reviews assess the implementation and its check results.

The model generates Lean implementations and proofs. Python controls their
generation, checking, and repair. The required signature, specification, trusted
definitions, and acceptance policy stay fixed while proposed solutions change.

| Exercise | Your work | Supplied support | Completion evidence |
| --- | --- | --- | --- |
| **1. Reproducible environment — complete** | Understand checked subtraction, write the implementation and proof, and compare a well-typed wrong program with a failed contract proof. | Pinned tools, environment checks, and reviewed fixtures. | Actual tool versions and expected fixture outcomes; learner solution passed review. |
| **2. Tasks and submissions — complete** | Implement immutable task data, JSON proposal validation, and template rendering. | Task format, examples, and acceptance tests. | All 23 submission tests and earlier regressions passed review. |
| **3. Lean feedback and proof repair — complete** | Read raw syntax/proof diagnostics and repair a theorem for a fixed correct implementation. | Bounded subprocesses, restricted Docker workers, immutable image selection, logs, and a review command. | The repaired candidate elaborated; all diagnostic examples matched expected outcomes. |
| **4. Trusted acceptance — complete** | Replace an axiom with a proof, finish a helper, and restore a required theorem statement in three Lean files. | Pinned challenge–solution checker, separate export/fresh verification workers, permitted-axiom policy, and retained acceptance evidence. | All three repairs received `VERIFIED` and passed review; reviewed invalid examples were rejected. |
| **5. One-shot LLM flow — complete** | Write a generation prompt from the public task view and connect the load → generate → parse → check flow. | Replay and real provider adapters, structured-response parsing, CLI, and saved records. | Seven learner tests and all six replay cases passed; real runs include a verified proposal and a failed proof with retained diagnostics. |
| **6. Feedback-driven repair — complete** | Implement repair prompt content, attempt-state decisions, stopping rules, and when to retain the implementation while revising a proof. | Model-call transport, frozen attempt observations, explicit budget guards/thresholds, proof-only edit enforcement, and artifact storage. | All 17 tests and eight replays passed; live evidence includes accepted proof repair on attempt 2 and stopping at the attempt limit. |
| **7. Helpers and planning** | Prove a generalized accumulator invariant, plan implementation and proof together, and choose proof repair, a helper, or implementation redesign. | Controlled helper assembly/checking, action records, and accounting. | Main contract stays fixed; helpers meet the same acceptance policy, planning is counted, and proof-only actions preserve the implementation. |
| **8. Task-contract audit** | Audit ten development and twenty held-out Lean tasks, reference proofs, algorithmic intent, library restrictions, and task-family separation. | Packaging, task loading, reference-check commands, and evaluator-controlled reference storage. | Every included contract has checked reference evidence and documented provenance; held-out answers are inaccessible to generation. |
| **9. Controlled comparisons** | Define one-shot, independent sampling, feedback repair, and planning policies with comparable budgets; read repeated results. | Common experiment runner, scheduling, persistence, aggregation, and configured infrastructure reruns. | Saved configurations reproduce the comparison, count all model work, and preserve failed and expensive attempts. |
| **10. Failure analysis and report** | Explain representative traces, classify code/proof/helper changes, evaluate one predefined repair-policy variation, and write the report. | Trace summaries, plots, reproducibility commands, and release packaging. | Results and limitations are supported by retained evidence; another user can reproduce the reported analysis. A negative result is acceptable. |

The trusted acceptance gate is established before model generation starts in
Exercise 5. In Exercise 3, `ELABORATED` records successful Lean execution; it does
not issue `VERIFIED`. Syntax errors and unsolved goals can both have
`ELABORATION_FAILED` status. Their raw diagnostics guide different repairs; the
runner does not claim to infer mathematical causes from an exit code.

Later budgets cover submissions, calls, input/output tokens, Lean checks, and
elapsed time. Planning and malformed responses consume resources. An unsolved
proof goal does not by itself establish that the implementation is wrong.

The **ten exercises** are the learning sequence. The **ten development and
twenty evaluation tasks** are Lean programming problems attempted by the final
agent. Their number and the final research scope are unchanged by this teaching
redesign. Evaluation compares methods under matched total budgets and retains
uncertainty across repeated runs.

Start with the [Exercise 6 guide](../exercises/06-feedback-repair/README.md).
The model/checker/history infrastructure is supplied; your work is confined to
the repair prompt, action selection, and loop. The
[full brief](project-brief.md) gives the project rationale and final design.
