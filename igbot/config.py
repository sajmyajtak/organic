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


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise SystemExit(f"Chybí proměnná prostředí {name} (viz docs/NASTAVENI.md).")
    return value
