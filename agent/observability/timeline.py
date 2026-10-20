"""Frame observer that records when every frame moved through the pipeline."""

from loguru import logger

from pipecat.frames.frames import AudioRawFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed

# Tagged so the debug log can keep these records out of the console.
log = logger.bind(timeline=True)


class Timeline(BaseObserver):
    """Logs every non-audio frame once, at the first hop it is pushed across."""

    def __init__(self, **kwargs):
        """Set up the observer so pipecat reports each frame only at its first push."""
        super().__init__(observe_every_push=False, **kwargs)

    async def on_push_frame(self, data: FramePushed):
        """Record a frame the first time it moves between two processors; audio frames are skipped."""
        if isinstance(data.frame, AudioRawFrame):
            return
        log.info(f"[{data.timestamp / 1e9:7.3f}s] {data.source} -> {data.destination}  {data.frame}")
