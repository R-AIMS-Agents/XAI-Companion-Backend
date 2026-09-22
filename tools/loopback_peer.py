"""Headless stand-in for the Unity client: joins the room, speaks tone bursts, reports what comes back.

Proves the Milestone 1 chain without Unity. A stutter here is the transport or the pipeline; a stutter Unity sees that this does not is Unity.
"""

import argparse
import asyncio
import statistics
import sys
import time

import numpy as np
from livekit import rtc
from loguru import logger

from agent import config
from agent.config import SAMPLE_RATE, Config
from agent.transports.livekit import AGENT_IDENTITY, client_token

FRAME_MS = 10
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000
BURST_MS = 100
BURST_PERIOD_MS = 1000
TONE_HZ = 440
TONE_AMPLITUDE = 0.5
ONSET_RMS = 0.05
QUEUE_SIZE_MS = 100
AGENT_WAIT_SECS = 30.0
TRACK_NAME = "peer"


def _tone(samples: int) -> np.ndarray:
    """Generate the sine wave every burst is made of."""
    phase = 2 * np.pi * TONE_HZ * np.arange(samples) / SAMPLE_RATE
    return (np.sin(phase) * TONE_AMPLITUDE * np.iinfo(np.int16).max).astype(np.int16)


BURST = _tone(SAMPLE_RATE * BURST_MS // 1000)
SILENCE = np.zeros(SAMPLES_PER_FRAME, dtype=np.int16)


def _rms(samples: np.ndarray) -> float:
    """Measure how loud one frame is, which is how a returning burst is recognised."""
    if samples.size == 0:
        return 0.0
    normalised = samples.astype(np.float32) / np.iinfo(np.int16).max
    return float(np.sqrt(np.mean(np.square(normalised))))


class Ear:
    """Listens to the agent's track: when bursts arrive and how evenly frames land."""

    def __init__(self):
        """Start out having heard nothing."""
        self.onsets: list[float] = []
        self.gaps: list[float] = []
        self.frames = 0
        self._last_arrival: float | None = None
        self._loud = False

    def hear(self, samples: np.ndarray, arrival: float):
        """Record one received frame, and the rising edge of a burst if this is one."""
        self.frames += 1
        if self._last_arrival is not None:
            self.gaps.append(arrival - self._last_arrival)
        self._last_arrival = arrival

        loud = _rms(samples) >= ONSET_RMS
        if loud and not self._loud:
            self.onsets.append(arrival)
        self._loud = loud


async def _listen(track: rtc.Track, ear: Ear):
    """Drain the agent's audio track until the room closes."""
    async for event in rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1):
        samples = np.frombuffer(event.frame.data, dtype=np.int16)
        ear.hear(samples, time.monotonic())


async def _speak(source: rtc.AudioSource, seconds: float) -> list[float]:
    """Send silence with a tone burst every second. Returns when each burst actually left the queue."""
    total_frames = int(seconds * 1000 / FRAME_MS)
    burst_frames = BURST_MS // FRAME_MS
    period_frames = BURST_PERIOD_MS // FRAME_MS
    sent_at: list[float] = []

    for index in range(total_frames):
        position = index % period_frames
        if position < burst_frames:
            samples = BURST[position * SAMPLES_PER_FRAME : (position + 1) * SAMPLES_PER_FRAME]
            if position == 0:
                sent_at.append(time.monotonic() + source.queued_duration)
        else:
            samples = SILENCE

        await source.capture_frame(
            rtc.AudioFrame(
                data=samples.tobytes(),
                sample_rate=SAMPLE_RATE,
                num_channels=1,
                samples_per_channel=SAMPLES_PER_FRAME,
            )
        )

    await source.wait_for_playout()
    return sent_at


async def _run(cfg: Config, seconds: float) -> Ear:
    """Join the room as the client, wait for the agent, speak, and listen."""
    room = rtc.Room()
    ear = Ear()
    agent_heard = asyncio.Event()
    listeners: list[asyncio.Task] = []

    @room.on("track_subscribed")
    def _on_track_subscribed(track, publication, participant):
        """Start listening as soon as the agent publishes audio, and ignore every other track."""
        if participant.identity != AGENT_IDENTITY or track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        logger.info(f"Subscribed to '{participant.identity}'")
        listeners.append(asyncio.create_task(_listen(track, ear)))
        agent_heard.set()

    await room.connect(cfg.livekit_url, client_token(cfg))
    logger.info(f"Joined room '{cfg.room}' on {cfg.livekit_url}")

    source = rtc.AudioSource(SAMPLE_RATE, 1, queue_size_ms=QUEUE_SIZE_MS)
    track = rtc.LocalAudioTrack.create_audio_track(TRACK_NAME, source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    logger.info("Published audio track")

    try:
        logger.info(f"Waiting up to {AGENT_WAIT_SECS:.0f}s for '{AGENT_IDENTITY}' to publish")
        await asyncio.wait_for(agent_heard.wait(), timeout=AGENT_WAIT_SECS)
        logger.info(f"Speaking a {BURST_MS} ms burst every {BURST_PERIOD_MS} ms for {seconds:.0f}s")
        ear.sent_at = await _speak(source, seconds)
    except TimeoutError:
        logger.error(f"'{AGENT_IDENTITY}' never published a track. Is the agent running?")
        ear.sent_at = []
    finally:
        for listener in listeners:
            listener.cancel()
        await source.aclose()
        await room.disconnect()

    return ear


def _report(ear: Ear) -> bool:
    """Print what was measured. False if the loopback did not come back."""
    sent = getattr(ear, "sent_at", [])
    logger.info(f"Bursts sent {len(sent)}, bursts heard back {len(ear.onsets)}")
    logger.info(f"Frames received {ear.frames}")

    if ear.gaps:
        gaps_ms = [gap * 1000 for gap in ear.gaps]
        logger.info(
            f"Receive gap: mean {statistics.mean(gaps_ms):.1f} ms  max {max(gaps_ms):.1f} ms"
        )

    if not ear.onsets:
        logger.error("Nothing came back. The loopback is broken.")
        return False

    trips_ms = [(heard - spoke) * 1000 for spoke, heard in zip(sent, ear.onsets)]
    logger.info(
        f"Round trip: mean {statistics.mean(trips_ms):.1f} ms  "
        f"min {min(trips_ms):.1f} ms  max {max(trips_ms):.1f} ms"
    )
    logger.info("  ".join(f"{trip:.0f}" for trip in trips_ms))

    if len(ear.onsets) < len(sent):
        logger.warning(f"{len(sent) - len(ear.onsets)} burst(s) never came back")
    return True


def _parse_args() -> argparse.Namespace:
    """Read the command line: how long to keep speaking."""
    parser = argparse.ArgumentParser(description="Speak into the agent's room and measure what returns.")
    parser.add_argument("--seconds", type=float, default=10.0, help="how long to speak for")
    return parser.parse_args()


async def main():
    """Run one loopback measurement."""
    args = _parse_args()
    ear = await _run(config.load(), args.seconds)
    if not _report(ear):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
