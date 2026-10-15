# Exercise 1 — Build a reproducible project environment

**This exercise passed review.** The current lesson is
[Exercise 2](../02-tasks-and-submissions/README.md). This first exercise covers
a working Python–Lean project, two contrasting implementations, and a manually
written solution. Say
**OK** when its completion checklist is satisfied to request a review. After
feedback and a passing review, say **OK** again to advance. Exercise 2 will then
extend this repository with structured tasks and candidate assembly.

## What you will learn

A Lean implementation is a program. Its correctness theorem is a separate claim
about that program. Python starts the Lean process, captures its diagnostics, and
records what happened; Python is not translating the implementation into Lean or
proving the theorem itself.

A reproducible environment fixes the compiler and project configuration so that
the same source can be checked under the same assumptions. This exercise pins
Python **3.12.15** and Lean **4.34.1**. Python uses its standard library, so the
runtime dependency list is intentionally empty. The Lake configuration builds
the trusted task specification as a library that the fixtures can import.

The exercise uses reviewed fixtures. Restricted execution and final acceptance
are introduced in Exercises 3 and 4, before relying on model-generated Lean.

## Editor setup

In VS Code, open the entire `lean-verified-agent` repository with **File →
Open Folder**, then open `starter/Candidate.lean` below. The repository-root
`lakefile.toml` and `lean-toolchain` allow the Lean extension to discover the
same environment used by the command-line checks. Run `lake build` from the
repository root to build the imported task module.

If you see `unknown module prefix 'tasks'`, build the project and reload the
editor window with **Developer: Reload Window**. A plain `lean` command outside
Lake's environment can also miss the task imports; use `lake env lean` for
manual file checks as shown below.

## 1. Set up the tools

Install [`uv`](https://docs.astral.sh/uv/getting-started/installation/) if needed,
then run the following from the repository root:

```bash
uv sync --locked --python 3.12.15
.venv/bin/python --version
```

For Lean, use [`elan`](https://github.com/leanprover/elan#installation) with the
toolchain in `lean-toolchain`, or a standalone Lean 4.34.1 installation.
Install your chosen Lean toolchain manager if needed. The checker records the compiler
actually used rather than assume that an executable name implies the right
version.

Run the reviewed environment check:

```bash
.venv/bin/python -m scripts.check_environment \
  --report runs/exercise01/environment.json
```

If elan is installed but Lake is not on `PATH`, select its executable explicitly:

```bash
.venv/bin/python -m scripts.check_environment \
  --lake "$HOME/.elan/bin/lake" \
  --report runs/exercise01/environment.json
```

For a standalone installation, pass its actual Lake executable path to `--lake`.
You can instead set `LAKE_BINARY` to that executable. Use the same installation
for your manual commands. The commands below assume `lake` is on `PATH`; when
using `LAKE_BINARY`, replace `lake` with `"$LAKE_BINARY"`.

Open `runs/exercise01/environment.json` after the check. Inspect the tool versions,
configuration and fixture outcomes. Generated reports belong in `runs/`.

## 2. Read the fixed specification

Open
[Specification.lean](../../tasks/development/checked_subtraction/Specification.lean).
Its central contract is:

```lean
def CheckedSubSpec
    (f : Nat → Nat → Option Nat) : Prop :=
  (∀ a b, b ≤ a → f a b = some (a - b)) ∧
  (∀ a b, a < b → f a b = none)
```

The two conjunction branches describe all natural-number inputs. Subtraction on
`Nat` truncates at zero, so the function uses `Option Nat` to distinguish a
defined subtraction from an input outside its precondition. For example,
`f 5 3` must return `some 2`, while `f 3 5` must return `none`. Equality is also
defined: `f 3 3` must return `some 0`.

Treat this specification as the fixed challenge. The starter gives you the
implementation and proof holes; changing the challenge would solve a different
task. The metadata and template beside the specification document that boundary.
Their general-purpose loader and renderer are Exercise 2 work.

## 3. Understand the three fixture outcomes

| Reviewed file | What Lean is asked to check | Expected observation |
| --- | --- | --- |
| [Correct.lean](fixtures/Correct.lean) | An implementation and a proof of the fixed contract | Lean succeeds with a completed theorem. |
| [WrongImplementation.lean](fixtures/WrongImplementation.lean) | The expression `some (a - b)` as an implementation | Lean succeeds: the function is well typed. |
| [WrongProof.lean](fixtures/WrongProof.lean) | That wrong implementation with an attempted proof of the fixed contract | Lean fails to establish the theorem. |

For the wrong implementation, `candidate 3 5` produces `some 0`, while the contract
requires `none`. That explicit input explains the behavioral error. In general,
a failed proof attempt alone does not establish an incorrect implementation.

You can reproduce the checks directly. Start at the repository root:

```bash
lake build
lake env lean exercises/01-environment/fixtures/Correct.lean
lake env lean exercises/01-environment/fixtures/WrongImplementation.lean
lake env lean exercises/01-environment/fixtures/WrongProof.lean
```

The last command is expected to return a nonzero exit code and diagnostics about
the unsuccessful proof. Read them. The environment checker treats this expected
failure as part of a successful exercise baseline.

## 4. Work through the correct implementation and proof

The correct implementation makes the precondition explicit:

```lean
def candidate (a b : Nat) : Option Nat :=
  if b ≤ a then some (a - b) else none
```

An appropriate theorem proof is:

```lean
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

`unfold` exposes the two properties in the specification. `constructor` splits
the conjunction. In the first branch, `h : b ≤ a` selects the `some` branch, and
`simp` unfolds the implementation and reduces the conditional. In the second,
`h : a < b` implies `¬ b ≤ a`; `omega` establishes that arithmetic fact, after
which `simp` selects `none`.

The theorem statement still refers to the original trusted specification. The
implementation and proof can be developed independently, but both must fit that
statement.

## 5. Complete the starter

Edit [starter/Candidate.lean](starter/Candidate.lean). Replace its implementation
and proof placeholders while preserving the import, required signature and
theorem statement. Use the worked example to understand each step, and inspect
the reviewed correct fixture when you need a complete file example.

Check your file manually from the repository root:

```bash
lake build
lake env lean exercises/01-environment/starter/Candidate.lean
```

Lean may exit successfully for a file containing `sorry`, accompanied by a
warning. A placeholder is unfinished work. Replace both holes and check that
your completed file has no `sorry` warnings. The environment checker intentionally
checks the reviewed fixtures; it does not execute the learner file or certify it
as a final accepted agent artifact.

## 6. Run the tests and record completion

From the repository root:

```bash
.venv/bin/python -m unittest discover -s tests -v
RUN_LEAN_INTEGRATION=1 .venv/bin/python -m unittest discover -s tests -v
```

The first command runs the ordinary Python checks and skips the real Lean
integration tests. The second includes those tests and requires the pinned Lake
installation. Set `LAKE_BINARY` if it is not on `PATH`.

Complete the exercise when:

- [ ] The recorded Python and Lean versions match the pinned configuration.
- [ ] The trusted task library builds.
- [ ] The correct implementation and theorem compile.
- [ ] The wrong implementation compiles on its own.
- [ ] The wrong implementation's attempted contract proof fails as expected.
- [ ] Your starter implementation and proof compile without `sorry` warnings.
- [ ] The tests pass with real Lean integration enabled, and the environment JSON
      report records the reviewed outcomes.
- [ ] You can explain why a well-typed implementation can fail its fixed contract.

Keep the report and your completed starter. Say **OK** for review. After a
passing review and feedback, say **OK** again to proceed to Exercise 2. If fixes
are needed, stay on this exercise and have the revised implementation reviewed.

The [roadmap](../../docs/roadmap.md) describes the remaining exercises. Those ten
implementation exercises are separate from the ten development and twenty
held-out programming tasks in the eventual agent benchmark.
