"""Load immutable trusted task snapshots and check template consistency."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re


_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]*")
_LEAN_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
_BODY_FIELDS = {"implementation_body", "proof_body"}


def _object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _strings(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list of strings")
    return tuple(_string(item, f"{label}[{index}]") for index, item in enumerate(value))


def _name(value: object, label: str) -> str:
    name = _string(value, label)
    if not _LEAN_NAME.fullmatch(name):
        raise ValueError(f"{label} must be a dotted Lean identifier")
    return name


def _local_path(root: Path, value: object, label: str) -> Path:
    relative = Path(_string(value, label))
    if relative.is_absolute():
        raise ValueError(f"{label} must be relative to the repository")
    try:
        path = (root / relative).resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError(f"Cannot resolve {label}: {error}") from error
    if not path.is_relative_to(root):
        raise ValueError(f"{label} must stay inside the repository")
    return path


def _read_source(root: Path, value: object, label: str) -> str:
    path = _local_path(root, value, label)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(f"Cannot read {label}: {error}") from error
    if not source.strip():
        raise ValueError(f"{label} must not be empty")
    return source


def _without_comments(source: str) -> str:
    """Skip nested block/line comments for the template's textual checks.

    This is deliberately not a general Lean parser. The trusted template has
    declaration headers and two placeholders, rather than arbitrary terms.
    """
    result = []
    index = depth = 0
    while index < len(source):
        pair = source[index:index + 2]
        if pair == "/-":
            depth += 1
            result.append(" ")
            index += 2
        elif pair == "-/":
            if not depth:
                raise ValueError("Template has an unmatched closing block comment")
            depth -= 1
            result.append(" ")
            index += 2
        elif depth:
            result.append("\n" if source[index] == "\n" else " ")
            index += 1
        elif pair == "--":
            newline = source.find("\n", index)
            if newline < 0:
                break
            result.append("\n")
            index = newline + 1
        else:
            result.append(source[index])
            index += 1
    if depth:
        raise ValueError("Template has an unclosed block comment")
    return "".join(result)


@dataclass(frozen=True)
class PublicExample:
    arguments: tuple[int, ...]
    expected: str


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    family: str
    specification_module: str
    specification_declaration: str
    specification_source: str
    implementation_header: str
    implementation_type: str
    theorem_header: str
    template_source: str
    permitted_imports: tuple[str, ...]
    public_examples: tuple[PublicExample, ...]
    lean_toolchain: str
    metadata_json: str

    @classmethod
    def load(cls, root: Path, task_id: str, split: str = "development") -> Task:
        """Load root/tasks/<split>/<task_id>/task.json and its trusted sources.

        Raise ValueError with a useful message for invalid or missing task data.
        See exercises/02-tasks-and-submissions/README.md for the field mapping.
        """
        if not isinstance(split, str) or split not in {"development", "evaluation"}:
            raise ValueError("Task split must be development or evaluation")
        if not isinstance(task_id, str) or not _IDENTIFIER.fullmatch(task_id):
            raise ValueError("Task id must be a lowercase identifier")
        try:
            root = Path(root).resolve()
        except (TypeError, OSError, RuntimeError) as error:
            raise ValueError(f"Invalid repository root: {error}") from error

        source = _read_source(root, f"tasks/{split}/{task_id}/task.json", "task metadata")
        try:
            metadata = _object(json.loads(source), "Task metadata")
        except (json.JSONDecodeError, RecursionError) as error:
            raise ValueError("Task metadata must contain valid JSON") from error
        if type(metadata.get("schema_version")) is not int or metadata["schema_version"] != 1:
            raise ValueError("Task metadata requires schema_version 1")
        if _string(metadata.get("id"), "id") != task_id:
            raise ValueError("Task metadata id must match its directory")
        regions = _strings(metadata.get("editable_regions"), "editable_regions")
        if len(regions) != 2 or set(regions) != _BODY_FIELDS:
            raise ValueError("Editable regions must be implementation_body and proof_body")

        specification = _object(metadata.get("specification"), "specification")
        declarations = _object(metadata.get("required_declarations"), "required_declarations")
        implementation = _object(declarations.get("implementation"), "implementation declaration")
        correctness = _object(declarations.get("correctness"), "correctness declaration")
        environment = _object(metadata.get("environment"), "environment")

        implementation_name = _name(implementation.get("name"), "implementation name")
        correctness_name = _name(correctness.get("name"), "correctness name")
        implementation_header = _string(implementation.get("header"), "implementation header")
        correctness_type = _string(correctness.get("type"), "correctness type")
        theorem_header = _string(correctness.get("header"), "correctness header")
        if (not implementation_header.startswith(f"def {implementation_name} ")
                or not implementation_header.endswith(":=")):
            raise ValueError("Implementation header must define its required declaration name")
        if theorem_header != f"theorem {correctness_name} : {correctness_type} :=":
            raise ValueError("Theorem header must match its required name and type")

        imports = _strings(metadata.get("permitted_imports"), "permitted_imports")
        for module in imports:
            _name(module, "permitted import")
        _local_path(root, environment.get("lake_project"), "Lake project")
        _strings(environment.get("dependencies"), "environment dependencies")

        raw_examples = metadata.get("public_examples")
        if not isinstance(raw_examples, list):
            raise ValueError("public_examples must be a list")
        examples = []
        for index, value in enumerate(raw_examples):
            example = _object(value, f"public_examples[{index}]")
            arguments = example.get("arguments")
            if (not isinstance(arguments, list)
                    or any(type(argument) is not int or argument < 0 for argument in arguments)):
                raise ValueError(f"public_examples[{index}].arguments must be nonnegative integers")
            examples.append(PublicExample(
                arguments=tuple(arguments),
                expected=_string(example.get("expected"), f"public_examples[{index}].expected"),
            ))

        try:
            metadata_json = json.dumps(metadata, sort_keys=True, ensure_ascii=False, allow_nan=False)
            metadata_json.encode("utf-8")
        except (ValueError, RecursionError) as error:
            raise ValueError("Task metadata must contain finite JSON values and valid Unicode") from error

        task = cls(
            id=task_id,
            title=_string(metadata.get("title"), "title"),
            family=_string(metadata.get("family"), "family"),
            specification_module=_name(specification.get("module"), "specification module"),
            specification_declaration=_name(specification.get("declaration"), "specification declaration"),
            specification_source=_read_source(root, specification.get("path"), "specification source"),
            implementation_header=implementation_header,
            implementation_type=_string(implementation.get("signature"), "implementation signature"),
            theorem_header=theorem_header,
            template_source=_read_source(root, metadata.get("candidate_template"), "candidate template"),
            permitted_imports=imports,
            public_examples=tuple(examples),
            lean_toolchain=_string(environment.get("lean_toolchain"), "Lean toolchain"),
            metadata_json=metadata_json,
        )
        task.validate_template()
        return task

    def validate_template(self) -> None:
        """Check fixed headers/imports and exactly one placeholder for each body.

        Reject missing/duplicate/unknown placeholders, changed headers,
        and imports outside permitted_imports. These are textual checks only.
        """
        source = _string(self.template_source, "template_source")
        placeholders = re.findall(r"\{\{(.*?)\}\}", source, flags=re.DOTALL)
        if len(placeholders) != 2 or set(placeholders) != _BODY_FIELDS:
            raise ValueError("Template must contain exactly the two body placeholders once each")
        lines = [line.strip() for line in _without_comments(source).splitlines() if line.strip()]
        for header, body in (
            (self.implementation_header, "implementation_body"),
            (self.theorem_header, "proof_body"),
        ):
            _string(header, f"{body} header")
            if lines.count(header) != 1:
                raise ValueError(f"Template must contain the exact fixed {body} header once")
            index = lines.index(header)
            if index + 1 >= len(lines) or lines[index + 1] != "{{" + body + "}}":
                raise ValueError(f"{body} placeholder must immediately follow its fixed header")

        imports = []
        for line in lines:
            if re.match(r"^import\b", line):
                modules = line.split()[1:]
                if not modules:
                    raise ValueError("Template import must name a module")
                for module in modules:
                    _name(module, "template import")
                    if module not in self.permitted_imports:
                        raise ValueError(f"Template import is not permitted: {module}")
                imports.extend(modules)
        if self.specification_module not in imports:
            raise ValueError("Template must import its trusted specification module")

    @property
    def digest(self) -> str:
        """Return a portable SHA-256 digest of the immutable task snapshot.

        Hash canonical metadata plus specification_source and
        template_source. File-system locations must not affect the digest.
        Hash stored content rather than rereading files after loading.
        """
        snapshot = {
            "metadata": json.loads(self.metadata_json),
            "specification_source": self.specification_source,
            "template_source": self.template_source,
        }
        encoded = json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                             allow_nan=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
