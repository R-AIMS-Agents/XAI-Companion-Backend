"""Headless stand-in for the Unity client: fetches its own connection details, announces itself over RTVI and publishes a camera track.

Proves the milestone 4 channel without Unity. What this peer sends is what the Unity client has to send, and what it counts is what the Unity client gets for free.
"""

import argparse
import asyncio
import json
import sys
import time
from collections import Counter

import aiohttp
from livekit import rtc
from loguru import logger
from pipecat.processors.frameworks.rtvi.models import MESSAGE_LABEL, PROTOCOL_VERSION

from agent.join import PATH, PORT
from agent.transports.livekit import AGENT_IDENTITY

ENDPOINT = f"http://localhost:{PORT}{PATH}"

WIDTH = 320
HEIGHT = 240
BAR_WIDTH = 24
TRACK_NAME = "camera"
AGENT_WAIT_SECS = 30.0
BOT_READY_WAIT_SECS = 30.0


async def _connection_details() -> dict:
    """Ask the agent where the room is and for a token to enter it with, the way the Unity client's TokenSourceEndpoint does."""
    async with aiohttp.ClientSession() as session:
        async with session.post(ENDPOINT) as response:
            response.raise_for_status()
            return await response.json()


def _client_ready() -> bytes:
    """The announcement that opens the handshake, in the wire format the Unity client has to reproduce."""
    return json.dumps(
        {
            "label": MESSAGE_LABEL,
            "type": "client-ready",
            "id": "client-ready",
            "data": {
                "version": PROTOCOL_VERSION,
                "about": {"library": "client_peer", "platform": "python"},
            },
        }
    ).encode()


def _frame(step: int) -> bytes:
    """Draw one RGBA frame: a white bar one bar width further right than the last, so a still tells you frames are moving."""
    pixels = bytearray(WIDTH * HEIGHT * 4)
    left = (step * BAR_WIDTH) % WIDTH
    span = min(BAR_WIDTH, WIDTH - left) * 4
    for row in range(HEIGHT):
        start = (row * WIDTH + left) * 4
        pixels[start : start + span] = b"\xff" * span
    return bytes(pixels)


async def _publish_frames(source: rtc.VideoSource, seconds: float, fps: float) -> int:
    """Send frames at the requested rate for the requested time, the way a headset's camera would."""
    period = 1.0 / fps
    deadline = time.monotonic() + seconds
    step = 0
    while time.monotonic() < deadline:
        source.capture_frame(rtc.VideoFrame(WIDTH, HEIGHT, rtc.VideoBufferType.RGBA, _frame(step)))
        step += 1
        await asyncio.sleep(period)
    return step


async def _run(seconds: float, fps: float) -> tuple[Counter, int]:
    """Join the room as the client, announce, publish video, and count what the agent sends back."""
    room = rtc.Room()
    seen: Counter = Counter()
    agent_present = asyncio.Event()
    bot_ready = asyncio.Event()

    @room.on("participant_connected")
    def _on_participant_connected(participant: rtc.RemoteParticipant):
        """Note the agent's arrival, since a packet sent into an empty room is not buffered for anyone."""
        if participant.identity == AGENT_IDENTITY:
            agent_present.set()

    @room.on("data_received")
    def _on_data_received(packet: rtc.DataPacket):
        """Count every message the agent publishes, and note the one that answers the handshake."""
        try:
            message = json.loads(packet.data)
        except json.JSONDecodeError:
            seen["<not json>"] += 1
            return
        if message.get("label") != MESSAGE_LABEL:
            seen["<not rtvi>"] += 1
            return
        seen[message["type"]] += 1
        if message["type"] == "bot-ready":
            logger.info(f"bot-ready: {message.get('data')}")
            bot_ready.set()

    details = await _connection_details()
    await room.connect(details["server_url"], details["participant_token"])
    logger.info(f"Joined {details['server_url']} as '{room.local_participant.identity}'")
    if AGENT_IDENTITY in room.remote_participants:
        agent_present.set()

    frames = 0
    try:
        logger.info(f"Waiting up to {AGENT_WAIT_SECS:.0f}s for '{AGENT_IDENTITY}' to join")
        await asyncio.wait_for(agent_present.wait(), timeout=AGENT_WAIT_SECS)

        await room.local_participant.publish_data(_client_ready(), reliable=True)
        logger.info(f"Sent client-ready, RTVI {PROTOCOL_VERSION}")

        source = rtc.VideoSource(WIDTH, HEIGHT)
        track = rtc.LocalVideoTrack.create_video_track(TRACK_NAME, source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
        )
        logger.info(f"Published a {WIDTH}x{HEIGHT} camera track at {fps:g} fps")

        try:
            await asyncio.wait_for(bot_ready.wait(), timeout=BOT_READY_WAIT_SECS)
        except TimeoutError:
            logger.error(f"No bot-ready within {BOT_READY_WAIT_SECS:.0f}s")

        frames = await _publish_frames(source, seconds, fps)
        await source.aclose()
    except TimeoutError:
        logger.error(f"'{AGENT_IDENTITY}' never joined. Is the agent running?")
    finally:
        await room.disconnect()

    return seen, frames


def _report(seen: Counter, frames: int) -> bool:
    """Print what the agent sent back. False if the handshake never completed."""
    logger.info(f"Camera frames sent {frames}")
    for message_type, count in sorted(seen.items()):
        logger.info(f"  {message_type}  x{count}")

    if not seen["bot-ready"]:
        logger.error("The agent never answered client-ready. The channel is broken.")
        return False
    return True


def _parse_args() -> argparse.Namespace:
    """Read the command line: how long to hold the camera open and at what rate."""
    parser = argparse.ArgumentParser(description="Stand in for the Unity client on the data channel.")
    parser.add_argument("--seconds", type=float, default=15.0, help="how long to publish video for")
    parser.add_argument("--fps", type=float, default=2.0, help="camera frame rate")
    return parser.parse_args()


async def main():
    """Run one handshake and one stretch of video."""
    args = _parse_args()
    try:
        seen, frames = await _run(args.seconds, args.fps)
    except aiohttp.ClientError as error:
        logger.error(f"No connection details from {ENDPOINT} ({error}). Is the agent running?")
        sys.exit(1)
    if not _report(seen, frames):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
