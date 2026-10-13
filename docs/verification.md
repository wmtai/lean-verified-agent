# Trusted acceptance

Task JSON is trusted input maintained by the task designer. The provider sees
the fixed contract, signature, and constraints, but never `reference.json`.
Task hashes in traces identify the exact supplied contract. A task author can
make a vacuous or incorrect specification; kernel acceptance cannot correct
that design error.

Candidates contain implementation and proof expressions. The assembler owns
the surrounding declarations and final assertion of `Spec candidate`.
Candidates cannot supply imports, theorem statements, or new top-level helper
declarations. Local recursion and local invariant proofs remain available.
Policy checks reject forbidden terms, commands, custom elaboration, strings
and quoted identifiers where necessary to keep this restricted format small.

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

Each failed Lean invocation is counted. Policy failures use no Lean check.
A successful candidate uses two checks. Model/API failures, missing compilers,
and inaccessible Docker images are infrastructure errors, not evidence that
the mathematical contract is unprovable.
