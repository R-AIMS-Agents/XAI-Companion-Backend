"""Routes every log record of one session to its own JSONL file under logs/debug, named like its study log, for debugging the pipeline after the fact."""

import json
import sys
import traceback
from pathlib import Path

from loguru import logger

DIRECTORY = Path(__file__).resolve().parent.parent.parent / "logs" / "debug"

# Tags of records too frequent or too long for the console, which go to the file only.
_QUIET = {"timeline", "llm"}


def start(session: str) -> Path:
    """Open this session's debug file and keep the frame and LLM records out of the console; returns the file's path."""
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    path = DIRECTORY / f"{session}.jsonl"

    logger.remove()
    logger.add(sys.stderr, level="DEBUG", filter=lambda record: not _QUIET & record["extra"].keys())
    logger.add(path, level="DEBUG", format=_format, encoding="utf-8", enqueue=True)
    return path


def _format(record) -> str:
    """Reduce a record to one compact JSON line: time, level, source and message, plus tags and traceback when present."""
    line = {
        "time": record["time"].strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
        "level": record["level"].name,
        "source": f"{record['name']}:{record['function']}:{record['line']}",
        "message": record["message"],
    }
    line.update({key: value for key, value in record["extra"].items() if key != "json"})
    if record["exception"] is not None:
        line["exception"] = "".join(traceback.format_exception(*record["exception"]))
    record["extra"]["json"] = json.dumps(line, ensure_ascii=False, default=str)
    return "{extra[json]}\n"
