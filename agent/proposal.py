"""Exercise 2 starter: validate the two fields proposed by a future model."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re


MAX_BODY_BYTES = 32768
# This small preflight is deliberately conservative, including inside comments.
# It does not parse Lean or establish a semantic/security boundary.
DISALLOWED_WORDS = frozenset({
    "import", "namespace", "section", "end", "def", "theorem", "lemma",
    "axiom", "unsafe", "partial", "noncomputable", "sorry", "admit",
})


@dataclass(frozen=True)
class Proposal:
    implementation_body: str
    proof_body: str

    @classmethod
    def from_json(cls, text: str) -> Proposal:
        """Parse exactly the two named string fields; extra fields are rejected.

        Decode JSON, check its shape, then construct and validate an instance.
        """
        if not isinstance(text, str):
            raise ValueError("Proposal JSON must be a string")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid proposal JSON: {error.msg}") from error
        except RecursionError as error:
            raise ValueError("Proposal JSON is nested too deeply") from error

        fields = {"implementation_body", "proof_body"}
        if not isinstance(data, dict) or set(data) != fields:
            raise ValueError("Proposal must contain exactly implementation_body and proof_body")

        proposal = cls(
            implementation_body=data["implementation_body"],
            proof_body=data["proof_body"],
        )
        proposal.validate()
        return proposal

    def validate(self) -> None:
        """Perform bounded, predictable format/preflight checks on both bodies.

        Require nonempty strings, at most MAX_BODY_BYTES UTF-8 bytes per
        body, no whole-word DISALLOWED_WORDS, and no '#' command marker.
        Allow ordinary terms, local let/let rec helpers, and proof-local have.
        This method must also check Proposals created directly by callers.
        """
        for name in ("implementation_body", "proof_body"):
            body = getattr(self, name)

            if not isinstance(body, str) or not body.strip():
                raise ValueError(f"{name} must be a nonempty string")

            try:
                size = len(body.encode("utf-8"))
            except UnicodeEncodeError as error:
                raise ValueError(f"{name} must be valid UTF-8 text") from error
            if size > MAX_BODY_BYTES:
                raise ValueError(f"{name} exceeds {MAX_BODY_BYTES} UTF-8 bytes")

            if "#" in body:
                raise ValueError(f"{name} contains a disallowed # command marker")
            disallowed = set(re.findall(r"\b\w+\b", body)) & DISALLOWED_WORDS
            if disallowed:
                words = ", ".join(sorted(disallowed))
                raise ValueError(f"{name} contains disallowed words: {words}")
