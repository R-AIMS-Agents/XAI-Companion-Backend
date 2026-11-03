"""Where benchmark results go: one append-only JSONL file per benchmark, each line stamped with the code version and the hashes that say what it is comparable with."""

import dataclasses
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from pipecat.services.ai_service import AIService

RESULTS = Path(__file__).resolve().parent / "results"


def digest(value: Any) -> str:
    """Return a short hash of a JSON-serialisable value, equal for equal content however its keys are ordered."""
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def settings(service: AIService) -> dict[str, Any]:
    """Return a service's settings as plain JSON values, so a result says exactly how its model was configured."""
    return json.loads(json.dumps(dataclasses.asdict(service.settings), default=str))


def commit() -> str | None:
    """Name the code version a run used, marked dirty when it had uncommitted changes, or None outside a git checkout."""
    try:
        described = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=RESULTS.parent,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return described.stdout.strip()


def read(benchmark: str) -> list[dict[str, Any]]:
    """Return every result line a benchmark has written, oldest first."""
    path = RESULTS / f"{benchmark}.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def append(benchmark: str, line: dict[str, Any]):
    """Add one result line, stamped with the time and code version, and flush it at once."""
    RESULTS.mkdir(exist_ok=True)
    stamped = {"iso": datetime.now().astimezone().isoformat(timespec="seconds"), "commit": commit(), **line}
    with (RESULTS / f"{benchmark}.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps(stamped, ensure_ascii=False) + "\n")
