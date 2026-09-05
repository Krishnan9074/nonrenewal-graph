import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_id(*parts: Any) -> str:
    return sha256(json.dumps(parts, sort_keys=True, default=str).encode())


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def dump_yaml(path: Path, obj: dict) -> None:
    path.write_text(yaml.safe_dump(obj, sort_keys=False))
