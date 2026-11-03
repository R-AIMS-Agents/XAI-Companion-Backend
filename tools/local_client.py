"""Local stand-in for the Unity client: talk to a running agent through this PC's microphone and speakers, and follow the conversation in the console.

Joins under its own identity, so the LiveKit logs never mistake it for the headset. Echo cancellation keeps the agent from hearing itself through the speakers. Starts the agent in a console of its own when none is running.
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

import aiohttp
from livekit import rtc
from loguru import logger
from pipecat.processors.frameworks.rtvi.models import MESSAGE_LABEL, PROTOCOL_VERSION

from agent.join import PATH, PORT
from agent.transports.livekit import AGENT_IDENTITY

ENDPOINT = f"http://localhost:{PORT}{PATH}"

IDENTITY = "local"
TRACK_NAME = "microphone"
AGENT_WAIT_SECS = 30.0
AGENT_COMMAND = [sys.executable, "-m", "agent.run", "--scenario", "chat", "--participant", "dev"]
POLL_SECS = 0.5


async def connection_details(identity: str) -> dict:
    """Ask the agent where the room is and for a token to enter it under the given identity, the way the Unity client's TokenSourceEndpoint does."""
    async with aiohttp.ClientSession() as session:
        async with session.post(ENDPOINT, json={"participant_identity": identity}) as response:
            response.raise_for_status()
            return await response.json()


async def _listening() -> bool:
    """Tell whether something accepts connections on the agent's endpoint port."""
    try:
        _, writer = await asyncio.open_connection("localhost", PORT)
    except OSError:
        return False
    writer.close()
    await writer.wait_closed()
    return True


async def ensure_agent() -> bool:
    """Start the agent in a new console when nothing listens on its endpoint, and wait until it does; False when the agent exited before it got there."""
    if await _listening():
        return True
    logger.info("No agent running, starting one in a new console")
    process = subprocess.Popen(
        AGENT_COMMAND, cwd=Path(__file__).resolve().parent.parent, creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    while not await _listening():
        if process.poll() is not None:
            return False
        await asyncio.sleep(POLL_SECS)
    return True


def client_ready(name: str) -> bytes:
    """The announcement that opens the handshake, in the wire format the Unity client has to reproduce."""
    return json.dumps(
        {
            "label": MESSAGE_LABEL,
            "type": "client-ready",
            "id": "client-ready",
            "data": {
                "version": PROTOCOL_VERSION,
                "about": {"library": name, "platform": "python"},
            },
        }
    ).encode()


def _show(message: dict) -> None:
    """Log the parts of one RTVI message a person in the conversation follows: what was heard, what was said, and where it was cut off."""
    data = message.get("data") or {}
    match message.get("type"):
        case "user-transcription" if data.get("final"):
            logger.info(f"you    {data['text']}")
        case "bot-output" if data.get("spoken_status") == "completed":
            logger.info(f"agent  {data['text']}")
        case "bot-interrupted":
            logger.info("agent  (interrupted)")
        case "server-message":
            logger.info(f"server-message: {data}")


async def _run() -> None:
    """Join the room, open the microphone and speakers, and hold the conversation until the agent leaves or Ctrl+C."""
    room = rtc.Room()
    agent_present = asyncio.Event()
    agent_left = asyncio.Event()
    adding: set[asyncio.Task] = set()

    # The microphone opens first, so the speakers share its echo canceller.
    devices = rtc.MediaDevices()
    microphone = devices.open_input()
    speakers = devices.open_output()
    await speakers.start()

    @room.on("participant_connected")
    def _on_participant_connected(participant: rtc.RemoteParticipant):
        """Note the agent's arrival, since a packet sent into an empty room is not buffered for anyone."""
        if participant.identity == AGENT_IDENTITY:
            agent_present.set()

    @room.on("participant_disconnected")
    def _on_participant_disconnected(participant: rtc.RemoteParticipant):
        """End the session with the agent's, since there is nobody left to talk to."""
        if participant.identity == AGENT_IDENTITY:
            logger.info(f"'{AGENT_IDENTITY}' left the room")
            agent_left.set()

    @room.on("track_subscribed")
    def _on_track_subscribed(
        track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant
    ):
        """Route the agent's voice to the speakers."""
        if participant.identity == AGENT_IDENTITY and track.kind == rtc.TrackKind.KIND_AUDIO:
            task = asyncio.create_task(speakers.add_track(track))
            adding.add(task)
            task.add_done_callback(adding.discard)

    @room.on("data_received")
    def _on_data_received(packet: rtc.DataPacket):
        """Show what the agent reports about the conversation."""
        try:
            message = json.loads(packet.data)
        except json.JSONDecodeError:
            return
        if message.get("label") == MESSAGE_LABEL:
            _show(message)

    try:
        details = await connection_details(IDENTITY)
        await room.connect(details["server_url"], details["participant_token"])
        logger.info(f"Joined {details['server_url']} as '{room.local_participant.identity}'")
        if AGENT_IDENTITY in room.remote_participants:
            agent_present.set()

        logger.info(f"Waiting up to {AGENT_WAIT_SECS:.0f}s for '{AGENT_IDENTITY}' to join")
        try:
            await asyncio.wait_for(agent_present.wait(), timeout=AGENT_WAIT_SECS)
        except TimeoutError:
            logger.error(f"'{AGENT_IDENTITY}' never joined. Is the agent running?")
            return

        await room.local_participant.publish_data(client_ready(IDENTITY), reliable=True)
        track = rtc.LocalAudioTrack.create_audio_track(TRACK_NAME, microphone.source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        logger.info("Microphone open. Talk to the agent, Ctrl+C ends the session.")
        await agent_left.wait()
    finally:
        await room.disconnect()
        await microphone.aclose()
        await speakers.aclose()


async def main():
    """Run one conversation with the agent, starting it first if needed."""
    if not await ensure_agent():
        logger.error("The agent exited before its endpoint came up.")
        sys.exit(1)
    try:
        await _run()
    except aiohttp.ClientError as error:
        logger.error(f"No connection details from {ENDPOINT} ({error}). Is the agent running?")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
