"""The LiveKit server the transport connects to, started here when the configuration points at this machine."""

import asyncio
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger

from agent.config import Config

BINARY = Path(__file__).resolve().parent.parent / "livekit-server.exe"
DOWNLOAD = "https://github.com/livekit/livekit/releases"
# Only these mean the server belongs to this machine and is ours to start; anything else is someone else's server.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_PORT = 7880
STARTUP_TIMEOUT = 15.0
SHUTDOWN_TIMEOUT = 5.0


def _listening(host: str, port: int) -> bool:
    """Ask whether something already answers on the server's port."""
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


async def _wait_until_listening(host: str, port: int) -> bool:
    """Wait for a freshly started server to accept connections."""
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if _listening(host, port):
            return True
        await asyncio.sleep(0.2)
    return False


async def ensure(config: Config) -> subprocess.Popen | None:
    """Start the dev server when it is ours to start and nothing answers yet, and return it for shutdown."""
    url = urlparse(config.livekit_url)
    host = url.hostname or ""
    port = url.port or DEFAULT_PORT

    if host not in LOCAL_HOSTS:
        return None
    if _listening(host, port):
        logger.info(f"LiveKit server already listening on {host}:{port}")
        return None
    if not BINARY.exists():
        raise RuntimeError(
            f"{BINARY.name} is not in the project root. Download it from {DOWNLOAD}, or point LIVEKIT_URL at a server running elsewhere."
        )

    # The server logs to stderr at debug level in dev mode, which would bury the agent's own timeline.
    process = subprocess.Popen(
        [str(BINARY), "--dev"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    if not await _wait_until_listening(host, port):
        process.terminate()
        raise RuntimeError(
            f"The LiveKit server did not answer on {host}:{port} within {STARTUP_TIMEOUT:.0f}s. Run '{BINARY.name} --dev' by hand to see why."
        )

    logger.info(f"Started the LiveKit server on {host}:{port}")
    return process


def stop(process: subprocess.Popen | None):
    """Stop the server we started, leaving one we merely found alone."""
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=SHUTDOWN_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
    logger.info("Stopped the LiveKit server")
