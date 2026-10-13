# Trusted acceptance

Task JSON is trusted input maintained by the task designer. The provider sees
the fixed contract, signature, and constraints, but never `reference.json`.
Task hashes in traces identify the exact supplied contract. A task author can
make a vacuous or incorrect specification; kernel acceptance cannot correct
that design error.

Candidates contain implementation and proof expressions. Python first applies
the conservative lexical policy, then encodes each body as an escaped Lean
string literal in a fixed `#checked_candidate` command. Candidate text is never
pasted into the surrounding command source. Quotes, backslashes, newlines, and
control characters in comments remain data during this transport.

Inside the verifier process, the trusted command uses Lean's term parser on
each decoded body. The parser requires exactly one complete term and rejects
errors or trailing input. Both bodies must parse before either is elaborated.
The command then splices the parsed term syntax into controller-owned
`def candidate <signature> := <implementation>` and
`theorem candidate_correct : Spec candidate := <proof>` declarations. A term
cannot close a source wrapper and become an extra top-level command. The fixed
specification, signature, names, imports, and final assertion of
`Spec candidate` remain trusted. Local recursion and proof-local invariants
remain available.

This structural boundary does not rely on enumerating every Lean command
keyword. Lexical checks still restrict forbidden terms, metaprogramming,
strings, and quoted identifiers in candidate code. Parsing a single term does
not by itself establish proof correctness or the safety of every tactic;
the dependency audit and isolated execution remain necessary.

The trusted Lean audit recursively inspects constants used by both the
implementation and proof, rejects unsafe definitions and axioms outside the
explicit logical allowlist, and emits its acceptance marker only on success.
The Python controller requires the marker and a successful process exit, then
rechecks the same assembled source in a fresh process before reporting
`VERIFIED`. A model assertion or successful executable test is never enough.

Task-specific `forbidden_identifiers` are checked against the implementation,
so a proof may still refer to library operations in its fixed specification.
Prose constraints such as “use structural recursion” express task intent;
they are not automatically enforced by a complete semantic program analysis.
Identifier restrictions can be bypassed by equivalent notation or aliases.
Audit constraints manually or add dependency-based checks before measuring
constraint compliance in research results.

The Docker runner mounts candidate source read-only and supplies trusted
modules from its image. It provides no host credentials, network access, or
Docker socket to generated code. Process limits and wall timeouts bound common
resource failures. This assumes a trusted image, working Docker isolation,
and the operating system/container runtime; it is not a guarantee against
runtime or compiler vulnerabilities. Local mode is explicitly unsandboxed.

Lean's [validation guide](https://lean-lang.org/doc/reference/latest/ValidatingProofs/)
distinguishes axiom audits from stronger checks of adversarial proofs. This
repository uses restricted expressions, trusted imports, dependency audits,
and repeated elaboration. For unrestricted generated Lean, add serialized
proof export and comparison against a separate trusted challenge with
`comparator` and an external kernel. A second elaboration with the same
compiler is a consistency check, not an independent proof-checker implementation.

Each failed Lean invocation is counted. Python lexical-policy failures use no
Lean check; a term-boundary rejection inside Lean uses one and is reported as
`policy_rejected`, allowing repair within the remaining budget. A successful
candidate uses two checks. Model/API failures, missing compilers,
and inaccessible Docker images are infrastructure errors, not evidence that
the mathematical contract is unprovable.

The CI Docker job runs reviewed term-boundary fixtures from
`tests/test_candidate_boundary.py`. They cover declaration insertion and
trailing input in both bodies, parsing both bodies before elaboration, literal
transport, local recursion/invariants, and a rejection followed by successful
repair. To repeat them after changing the trusted module:

```bash
bash scripts/build-verifier.sh
RUN_LEAN_INTEGRATION=1 LEAN_TEST_BACKEND=docker \
  python3 -m unittest discover -s tests -p test_candidate_boundary.py -v
python3 -m agent check-fixtures
python3 -m agent demo
```

Rebuild the image whenever `lean/Trusted/Audit.lean` changes: its compiled module
is baked into the image. A stale image does not contain the updated trusted
command. For these reviewed fixtures on the pinned local compiler, select
`LEAN_TEST_BACKEND=local` and set `LEAN_BINARY=/path/to/lean` instead.
