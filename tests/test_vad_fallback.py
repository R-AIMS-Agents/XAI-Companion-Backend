"""The VAD fallback: closes a turn the STT heard but VAD missed, and stays out of turns VAD saw."""

from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    ProposedUserStoppedSpeakingFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.tests.utils import SleepFrame, run_test

from agent.vad_fallback import VADFallback

SILENCE = 0.1


def _interim(text: str) -> InterimTranscriptionFrame:
    """Build an interim transcript as the STT would push it."""
    return InterimTranscriptionFrame(text=text, user_id="unity", timestamp="")


def _final(text: str) -> TranscriptionFrame:
    """Build a final transcript as the STT would push it."""
    return TranscriptionFrame(text=text, user_id="unity", timestamp="")


async def test_interims_without_vad_flush_stt_and_propose_stop_after_final():
    """Silence after VAD-less interims flushes the STT, and the final that follows is chased by a stop proposal."""
    await run_test(
        VADFallback(silence_secs=SILENCE),
        frames_to_send=[_interim("Test"), SleepFrame(sleep=SILENCE * 3), _final("Test")],
        expected_down_frames=[InterimTranscriptionFrame, TranscriptionFrame, ProposedUserStoppedSpeakingFrame],
        expected_up_frames=[VADUserStoppedSpeakingFrame],
    )


async def test_each_interim_restarts_the_silence_window():
    """Interims arriving faster than the window keep the fallback from firing."""
    await run_test(
        VADFallback(silence_secs=SILENCE * 3),
        frames_to_send=[
            _interim("Ja"),
            SleepFrame(sleep=SILENCE * 2),
            _interim("Ja, ich"),
            SleepFrame(sleep=SILENCE * 2),
            _final("Ja, ich"),
        ],
        expected_down_frames=[InterimTranscriptionFrame, InterimTranscriptionFrame, TranscriptionFrame],
        expected_up_frames=[],
    )


async def test_interims_after_vad_start_leave_the_turn_to_vad():
    """Once VAD has heard the user, interims and silence do not trigger the fallback."""
    await run_test(
        VADFallback(silence_secs=SILENCE),
        frames_to_send=[VADUserStartedSpeakingFrame(), _interim("Hallo"), SleepFrame(sleep=SILENCE * 3)],
        expected_down_frames=[VADUserStartedSpeakingFrame, InterimTranscriptionFrame],
        expected_up_frames=[],
    )


async def test_final_without_fallback_gets_no_proposal():
    """A final transcript on the normal path passes through alone."""
    await run_test(
        VADFallback(silence_secs=SILENCE),
        frames_to_send=[_interim("Hallo"), _final("Hallo")],
        expected_down_frames=[InterimTranscriptionFrame, TranscriptionFrame],
        expected_up_frames=[],
    )
