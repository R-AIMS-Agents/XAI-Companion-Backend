"""The Loopback processor: input audio becomes output audio, everything else passes through."""

from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame, TextFrame
from pipecat.tests.utils import run_test

from agent.config import SAMPLE_RATE
from agent.pipeline import Loopback

AUDIO = b"\x01\x02" * 480


def _input_frame() -> InputAudioRawFrame:
    """Build one frame of received audio to send through the processor."""
    return InputAudioRawFrame(audio=AUDIO, sample_rate=SAMPLE_RATE, num_channels=1)


async def test_input_audio_becomes_output_audio():
    """Received audio is re-emitted as sent audio."""
    received, _ = await run_test(
        Loopback(),
        frames_to_send=[_input_frame()],
        expected_down_frames=[OutputAudioRawFrame],
    )
    assert isinstance(received[0], OutputAudioRawFrame)


async def test_audio_payload_survives_the_conversion():
    """Samples, rate and channel count cross unchanged, so nothing resamples on the way through."""
    received, _ = await run_test(
        Loopback(),
        frames_to_send=[_input_frame()],
        expected_down_frames=[OutputAudioRawFrame],
    )
    assert received[0].audio == AUDIO
    assert received[0].sample_rate == SAMPLE_RATE
    assert received[0].num_channels == 1


async def test_other_frames_pass_through_untouched():
    """Only input audio is rewritten. Every other frame is forwarded as it arrived."""
    sent = TextFrame(text="untouched")
    received, _ = await run_test(
        Loopback(),
        frames_to_send=[sent],
        expected_down_frames=[TextFrame],
    )
    assert received[0] is sent


async def test_output_audio_is_not_converted_again():
    """Audio already heading out is forwarded, not re-wrapped into a second frame."""
    sent = OutputAudioRawFrame(audio=AUDIO, sample_rate=SAMPLE_RATE, num_channels=1)
    received, _ = await run_test(
        Loopback(),
        frames_to_send=[sent],
        expected_down_frames=[OutputAudioRawFrame],
    )
    assert received[0] is sent
