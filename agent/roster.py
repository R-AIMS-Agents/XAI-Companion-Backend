"""Which participant IDs the study logs have already used, and which file the next session of a participant is written to."""

import re
from pathlib import Path

DIRECTORY = Path(__file__).resolve().parent.parent / "logs" / "study"

# A re-run after a technical failure keeps the participant's ID and gains a suffix, so P04-2 still means participant 4 has been seen.
_SESSION = re.compile(r"P(\d+)(?:-\d+)?")
_ID = re.compile(r"P(\d+)", re.IGNORECASE)

# The ID becomes the log's file name, so it cannot hold what Windows refuses in one.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}

# The ID for trying the platform out. It is no participant, so the suggestion never counts it.
TEST = "test"


def normalise(text: str) -> str | None:
    """Return the form a participant ID is stored in, such as P04 for 'p4', or None when the text cannot name a log file."""
    text = text.strip()
    if match := _ID.fullmatch(text):
        return f"P{int(match.group(1)):02d}"
    if not text or _UNSAFE.search(text) or text.endswith(".") or text.upper() in _RESERVED:
        return None
    return text


def suggest(directory: Path = DIRECTORY) -> str:
    """Return the ID one past the highest participant number any study log has used."""
    numbers = [
        int(match.group(1))
        for path in directory.glob("*.jsonl")
        if (match := _SESSION.fullmatch(path.stem))
    ]
    return f"P{max(numbers, default=0) + 1:02d}"


def session_path(participant: str, directory: Path = DIRECTORY) -> Path:
    """Return the first unused log file for a participant: P04.jsonl, then P04-2.jsonl, P04-3.jsonl and on."""
    path = directory / f"{participant}.jsonl"
    attempt = 1
    while path.exists():
        attempt += 1
        path = directory / f"{participant}-{attempt}.jsonl"
    return path
