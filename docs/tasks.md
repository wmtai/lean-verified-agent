# Task corpus

The repository ships ten development tasks. They exercise the generation and
repair pipeline and have known reference solutions; they are not a held-out
benchmark. The evaluation manifest is deliberately empty. No research solve rate
or claim of generalization should be reported from these fixtures alone.

| ID | Contract | Main proof obligation |
| --- | --- | --- |
| `checked_subtraction` | Return `some (a - b)` when subtraction is defined, otherwise `none` | Preconditions and comparison branches |
| `maximum` | Bound both inputs and return one of them | Arithmetic inequalities and an output witness |
| `clamp` | Stay in a valid interval, preserve in-range values, select endpoints outside it | Several conditional properties |
| `doubling` | Agree with multiplication by two | Arithmetic normalization |
| `list_append` | Agree with list concatenation | Structural induction |
| `list_map` | Agree with mapping any supplied function | Higher-order structural induction |
| `list_filter` | Agree with filtering any Boolean predicate | Branches within structural induction |
| `list_reverse` | Agree with list reversal | Structural induction and append |
| `accumulator_reverse` | Agree with list reversal through an accumulator worker | Generalize the invariant to every accumulator |
| `constant_folding` | Preserve evaluation under every variable environment and fold literal addition | Expression induction and recursive case analysis |

Each `tasks/<id>/task.json` stores only the fixed problem: its identifier, title,
category, split, Lean specification, declaration signature, constraints, and
forbidden implementation identifiers. `reference.json` is a separate development
fixture containing the same `implementation` and `proof` fields the model must
produce. Model prompts receive the task contract and do not load reference files.

The verifier renders `import Std`, a `Generated` namespace, the trusted
specification, `def candidate <signature> := <implementation>`, and
`theorem candidate_correct : Spec candidate := <proof>`. Both output fields are
terms; global helper declarations are outside the interface. Local recursive
functions and proof-local `have` statements provide the needed helpers. Lean may
give a local recursive worker an internal name such as `candidate.go`; proofs can
refer to that generated name.

Library restrictions apply to the implementation, not the trusted specification
or the proof. For example, the accumulator reversal contract and its proof use
`List.reverse`, while its implementation uses a local recursive accumulator
worker. Structural list references use local recursive functions so their
definitions also pass Lean's code generator. Prose algorithm constraints
require task-design review; the identifier denylist is a guardrail, not a general
semantic checker for arbitrary Lean programs or equivalent notation.

`examples/checked_subtraction_repair.json` contains two real candidate attempts.
The first always returns `some` and its proof leaves an impossible branch goal.
The second changes the branch and supplies an `omega` proof of the missing
inequality. A replay runs both through the same verifier used for model output;
the recorded fixture does not declare either candidate accepted.

To add a task, create a fresh directory and a formal `Spec`, add the identifier to
one manifest, validate its reference solution with the pinned Lean toolchain, and
review the contract and implementation constraints. Keep references separate from
model inputs. Before a research evaluation, assemble and independently audit
20–30 new tasks with different contracts or algorithmic families, freeze their
specification hashes, inspect reference theorem dependencies, and keep them
separate from development and prompt design. Run all strategies with the same
model and comparable call, token, verification, and time budgets; planning calls
consume that budget too.
