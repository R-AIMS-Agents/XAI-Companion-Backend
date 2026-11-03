"""The local NIM container that serves Nemotron transcription, started here when a session uses it and left running afterwards."""

import asyncio
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from loguru import logger

STT = "nemotron"
COMPOSE = Path(__file__).resolve().parent.parent / "nemotron.compose.yaml"
SERVICE = "nemotron"
# Docker accepts connections on a mapped port before the server behind it is up, so readiness is asked of NIM itself.
READY_URL = "http://localhost:9000/v1/health/ready"
STARTUP_TIMEOUT = 180.0


def ready() -> bool:
    """Ask the container whether it is serving."""
    try:
        with urllib.request.urlopen(READY_URL, timeout=0.5) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


# The one background start a dialog may kick off, kept so a second look at the choice neither starts it twice nor retries a failure.
_launch: subprocess.Popen | None = None


def start():
    """Bring the container up in the background unless it is serving or a start is already under way, without waiting for it."""
    global _launch
    if _launch is not None or ready():
        return
    _launch = subprocess.Popen(
        ["docker", "compose", "-f", str(COMPOSE), "up", "-d", SERVICE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def hint(stt: str) -> str:
    """Start the container as soon as the operator picks it, and say how far it has got."""
    if stt != STT:
        return ""
    if ready():
        return "Container running"
    try:
        start()
    except FileNotFoundError:
        return "Docker is not installed"
    if _launch is not None and _launch.poll() not in (None, 0):
        return "Docker could not start the container. Is Docker Desktop running?"
    return "Container starting (about 40 s)"


async def _wait_until_ready() -> bool:
    """Wait for a freshly started container to finish loading its model."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if ready():
            return True
        await asyncio.sleep(1.0)
    return False


async def ensure():
    """Start the container unless it is already serving, and wait until it is."""
    if ready():
        logger.info("Nemotron container already serving")
        return

    logger.info("Starting the Nemotron container, which takes about 40 s")
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["docker", "compose", "-f", str(COMPOSE), "up", "-d", SERVICE],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError("Docker is not installed, and the nemotron STT runs in a Docker container.") from None
    if result.returncode != 0:
        raise RuntimeError(f"Docker could not start the Nemotron container. Is Docker Desktop running?\n{result.stderr.strip()}")

    if not await _wait_until_ready():
        raise RuntimeError(
            f"The Nemotron container did not become ready within {STARTUP_TIMEOUT:.0f}s. Run 'docker logs nemotron-asr-streaming' to see why."
        )
    logger.info("Nemotron container serving")
