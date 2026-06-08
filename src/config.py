from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_path(path_value: str | Path, base_dir: Path | None = None) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir or project_root()) / path


def load_config(config_path: str | Path = "config.yaml") -> dict[str, Any]:
    root = project_root()
    path = resolve_path(config_path, root)
    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}
    config["_root"] = str(root)
    config["_config_path"] = str(path)
    return config
