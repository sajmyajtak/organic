"""Load account configuration and runtime secrets."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "account.yaml"
CONTENT_DIR = ROOT / "content"
DATA_DIR = ROOT / "data"
BUILD_DIR = ROOT / "build"
ENV_PATH = ROOT / ".env"


def load_dotenv(path: Path = ENV_PATH) -> None:
    """Read KEY=VALUE lines from .env into os.environ for local runs.

    Variables already set in the environment win (GitHub Actions passes
    secrets that way). Unquoted values end at " #", so the inline comments
    from .env.example are not read as part of a key."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] in ("'", '"') and value.endswith(value[0]) and len(value) > 1:
            value = value[1:-1]
        elif value.startswith("#"):
            value = ""
        else:
            value = value.split(" #", 1)[0].strip()
        if key and value and key not in os.environ:
            os.environ[key] = value


load_dotenv()


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(f"Chybí proměnná prostředí {name} (viz docs/NASTAVENI.md).")
    return value
