"""Ends a user turn that VAD missed, so speech the STT heard still reaches the LLM."""

import asyncio

from loguru import logger

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    ProposedUserStoppedSpeakingFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.turns.user_stop import BaseUserTurnStopStrategy

SILENCE_SECS = 1.5


class VADFallback(FrameProcessor):
    """Sits between STT and the user aggregator and closes turns heard by the STT but never by VAD."""

    def __init__(self, *, silence_secs: float = SILENCE_SECS, **kwargs):
        """Set how long interim transcripts must stay quiet before the fallback acts."""
        super().__init__(**kwargs)
        self._silence_secs = silence_secs
        self._vad_heard = False
        self._awaiting_final = False
        self._timer: asyncio.Task | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Pass every frame on, arming the fallback on interims that arrive without any VAD activity."""
        await super().process_frame(frame, direction)

        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._vad_heard = True
            self._awaiting_final = False
            await self._disarm()
        elif isinstance(frame, InterimTranscriptionFrame) and not self._vad_heard:
            await self._disarm()
            self._timer = self.create_task(self._wait_for_silence(), f"{self}::silence")
        elif isinstance(frame, TranscriptionFrame):
            await self._disarm()
            self._vad_heard = False
            await self.push_frame(frame, direction)
            # Sent after the transcript so the aggregator already holds the text when the turn closes.
            if self._awaiting_final:
                self._awaiting_final = False
                await self.push_frame(ProposedUserStoppedSpeakingFrame())
            return

        await self.push_frame(frame, direction)

    async def cleanup(self):
        """Stop a pending silence timer."""
        await super().cleanup()
        await self._disarm()

    async def _wait_for_silence(self):
        """After the silence window, make the STT finalize as if VAD had reported the end of speech."""
        await asyncio.sleep(self._silence_secs)
        self._timer = None
        logger.info(f"{self}: VAD missed the user's speech, flushing STT after {self._silence_secs}s of silence")
        self._awaiting_final = True
        await self.push_frame(VADUserStoppedSpeakingFrame(), FrameDirection.UPSTREAM)

    async def _disarm(self):
        """Cancel the silence timer if one is running."""
        if self._timer:
            await self.cancel_task(self._timer)
            self._timer = None


class VADFallbackStopStrategy(BaseUserTurnStopStrategy):
    """Ends the user turn when VADFallback proposes it, and on nothing else."""

    @property
    def resolves_proposed_turn_stop_frames(self) -> bool:
        """Claim the proposal, so the aggregator consumes it instead of passing it on."""
        return True

    async def process_frame(self, frame: Frame):
        """Report the turn stopped on a proposed stop; leave every other decision to the other strategies."""
        if isinstance(frame, ProposedUserStoppedSpeakingFrame):
            await self.report_user_turn_stopped()
