"""The frame pipeline. Receives a transport and never imports one."""

from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import BaseTransport


class Loopback(FrameProcessor):
    """Turns received audio into sent audio. The entire agent until the models arrive."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Re-emit input audio as output audio and pass everything else through."""
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            frame = OutputAudioRawFrame(
                audio=frame.audio,
                sample_rate=frame.sample_rate,
                num_channels=frame.num_channels,
            )
        await self.push_frame(frame, direction)


def build(transport: BaseTransport) -> Pipeline:
    """Assemble the pipeline. The only place it is assembled."""
    return Pipeline([transport.input(), Loopback(), transport.output()])
