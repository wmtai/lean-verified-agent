# Mini Project 1 — An LLM Agent for Verified Code Generation in Lean 4

Goal: Build an LLM agent that automatically generates a Lean program and a mathematical proof that the program satisfies a given specification.

The agent can make mistakes, receive feedback from Lean, and revise its solution until Lean accepts the program and proof or the agent runs out of attempts.

This project is an automated version of the verified code generation exercises you have just completed.

I'll explain the project from scratch, including the formal problem definition, inputs and outputs, an example, the agent architecture, implementation requirements, and possible research experiments.

## 1. What problem are we solving?

Suppose we want to implement a function that returns the maximum of two natural numbers.

We provide a mathematical specification:

\\[ \begin{aligned} S(p)\equiv\forall a,b\in\mathbb N,\quad & a\le p(a,b)\\\ {}\land\\;&b\le p(a,b)\\\ {}\land\\;&(p(a,b)=a\lor p(a,b)=b). \end{aligned} \\]

Here:

- \\(S\\) is the formal specification.
- \\(p\\) is the program we want to generate.
- \\(S(p)\\) is the proposition that \\(p\\) satisfies the specification.

Our goal is to build a system that produces:

\\[ \boxed{(p,\pi)} \\]

where:

\\[ \boxed{\pi:S(p)} \\]

In this project, both \\(p\\) and \\(\pi\\) are written in Lean 4.

- \\(p\\) is a Lean function implementing the required behavior.
- \\(\pi\\) is a Lean proof of its correctness.

We are not generating Python code and translating it into Lean. Python may be used to control the LLM and Lean compiler, but the programs being verified are written directly in Lean.

## 2. What does one successful solution look like?

For the maximum function, the agent might generate:

Generated program and proof

```

def my_max (a b : Nat) : Nat :=
  if a ≤ b then b else a

theorem my_max_correct (a b : Nat) :
    a ≤ my_max a b ∧
    b ≤ my_max a b ∧
    (my_max a b = a ∨ my_max a b = b) := by
  unfold my_max
  by_cases h : a ≤ b
  · simp [h]
  · simp [h]
    omega

```

The first declaration defines the program \\(p\\).

The second declaration provides the proof \\(\pi\\).

The Lean kernel checks the proof according to the formal rules of Lean's type theory.

Notice that this is not testing whether:

```
#eval my_max 3 7
```

returns `7`.

Instead, we establish the theorem for all natural-number inputs.

The agent succeeds only if it produces an accepted implementation and a valid proof against the original specification.

## 3. What exactly is the input to the agent?

Initially, I recommend using tasks whose specifications are already formally written in Lean.

This avoids combining two difficult problems: formalizing informal requirements and generating verified implementations.

Each task contains three essential elements.

### A. A fixed formal specification

For example, consider checked subtraction.

```
def CheckedSubSpec
    (f : Nat → Nat → Option Nat) : Prop :=
  (∀ a b, b ≤ a → f a b = some (a - b)) ∧
  (∀ a b, a < b → f a b = none)
```

This defines what constitutes correct behavior.

### B. An implementation hole

```
def candidate (a b : Nat) : Option Nat :=
  sorry
```

The agent must fill in the implementation.

### C. A proof hole

```
theorem candidate_correct :
    CheckedSubSpec candidate := by
  sorry
```

The agent must generate a proof of the specification.

Thus, the input task can be represented as:

\\[ T=(S,\text{signature},\text{constraints}). \\]

The constraints may prohibit certain library functions, require recursion, or restrict imports.

Crucially, the agent cannot modify the specification \\(S\\). It can modify only the implementation, its proof, and permitted helper declarations.

## 4. What exactly is the output?

The agent produces a Lean implementation and proof, together with a verification status.

A successful result might be:

```
Task: checked_subtraction

Program:
  candidate

Proof:
  candidate_correct

Status:
  VERIFIED

Attempts:
  3

Lean checks:
  3
```

A failed run should report something like:

```
Status:
  UNSOLVED_WITHIN_BUDGET
```

Failure to generate a proof does not necessarily mean the implementation is incorrect. It means the system did not establish correctness within its allowed resources.

# 5. The agent's complete workflow

Here is the proposed system.

Fixed Lean specification

Trusted problem supplied by the task designer

LLM

Generates Lean implementation + proof

Lean verifier

Elaborates code, checks proof, produces diagnostics

Accepted

Perform final trusted validation and save result

Not accepted

Collect diagnostics; revise and retry within budget

Agent repair loop

On failure, send relevant diagnostics to the LLM for another attempt

Let's go through a concrete execution.

## Step 1 — The LLM generates its first solution

Suppose the agent receives the checked-subtraction task and produces:

```
def candidate (a b : Nat) : Option Nat :=
  some (a - b)
```

This implementation is wrong.

For example, when \\(a=3\\) and \\(b=5\\):

\\[ candidate(3,5)=\operatorname{some}(0) \\]

but the specification requires:

\\[ candidate(3,5)=\operatorname{none}. \\]

The LLM may also generate a proof attempt, but it cannot produce an ordinary valid proof of this false specification under the trusted assumptions.

## Step 2 — Lean checks the generated program and proof

The agent submits its code and proof to Lean.

Lean may report a remaining goal resembling:

```
a b : Nat
h : a < b
⊢ some (a - b) = none
```

This is an illustration of the proof obligation, not a verbatim diagnostic from an actual execution.

The system now knows that the attempt did not verify.

An additional testing or counterexample-search component might identify `a = 3, b = 5` as a concrete failure. Lean does not automatically provide such a counterexample for every failed proof.

## Step 3 — The agent receives feedback

The controller sends a repair request to the LLM containing the original fixed specification, previous candidate, and relevant Lean error.

For example:

```
Your previous solution did not verify.

The implementation always returns some value,
including when b > a.

The specification requires none when b > a.

Revise the Lean implementation and proof.
Do not change the specification.
```

The message may contain a checked counterexample when one is available.

## Step 4 — The LLM repairs its solution

A corrected solution could be:

```
def candidate (a b : Nat) : Option Nat :=
  if b ≤ a then some (a - b) else none

theorem candidate_correct :
    CheckedSubSpec candidate := by
  unfold CheckedSubSpec
  constructor
  · intro a b h
    simp [candidate, h]
  · intro a b h
    have hnot : ¬ b ≤ a := by omega
    simp [candidate, hnot]
```

The model has now changed both the implementation and the proof.

## Step 5 — Final verification

The system checks the revised implementation against the original trusted specification.

If the proof passes the required acceptance checks, the system records success.

It must also reject attempts that alter trusted declarations, depend on unacceptable axioms or unfinished proofs, or otherwise bypass the intended contract.

The model is allowed to be wrong during generation. The acceptance process must not treat an unverified claim as correct.

# 6. Why is this a research problem?

A basic generation-and-repair loop is relatively straightforward to build.

The research challenge is that not all verification failures require the same kind of repair.

Consider three examples.

### Example A — The program is wrong

```
def my_max (a b : Nat) : Nat :=
  a
```

The implementation is wrong whenever `b > a`.

More proof attempts will not make it correct.

Required action: Change the implementation.

### Example B — The program is correct, but the proof is incomplete

```
def my_double (n : Nat) : Nat :=
  n + n
```

The theorem is true:

\\[ my\\\_double(n)=2n. \\]

But the agent may attempt a tactic that does not establish it.

Required action: Repair the proof while preserving the implementation.

### Example C — The proof needs a stronger invariant

Consider accumulator-based list reversal.

A weak induction attempt might target only:

\\[ reverseAux(xs,[])=xs.reverse. \\]

But the recursive call changes the accumulator.

The more useful invariant is:

\\[ \boxed{ \forall acc,\quad reverseAux(xs,acc)=xs.reverse++acc } \\]

Required action: Generalize the theorem or introduce a helper lemma.

This is more sophisticated than simply retrying a tactic.

The challenge is determining which situation applies.

# 7. What strategies should you compare?

This is where the mini project becomes an experiment.

I recommend four systems using the same underlying LLM.

| Method                    | How it works                                                                                 |
| ------------------------- | -------------------------------------------------------------------------------------------- |
| A. One-shot generation    | Generate one implementation and proof; check once                                            |
| B. Independent sampling   | Generate fresh code-and-proof pairs without feedback from previous attempts                  |
| C. Verifier-guided repair | Revise the existing implementation or proof using Lean diagnostics                           |
| D. Proof-aware planning   | Plan the algorithm, invariants, and proof structure before generation, then repair if needed |

The fourth approach is related to work such as P³ on joint program-and-proof planning; therefore, the basic idea of planning both together is not novel.

Your experiment would investigate their behavior under controlled conditions.

### Example: Accumulator reversal

| Method               | Possible behavior                                                      |
| -------------------- | ---------------------------------------------------------------------- |
| One-shot             | Generates working recursion but fails the proof                        |
| Independent sampling | Tries several implementations                                          |
| Repair               | Repeatedly changes tactics, possibly discovers the invariant           |
| Proof-aware planning | Identifies the generalized accumulator invariant before implementation |

These are hypothetical behaviors, not established outcomes.

The objective is to determine what actually happens in experiments.

# 8. How should you measure performance?

The primary metric should be verified solve rate.

For a set of tasks \\(D\\):

\\[ \boxed{ \operatorname{SolveRate} = \frac{\text{Number of tasks with accepted implementations and proofs}} {\text{Total number of tasks}} } \\]

But solve rate alone is insufficient.

You should also measure:

| Metric                    | What it tells you                       |
| ------------------------- | --------------------------------------- |
| Verified solve rate       | How often the system succeeds           |
| Number of LLM calls       | Generation and repair effort            |
| Token usage               | Inference cost                          |
| Number of Lean checks     | Verification effort                     |
| Time to verified solution | End-to-end efficiency                   |
| Implementation revisions  | How often the agent rewrites code       |
| Proof revisions           | How often the agent repairs only proofs |
| Failure categories        | Where the system struggles              |

### Fair comparison

Suppose Method C gets five repair attempts, but Method A gets only one attempt.

If C performs better, we cannot conclude that repair feedback caused the improvement. It may simply benefit from having five attempts.

Therefore, the crucial comparison is:

\\[ \boxed{ \text{Verifier-guided repair} \quad\text{versus}\quad \text{independent sampling} } \\]

under comparable total model and verification budgets.

Planning must also count toward the budget.

# 9. What tasks should you use?

You already have suitable development examples from the course.

I recommend an initial collection of approximately 10 tasks for debugging the agent, followed by a separate set of 20–30 audited evaluation tasks.

| Task category          | Example              | Main verification challenge |
| ---------------------- | -------------------- | --------------------------- |
| Arithmetic             | Checked subtraction  | Preconditions and branches  |
| Arithmetic             | Clamping             | Multiple properties         |
| Lists                  | Append               | Structural induction        |
| Lists                  | Mapping              | Higher-order functions      |
| Lists                  | Filtering            | Membership and preservation |
| Lists                  | Reversal             | Recursive correctness       |
| Lists                  | Accumulator reversal | Generalized invariants      |
| Data structures        | Certified search     | Dependent values            |
| Algorithms             | Insertion sort       | Multiple helper lemmas      |
| Program transformation | Constant folding     | Semantic preservation       |

Your existing exercises are especially useful for validating the workflow because you know what correct solutions look like.

However, don't use the same familiar exercises as the sole evidence of generalization. A held-out evaluation should use different contracts or algorithmic families, not simply renamed versions.

A later stage could use curated tasks from Lean verified-code-generation benchmarks such as VERINA.

# 10. What software do you need to build?

I would implement the agent in Python and keep Lean as the language of generated code and proofs.

The main components are:

Task manager

Stores fixed specifications, function signatures, permitted edits, and task metadata.

LLM agent

Generates Lean implementations, proof scripts, and revisions.

Lean runner

Checks generated files and returns diagnostics from Lean.

Trusted acceptance checker

Ensures the original theorem and dependencies are preserved, with no unacceptable proof shortcuts.

Experiment logger

Records code, errors, proof attempts, costs, and final outcomes.

A possible repository is:

```
lean-verified-agent/
├── tasks/
│   ├── checked_subtraction/
│   ├── list_reverse/
│   └── insertion_sort/
├── agent/
│   ├── model_client.py
│   ├── prompts.py
│   ├── repair.py
│   └── controller.py
├── verifier/
│   ├── lean_runner.py
│   └── acceptance.py
├── experiments/
│   ├── evaluate.py
│   └── analyze.py
└── results/
```

Initially, the controller can simply run Lean on complete candidate files and collect the diagnostics.

For acceptance, the system must check more than a zero compiler exit code. In particular, the model must not be able to weaken the specification or modify trusted definitions. Untrusted generated Lean should be checked in an isolated environment with resource limits, because elaboration and metaprogramming can execute code.

# 11. What is the actual research contribution?

I would distinguish two stages.

Stage 1 — Engineering project

Build a functioning LLM agent that generates Lean code and proofs, receives verifier feedback, and automatically repairs attempts.

This demonstrates technical competence, but the basic workflow already exists in previous research.

Stage 2 — Research project

Investigate a question such as:

> When Lean verification fails, how should an agent decide whether to repair the proof or redesign the implementation?

A more formal formulation is:

Suppose the agent has attempted solution \\((p_t,\pi_t)\\) and receives verification feedback \\(e_t\\).

It must choose an action:

\\[ a_t\in \\{ \text{repair proof}, \text{modify program}, \text{introduce lemma}, \text{replan} \\}. \\]

The objective is to maximize the probability of producing an accepted implementation and proof before exhausting the budget:

\\[ \boxed{ \max\_{\text{agent policy}} \Pr\left( \exists t\le B: \operatorname{Accept}(S,p_t,\pi_t) \right) } \\]

Here, \\(B\\) can represent a fixed resource budget, while `Accept` denotes the full trusted acceptance procedure, not merely a model prediction.

You can initially use a rule-based decision mechanism. Only later consider learning a policy from verification traces.

To claim a contribution, compare against unrestricted repair, independent sampling, and fixed strategies. The question is whether better decision-making produces more verified solutions at comparable cost.

# 12. Recommended implementation roadmap

## 1

Build a single-task prototype

Automate your checked-subtraction exercise. Have the model fill implementation and proof holes, check them with Lean, and record the result.

## 2

Add automatic repair

Return Lean diagnostics after unsuccessful attempts. Give the agent a maximum number of tries, such as five, and preserve the full attempt history.

## 3

Add audited tasks and safety checks

Expand to recursive programs and helper lemmas. Ensure the agent cannot alter specifications, introduce disallowed axioms, or obtain acceptance through unfinished proofs.

## 4

Conduct controlled experiments

Compare independent sampling, error-guided repair, and proof-aware planning on held-out tasks under matched budgets.

## 13. What would make the project successful?

There are two different success criteria.

Engineering success: You have a working repository in which an LLM receives a fixed Lean specification, generates code and proof, receives diagnostics, and eventually produces a verified artifact or reports failure.

Research success: You demonstrate, with controlled comparisons, that a particular decision-making or repair mechanism improves verified solve rate, resource efficiency, or failure diagnosis beyond established baselines.

Even if the agent does not outperform a baseline, a systematic analysis of why it fails can be useful—for example, distinguishing incorrect implementations from missing invariants or inadequate proof search.

## Final picture

Project 1 in one diagram

The agent can revise its implementation and proof, but the trusted specification remains unchanged. Final acceptance requires independent verification.

The essence of Project 1: You are not trying to prove that an LLM is always correct. You are building a system in which an unreliable LLM searches for a solution, while a trusted verification process determines whether a candidate satisfies the fixed requirement.

I recommend beginning with one LLM, one Lean task, and one automated repair loop. After that works, the most interesting research direction is studying how the agent decides what to repair when verification fails.
