"""Shared live-model configuration, loaded from the repository .env file."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit


DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_API_URL = "https://api.openai.com/v1/responses"


def read_dotenv(path: Path) -> dict[str, str]:
    """Read literal KEY=value lines without executing code or expanding variables.

    Single/double quoted values and comments are supported. Error messages
    identify line numbers but never echo values that might contain credentials.
    """
    if not path.exists():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise ValueError("Cannot read the .env configuration file") from None
    values = {}
    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid .env assignment on line {number}")
        if value.startswith(("'", '"')):
            try:
                parts = shlex.split(value, comments=True, posix=True)
            except ValueError:
                raise ValueError(f"Invalid .env quoting on line {number}") from None
            if len(parts) != 1:
                raise ValueError(f"Invalid .env value on line {number}")
            value = parts[0]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


@dataclass(frozen=True)
class LLMConfig:
    api_url: str
    api_key: str = field(repr=False)
    model: str

    @classmethod
    def load(cls, env_file: Path | None = None):
        values = read_dotenv(Path(env_file) if env_file is not None else DEFAULT_ENV_PATH)

        def setting(name, legacy, default=""):
            # File values, including blanks, override previously exported values.
            if name in values:
                return values[name].strip()
            if legacy in values:
                return values[legacy].strip()
            return os.environ.get(name, os.environ.get(legacy, default)).strip()

        result = cls(
            api_url=setting("LLM_API_URL", "OPENAI_API_URL", DEFAULT_API_URL),
            api_key=setting("LLM_API_KEY", "OPENAI_API_KEY"),
            model=setting("LLM_MODEL", "OPENAI_MODEL"),
        )
        parsed = urlsplit(result.api_url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
                or any(char.isspace() for char in result.api_url)):
            raise ValueError("LLM_API_URL must be a complete HTTP(S) endpoint without credentials, query, or fragment")
        return result
