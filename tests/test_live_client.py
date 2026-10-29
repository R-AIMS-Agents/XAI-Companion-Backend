"""Live check of the Unity contract against a running agent: token, handshake and camera track, without a headset.

Skipped by a plain `uv run pytest`. Start the agent, then run `uv run pytest -m live`.
"""

import asyncio
import json
import time
from collections import Counter

import aiohttp
import pytest
from livekit import rtc
from loguru import logger
from pipecat.processors.frameworks.rtvi.models import MESSAGE_LABEL

from agent.transports.livekit import AGENT_IDENTITY
from tools.local_client import ENDPOINT, client_ready, connection_details

pytestmark = pytest.mark.live

IDENTITY = "live-test"
WIDTH = 320
HEIGHT = 240
BAR_WIDTH = 24
TRACK_NAME = "camera"
VIDEO_SECS = 15.0
FPS = 2.0
AGENT_WAIT_SECS = 30.0
BOT_READY_WAIT_SECS = 30.0


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


async def test_agent_answers_handshake_and_takes_camera():
    """Join as a client, announce, publish video, and require the agent to answer the handshake."""
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
        """Count every RTVI message the agent publishes, and note the one that answers the handshake."""
        try:
            message = json.loads(packet.data)
        except json.JSONDecodeError:
            return
        if message.get("label") != MESSAGE_LABEL:
            return
        seen[message["type"]] += 1
        if message["type"] == "bot-ready":
            logger.info(f"bot-ready: {message.get('data')}")
            bot_ready.set()

    try:
        details = await connection_details(IDENTITY)
    except aiohttp.ClientError as error:
        pytest.fail(f"No connection details from {ENDPOINT} ({error}). Is the agent running?")

    await room.connect(details["server_url"], details["participant_token"])
    if AGENT_IDENTITY in room.remote_participants:
        agent_present.set()

    try:
        try:
            await asyncio.wait_for(agent_present.wait(), timeout=AGENT_WAIT_SECS)
        except TimeoutError:
            pytest.fail(f"'{AGENT_IDENTITY}' never joined within {AGENT_WAIT_SECS:.0f}s.")

        await room.local_participant.publish_data(client_ready(IDENTITY), reliable=True)

        source = rtc.VideoSource(WIDTH, HEIGHT)
        track = rtc.LocalVideoTrack.create_video_track(TRACK_NAME, source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
        )

        try:
            await asyncio.wait_for(bot_ready.wait(), timeout=BOT_READY_WAIT_SECS)
        except TimeoutError:
            pytest.fail("The agent never answered client-ready. The channel is broken.")

        frames = await _publish_frames(source, VIDEO_SECS, FPS)
        await source.aclose()
    finally:
        await room.disconnect()

    logger.info(f"Camera frames sent {frames}")
    for message_type, count in sorted(seen.items()):
        logger.info(f"  {message_type}  x{count}")
