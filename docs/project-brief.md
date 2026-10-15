# Project 1 — Fixed-Spec Lean Agent
## A ten-exercise project in LLM-based verified code generation

**You will build an agent that receives a fixed Lean programming specification, generates an implementation and a correctness proof, checks them with Lean, and repairs unsuccessful attempts.**

The final repository will contain both a working agent and an experiment comparing different generation strategies.

There are **two kinds of code** in this project:

| Component | Language | Purpose |
|---|---|---|
| Generated implementation | Lean 4 | The program the agent is trying to construct |
| Generated proof | Lean 4 | Evidence that the implementation satisfies the specification |
| Agent controller | Python | Calls the model, submits candidates, processes feedback, and manages the budget |
| Trusted task definitions | Lean 4 | Define the requirements that the agent must satisfy |
| Experiment framework | Python | Runs comparisons and records results |

**We are not generating Python programs and translating them into Lean.** Python controls the workflow; the programs being verified are written directly in Lean.

We will build this through **ten cumulative exercises**. Each lesson introduces
its concepts with worked examples, focused learner tasks, and supplied checks.

**Current teaching design:** Exercises 1 and 2 are complete. Starting with
Exercise 3, learner work focuses on Lean programs/proofs and agent generation,
checking, and repair decisions. System implementation is supplied: process
management, Docker isolation, API transport, logging, resource accounting, and
experiment persistence are support services. Later services are added when
their exercise is reached. This note and the revised Section 12 supersede the
original infrastructure-programming assignments; the final system scope is
unchanged. The active guide is
[Exercise 3 — Read Lean feedback and repair a proof](../exercises/03-sandboxed-runner/README.md).

The first **OK** requests review and feedback. After a passing review, another
**OK** advances to the next exercise. Required fixes keep the current exercise
active.

**Learner preference:** from Exercise 3 onward, completion is assessed through
implementations and check results. Written Q&A, reflection worksheets, and oral
explanation requirements are omitted. Technical explanations remain available
in the lesson material and on request.

---

# 1. The precise goal

Suppose we provide a specification for a function:

> Given natural numbers \(a\) and \(b\), return `some (a - b)` when \(b\le a\), and return `none` otherwise.

The agent must generate two things:

\[
(p,\pi),
\]

where \(p\) is a Lean implementation and \(\pi\) is a proof that the implementation satisfies the specification.

If the specification is \(S\), our requirement is:

\[
\boxed{p:\tau \qquad \pi:S(p)}
\]

Here, \(\tau\) is the required function type.

For checked subtraction:

\[
\tau=\mathbb N\rightarrow\mathbb N\rightarrow
\operatorname{Option}(\mathbb N).
\]

The project succeeds when the system can automatically produce accepted code-and-proof pairs—or honestly report that it did not find one within its budget.

This is related to existing joint program-and-proof generation research. For example, P³ investigates planning the implementation and proof together rather than treating proof generation as an afterthought. Our first objective is to build a controlled, understandable system, not to claim that the basic workflow is new. [arXiv](https://arxiv.org/abs/2608.09277)

## The central restriction

**The model cannot change the specification to make its proof easier.**

It may revise the implementation, proof, and permitted helper declarations. It may not weaken the required theorem, alter trusted definitions, or change the acceptance rules.

---

# 2. What is—and is not—in scope

## What we will build

The first version will handle small, pure Lean functions: arithmetic operations, list-processing functions, recursive algorithms, and selected program transformations.

It will support one pretrained LLM through a replaceable model interface. A fake or replay model will also be available so that we can test the software without making paid model calls.

The agent will work primarily with complete candidate files rather than attempting tactic-level search at every proof step.

## What we will not build initially

We will not train or fine-tune a model, implement reinforcement learning, build a multi-agent society, or automatically translate unrestricted natural-language requirements into formal contracts.

We will also not claim to verify arbitrary Python, Rust, or native executables.

Your existing `ArithExpr` compiler remains a useful separate project, but it cannot compile arbitrary Lean functions. Therefore:

> **This project’s main artifact is verified Lean source code, not code compiled through your earlier toy stack-machine compiler.**

## What the correctness guarantee means

An accepted result establishes the supplied formal contract under the configured Lean environment and trust assumptions.

It does not automatically establish that the contract captures every informal intention, that the program is efficient, or that every external runtime and deployment component is correct.

Lean’s own validation guidance distinguishes checking a proof from checking what its theorem statement means. That distinction will be built into our task and acceptance design. [Lean Language](https://lean-lang.org/doc/reference/latest/ValidatingProofs/)

---

# 3. A complete example task

We will use checked subtraction as a running example because you already understand it.

## 3.1. The trusted specification

The task designer supplies:

```lean
import Lean

namespace TaskSpec

def CheckedSubSpec
    (f : Nat → Nat → Option Nat) : Prop :=
  (∀ a b, b ≤ a → f a b = some (a - b)) ∧
  (∀ a b, a < b → f a b = none)

end TaskSpec
```

The agent is not allowed to edit this definition.

## 3.2. The candidate template

The system provides the following structure:

```lean
def candidate (a b : Nat) : Option Nat :=
  -- IMPLEMENTATION HOLE
  sorry

theorem candidate_correct :
    TaskSpec.CheckedSubSpec candidate := by
  -- PROOF HOLE
  sorry
```

The holes are unfinished work. They are not acceptable in a final submission.

The trusted renderer—not the model—controls the required declaration names, signature, and theorem statement.

## 3.3. A successful candidate

A valid solution would be:

```lean
def candidate (a b : Nat) : Option Nat :=
  if b ≤ a then
    some (a - b)
  else
    none

theorem candidate_correct :
    TaskSpec.CheckedSubSpec candidate := by
  unfold TaskSpec.CheckedSubSpec
  constructor
  · intro a b h
    simp [candidate, h]
  · intro a b h
    have hnot : ¬ b ≤ a := by
      omega
    simp [candidate, hnot]
```

The implementation and proof are different artifacts. The proof script is elaborated into evidence for the required theorem; it is not a translation of the program into another language.

## 3.4. A plausible unsuccessful candidate

Suppose the model proposes:

```lean
def candidate (a b : Nat) : Option Nat :=
  some (a - b)
```

This is a well-typed function, but it violates the contract.

For example:

\[
candidate(3,5)=\operatorname{some}(0),
\]

while the contract requires `none`.

The system should not accept this merely because the implementation compiles. It must also verify the fixed correctness theorem.

---

# 4. How we will represent tasks and submissions

We need an explicit data model so that the agent, verifier, and evaluator agree on what they are handling.

## 4.1. A task record

Conceptually, each task is:

\[
T=(\tau,S,C,E),
\]

where:

- \(\tau\) is the required function type.
- \(S\) is the fixed formal contract.
- \(C\) contains implementation and submission constraints.
- \(E\) identifies the trusted environment.

In the repository, a task will contain:

```text
tasks/checked_subtraction/
    task.json
    Specification.lean
    candidate_template.lean
```

The metadata will record the task identifier, required declaration names, permitted imports, editable regions, public examples, and task-family label.

Reference solutions used to validate the task will be kept separately, outside the agent’s accessible workspace.

## 4.2. A candidate proposal

Initially, the model will return two fields:

```text
implementation_body
proof_body
```

For more advanced tasks, we will introduce controlled helper-declaration fields:

```text
helpers_before_implementation
implementation_body
helpers_after_implementation
proof_body
```

The distinction permits an auxiliary recursive function before the main implementation and a helper correctness lemma afterward.

These fields are a structured submission format, **not a security boundary by themselves**. A string placed inside a code region can still contain unexpected syntax. Later acceptance checks must verify the elaborated result, not merely the response format.

## 4.3. An attempt record

Each attempt will preserve:

```text
Task identity and specification hash
Candidate implementation and proof
Model configuration
Prompt and response
Lean diagnostics
Acceptance-check results
Resource usage
Final attempt status
```

The previous attempt is never silently overwritten.

That history is needed both for debugging and for studying how the agent improves—or fails to improve—its solution.

---

# 5. The complete agent workflow

The system will follow this process:

```text
Load trusted task
       ↓
Prepare generation prompt
       ↓
Model proposes implementation and proof
       ↓
Parse response and assemble candidate
       ↓
Run sandboxed Lean checks
       ↓
Perform acceptance checks
       ↓
Accepted?
  Yes → Save verified artifact and run record
  No  → Prepare feedback and revise, while budget remains
```

## 5.1. Initial generation

The initial prompt contains the trusted specification, signature, permitted dependencies, submission format, and public examples.

It does not contain the reference implementation or proof.

## 5.2. Candidate assembly

The Python controller inserts the permitted generated content into the trusted template.

It records a hash of the assembled candidate and the trusted task snapshot.

These hashes support provenance and detect accidental changes. They do not, by themselves, prove semantic correspondence.

## 5.3. Verification

The worker asks Lean to elaborate the candidate and check the theorem.

We start with whole-file interaction. Lake provides the project environment for running Lean commands; we will pin the toolchain and dependencies rather than let the agent change them during repair. [Lean Language](https://lean-lang.org/doc/reference/latest/Build-Tools-and-Distribution/Lake/)

An illustrative development command is:

```bash
lake env lean Candidate.lean
```

This will run inside the project’s restricted worker, not in an unrestricted workspace containing credentials.

## 5.4. Feedback

When an attempt fails, the controller sends the model the current candidate and relevant diagnostics.

The feedback must distinguish observations from interpretations.

For example:

```text
Observed:
The correctness theorem has an unsolved goal.

Not established:
Whether the implementation is mathematically incorrect.

Permitted next action:
Revise the implementation, proof, or allowed helper declarations.
```

A concrete counterexample is stronger evidence, but Lean does not automatically supply one for every unsuccessful proof. An optional test component must separately produce and validate it.

## 5.5. Stopping

The run ends when an artifact passes final acceptance, the budget is exhausted, or infrastructure fails.

The model cannot grant itself more attempts.

A failed run should not claim that the task is impossible.

---

# 6. Verification outcomes and honest reporting

We will use explicit statuses.

| Status | Meaning |
|---|---|
| `VERIFIED` | The final acceptance procedure accepted the intended artifact |
| `SUBMISSION_REJECTED` | The response or artifact violated submission rules |
| `ELABORATION_FAILED` | Lean could not elaborate the submitted code or proof |
| `PROOF_INCOMPLETE` | The required proof was not established |
| `TIMEOUT` | A verification process exceeded its resource limit |
| `INFRASTRUCTURE_ERROR` | A tool, API, environment, or controller failed |
| `UNSOLVED_WITHIN_BUDGET` | The run ended without an accepted solution |

These labels describe the system’s evidence.

We will **not** use “incorrect implementation” as a synonym for “proof failed.” An incorrect implementation can be established by an appropriate counterexample; an incomplete proof alone does not establish it.

Also, a candidate will not become `VERIFIED` just because a preliminary Lean invocation succeeded. It must pass the final acceptance gate.

---

# 7. The trust boundary

This is the most important engineering constraint.

The model is allowed to propose unreliable content. The acceptance process must independently determine what that content establishes.

## 7.1. Fixed challenges, not model-controlled requirements

The checker must compare the solution against trusted declarations.

For implementation-generation tasks, the implementation is an allowed definition hole. Its signature is fixed, while the contract and other trusted dependencies remain fixed.

Lean’s Comparator supports checking theorem correspondence, allowed axioms, and declared definition holes. Its documentation also warns that definition-hole tasks require additional oversight: a formally valid solution may still exploit an inadequate task definition. [GitHub](https://github.com/leanprover/comparator)

We will integrate that checking approach rather than try to invent a trusted proof checker in Python.

Exact configuration will follow the pinned tool versions used in the project.

## 7.2. Proof dependencies matter

Checking that the final proof text contains no `sorry` is insufficient. It might rely on an unfinished helper.

For development, Lean exposes transitive axiom dependencies through:

```lean
#print axioms candidate_correct
```

The project will define an explicit permitted-axiom policy and reject unfinished proofs or unapproved assumptions. Lean’s documentation explains that proofs remain relative to their axiom dependencies. [Lean Language](https://lean-lang.org/doc/reference/latest/Axioms/)

This diagnostic is useful, but it is not our entire defense against untrusted code.

## 7.3. Sandboxing starts before the first model-generated Lean check

Lean tactics and metaprograms can perform actions during elaboration. Official guidance therefore treats unreviewed AI-generated proofs and programs as potentially adversarial. [Lean Language](https://lean-lang.org/doc/reference/latest/ValidatingProofs/)

Our proposed worker will have no model API credentials, no unnecessary network access, restricted writable directories, and explicit process and memory limits.

Trusted source files, reference solutions, and acceptance configuration remain outside the model’s writable workspace.

A timeout alone is not a sandbox.

## 7.4. Final checking is separate from exploratory feedback

The final checker will use a fresh environment and trusted challenge data. It will not trust the model’s claimed verdict or reuse a potentially compromised interactive session as its sole authority.

Comparator’s guarantees still depend on its documented assumptions, including trustworthy challenges, correct checking components, and safe isolation. We will report that trust boundary rather than claim absolute security. [GitHub](https://github.com/leanprover/comparator)

If final validation is unavailable, the system must report that limitation—not silently substitute a weaker check and label the result verified.

## 7.5. The implementation must be usable as code

The project asks for executable implementations, not merely proofs that a suitable mathematical object exists.

Tasks will therefore restrict noncomputable implementations and require appropriate execution smoke tests. Those tests supplement the proof and check the intended programming interface; they do not replace universal correctness.

---

# 8. What intelligence the agent will have

We will begin with one model, not several specialized agents.

The controller will eventually support these actions:

```text
GENERATE
REPAIR_PROOF
REVISE_IMPLEMENTATION_AND_PROOF
ADD_HELPER
REPLAN
RESTART
```

The action set describes allowed workflows. It does not require reinforcement learning.

## Example A — Proof-only repair

The implementation is:

```lean
def candidate (n : Nat) : Nat :=
  n + n
```

The agent is trying to prove that it equals `2 * n`.

A suitable repair may only change the proof.

## Example B — Implementation repair

The checked-subtraction implementation always returns `some`.

A checked counterexample shows a genuine behavioral error. Revising only the proof cannot solve the original task.

## Example C — Helper discovery

For accumulator reversal, the agent may need:

\[
\forall acc,\quad
reverseAux(xs,acc)=xs.reverse++acc.
\]

The main theorem remains unchanged. The agent adds a stronger auxiliary theorem that helps prove it.

**Generalizing a helper is permitted; weakening the required contract is not.**

Initially, our policies will be transparent rules or prompts. We will not pretend that the controller perfectly diagnoses mathematical failure.

---

# 9. The experiment we will conduct

The working agent is the engineering deliverable. A controlled comparison is the research deliverable.

## 9.1. Four main strategies

| Strategy | Procedure |
|---|---|
| **One-shot** | Generate one implementation and proof |
| **Independent sampling** | Generate fresh candidates without previous verification feedback |
| **Verifier-guided repair** | Revise an existing candidate using diagnostics |
| **Joint planning and repair** | Plan implementation and proof structure, then generate and repair |

Planning and iterative repair are already studied in the literature. Our experiment will investigate their behavior in the particular task suite and budget we define, rather than assume a new architecture automatically constitutes a contribution. [arXiv](https://arxiv.org/abs/2608.09277)

## 9.2. Budget accounting

We will record model input/output tokens, model calls, candidate submissions, Lean checks, and elapsed time.

A starting configuration can allow up to five candidate submissions, with separate configurable limits for tokens and verification resources.

Planning calls and malformed model responses consume resources too.

One-shot performance is a reference point. The main causal comparison is between **independent sampling and feedback-driven methods under comparable total budgets**.

## 9.3. Primary metric

For tasks \(D\) and budget \(B\):

\[
\operatorname{SolveRate}(B)=
\frac{
\#\{\text{tasks accepted within }B\}
}{
|D|
}.
\]

We will also report repair counts, implementation changes, helper-lemma additions, failure categories, and uncertainty across repeated runs.

Infrastructure failures will be reported separately, with a predetermined rerun policy rather than selectively removed after seeing results.

## 9.4. What we will not claim

We will not claim that passing public tests proves correctness, that every failed proof identifies a wrong program, or that a higher solve rate under a larger budget demonstrates better reasoning.

We will also not claim broad generalization from a handful of familiar exercises.

---

# 10. The task suite

Your previous exercises will be development material because you understand their intended solutions.

The default project target is **ten development tasks and twenty held-out evaluation tasks**. We can first run a smaller pilot without changing the design.

Development tasks can cover checked arithmetic, clamping, list recursion, accumulator invariants, sorting, and simple transformations.

Evaluation tasks should use different contracts or algorithmic templates, not merely different variable names.

Each task must have an audited contract and a checked reference solution that remains inaccessible to the agent.

We will explicitly decide whether existing library implementations are allowed. “Implement reversal yourself” and “produce any function equal to reversal, including calling `List.reverse`” are different tasks.

VERINA is a possible later source of curated Lean tasks, with formal specifications and reference material. We would inspect selected tasks and preserve a clear separation between the agent-visible challenge and hidden reference solutions. [arXiv](https://arxiv.org/abs/2505.23135)

**Important distinction:** the ten exercises below are the steps **you** complete to build the system. The benchmark tasks are the programming problems that your completed **agent** attempts.

---

# 11. Proposed repository and final interface

The repository will grow toward:

```text
fixed-spec-lean-agent/
├── README.md
├── pyproject.toml
├── configs/
│   ├── model.json
│   ├── budgets.json
│   └── acceptance.json
├── lean/
│   ├── lean-toolchain
│   ├── lakefile.toml
│   └── Trusted/
├── tasks/
│   ├── development/
│   └── evaluation/
├── agent/
│   ├── task.py
│   ├── proposal.py
│   ├── model_client.py
│   ├── prompts.py
│   ├── controller.py
│   └── policies.py
├── verification/
│   ├── runner.py
│   ├── diagnostics.py
│   └── acceptance.py
├── evaluation/
│   ├── run_suite.py
│   └── summarize.py
├── tests/
└── runs/
```

Reference answers will live in a separate evaluator-controlled location.

The intended command-line interface—not an existing command yet—will resemble:

```bash
python -m agent run \
  --task checked_subtraction \
  --strategy repair \
  --max-submissions 5
```

A run will produce candidate files, diagnostics, acceptance results, and a machine-readable summary.

For richer interaction, LeanInteract provides Python interfaces to Lean commands and proof states. We will only add that dependency if whole-file diagnostics prove insufficient; it is not required for the first working version. [GitHub](https://github.com/augustepoiroux/LeanInteract?utm_source=chatgpt.com)

---

# 12. The ten exercises

Each exercise will extend the same repository. You will not repeatedly rebuild earlier components.

## Exercise 1 — Build a reproducible project environment

**Objective:** establish a working Python–Lean project before introducing any model.

You will create the repository, pin the Lean toolchain and Python dependencies, add one trusted specification, and run a manually written correct solution.

The new concepts are project environments, process boundaries, and reproducibility.

We will use two contrasting fixtures: a correct checked-subtraction implementation and a well-typed implementation that fails its contract.

**Completion criterion:** the environment can reproduce the expected outcomes, and its versions and configuration are recorded. No LLM integration is required.

---

## Exercise 2 — Define tasks and assemble candidate submissions

**Objective:** make the task and candidate interfaces precise.

You will implement the task metadata model, candidate-response model, file loader, and renderer that inserts generated content into permitted regions.

The new concepts are structured interfaces, immutable task data, namespacing, and separation of trusted requirements from proposed solutions.

We will test missing response fields, invalid field types, unexpected declarations, and accidental changes to required signatures.

**Completion criterion:** a valid proposal produces the intended Lean file, while malformed proposals are rejected predictably. At this stage, structural validation is not presented as complete semantic protection.

---

## Exercise 3 — Read Lean feedback and repair a proof

**Objective:** learn to turn compiler observations into a justified repair action.

You will run supplied syntax/proof examples, read their raw Lean diagnostics,
and repair the proof of a fixed, correct checked-subtraction implementation.
You may change only the proof body; the implementation and required contract
stay fixed. The supplied command retains the observed goal and repaired run.

**Supplied system implementation:** isolated work directories, bounded process
execution, restricted Docker workers, time/memory/process limits, compiler
version checks, immutable attempt artifacts, and structured execution outcomes.
These are working support components, not learner implementation tasks.

The new concepts are hypotheses and goals, conditional simplification,
proof-only repair, and the distinction between a compiler observation and an
interpretation. Syntax and proof failures can share `ELABORATION_FAILED`; read
the logs to distinguish them. An unsolved goal alone does not show that a program
is wrong.

**Completion criterion:** the learner proof elaborates without weakening the
contract, and all reviewed diagnostic examples produce their expected outcomes.
`ELABORATED` is not the final `VERIFIED` verdict. No LLM is called yet.

---

## Exercise 4 — Understand and apply trusted acceptance

**Objective:** determine whether a candidate solved the original fixed task.

You will inspect contrasting Lean examples: valid solutions, direct/indirect
unfinished proofs, custom axioms, altered contracts, and missing declarations.
Construct and repair candidates exercising theorem correspondence and proof
dependencies. Check a counterexample against an inadequate contract.

**Supplied system implementation:** pinned challenge–solution checking,
Comparator integration, allowed definition holes, explicit permitted-axiom
configuration, fresh final checking, and retained acceptance records.

The new concepts are trusted challenges, transitive assumptions, specification
adequacy, and acceptance relative to an explicit policy.

**Completion criterion:** the candidate examples produce the expected acceptance
results. Only candidates satisfying the configured final policy receive
`VERIFIED`; an unavailable checker is an explicit non-success. This gate is
established before unrestricted model-generated Lean is introduced.

---

## Exercise 5 — Design the one-shot LLM flow

**Objective:** generate the first implementation-and-proof proposal automatically.

You will write the generation prompt, decide what task information the model
receives, and connect the load → generate → parse → check flow through the
supplied interfaces. Start with replayed output, then run a real model.

**Supplied system implementation:** replay and real-provider model adapters,
API configuration/transport, response parsing, command-line entry point, and
artifact persistence. Credentials remain outside the Lean worker.

The new concepts are prompt contracts, agent-visible information, structured
model proposals, and distinguishing provider errors from unsuccessful proofs.

**Completion criterion:** a replayed and real-model attempt preserve the task,
proposal, diagnostics, acceptance result, and resource observations. The model
need not solve every task. LLM generation begins in this exercise.

---

## Exercise 6 — Add verifier-guided repair decisions

**Objective:** turn one-shot generation into an iterative agent.

You will implement repair prompt content, attempt-state transitions, action
selection, and stopping behavior. Decide what evidence to send back and when a
proof-only revision is justified. Contrast a missing proof step with a checked
counterexample that establishes a behavioral defect.

**Supplied system implementation:** immutable attempt history, model calls,
resource accounting, budget guards, artifact storage, and deterministic replay
fixtures. Planning and malformed responses consume the same configured budgets.

The new concepts are feedback-driven control flow, bounded search, and the
difference between observed diagnostics and a proposed diagnosis.

**Completion criterion:** a replayed failed/corrected sequence follows the intended
actions, stays within all caps, preserves attempts, and stops immediately after
accepted success. Exercise the flow against the real model too.

---

## Exercise 7 — Write helpers and plan implementation with proof

**Objective:** handle tasks that need a stronger auxiliary theorem or a different
implementation strategy.

You will prove a generalized invariant for accumulator reversal, plan code and
proof structure together, and implement agent decisions among proof repair,
helper introduction, implementation redesign, and restart. The main theorem
remains unchanged.

**Supplied system implementation:** controlled helper assembly, helper dependency
checks under the same acceptance policy, logged actions, planning-call transport,
and resource accounting.

The new concepts are generalized invariants, modular proofs, and explicit repair
actions. A proof-only action must actually preserve the implementation.

**Completion criterion:** the helper supports the original contract, planning is
preserved and counted, and replayed actions obey their allowed edit scope.

---

## Exercise 8 — Audit Lean task contracts and reference solutions

**Objective:** create trustworthy development and evaluation data.

You will audit ten development tasks and twenty held-out tasks, check reference
solutions, document allowed-library policies, and justify the family split.
Contrast a complete sorting specification with one requiring only sorted output,
and a meaningful held-out task with a superficial renaming.

**Supplied system implementation:** task packaging/loading, reference-check
commands, provenance storage, and separate evaluator-controlled reference
locations inaccessible to the agent.

The new concepts are specification adequacy, algorithmic intent, leakage, and
benchmark integrity.

**Completion criterion:** every included task has an audited contract and checked
reference; the split and provenance are fixed before final evaluation.

---

## Exercise 9 — Design controlled strategy comparisons

**Objective:** compare generation and repair methods under comparable resources.

You will define one-shot, independent sampling, feedback repair, and
planning-plus-repair policies, choose matched budgets and repeated runs, and
interpret their outcomes. Make infrastructure reruns follow a predetermined
policy.

**Supplied system implementation:** experiment scheduling, common strategy
interfaces, result persistence, resource aggregation, and repeatable summary
commands.

The new concepts are baselines, matched budgets, repeated runs, and uncertainty.

**Completion criterion:** saved configurations reproduce a small comparison,
account for all relevant model work, and retain failed and expensive runs.
The full target remains ten development and twenty held-out tasks.

---

## Exercise 10 — Analyze repair traces and explain the results

**Objective:** turn the agent and its runs into an interpretable research artifact.

You will inspect representative successes/failures, distinguish changes to
implementation, proof, and helper structure, and test one predefined repair
policy variation. For example, compare staged proof-first repair with allowing
implementation redesign earlier. Treat the variation as a hypothesis.

**Supplied system implementation:** trace summaries, plotting/aggregation
commands, reproducibility checks, and release packaging.

The new concepts are ablations, evidence-based failure analysis, reproducibility,
and bounded conclusions.

**Completion criterion:** the final CLI and retained configurations reproduce the
reported analysis, and the report explains what helped, failed, and remains
unestablished. A negative result is acceptable.

---

# 13. How the project builds up

The exercise sequence has three milestones:

| Milestone | Exercises | Working capability |
|---|---|---|
| **Reliable checking infrastructure** | 1–4 | Load a task, check a proposed solution, and enforce acceptance rules |
| **An autonomous generation-and-repair agent** | 5–7 | Generate, verify, revise, and introduce proof-supporting structure |
| **A reproducible experimental project** | 8–10 | Evaluate strategies and explain their behavior |

The deliberately chosen order matters: **we build the acceptance process before relying on autonomous generation**.

---

# 14. What counts as completion?

## Engineering completion

You can run a command that supplies a fixed task to an LLM, obtains an implementation and proof, checks them, repairs unsuccessful attempts within a budget, and returns either an accepted artifact or an honest failure status.

The result is accompanied by enough information to reproduce what happened.

## Evaluation completion

You have compared the planned strategies under documented conditions and analyzed representative failures.

You can answer questions such as:

> Did verifier feedback help more than spending the same budget on independent attempts?

> Did proof-aware planning help specifically on tasks requiring generalized invariants?

> Did implementation rewrites solve genuine errors, or discard otherwise useful progress?

## What completion does not require

It does not require solving every task, training a new model, proving the Python controller itself correct, or producing a publishable new algorithm.

The repository will state which components are trusted and which guarantees have actually been checked.

---

# 15. The research direction after the core system works

The most promising extension remains:

\[
\boxed{
\text{When should an agent repair a proof, introduce a lemma,
or redesign the implementation?}
}
\]

Your first ten exercises will provide the infrastructure and traces needed to investigate that question.

A later contribution could use diagnostic evidence to choose repair actions more effectively. But the comparison must establish that the decision mechanism—not extra calls, more generous budgets, or weaker acceptance—causes the improvement.

**The project’s governing principle is simple: the LLM may explore and revise; the formal specification and acceptance rules remain fixed.**

Exercises 1–3 passed review. Exercise 4 is now current; follow its
[Lean acceptance-repair guide](../exercises/04-trusted-acceptance/README.md).
Remaining exercises are assessed through implementations and check results,
without written Q&A or reflection requirements.
