"""Frame observer that records when every frame moved through the pipeline."""

from dataclasses import dataclass, field

from loguru import logger

from pipecat.frames.frames import AudioRawFrame
from pipecat.observers.base_observer import BaseObserver, FramePushed

NS_PER_MS = 1_000_000


@dataclass
class _AudioWindow:
    """Audio frames seen on one hop since the last summary was logged."""

    count: int = 0
    audio_bytes: int = 0
    first_ns: int = 0
    last_ns: int | None = None
    max_gap_ns: int = 0
    gaps: list[int] = field(default_factory=list)


class Timeline(BaseObserver):
    """Logs control frames as they happen and summarises audio frames once per window.

    Audio arrives far too fast to log frame by frame, and the number that matters is not the count but the largest gap between two frames on the same hop: that gap is what a stutter sounds like.
    """

    def __init__(self, *, window_secs: float = 1.0, **kwargs):
        """Set up the observer with the stretch of time each audio summary covers."""
        super().__init__(**kwargs)
        self._window_ns = int(window_secs * 1e9)
        self._windows: dict[str, _AudioWindow] = {}

    async def on_push_frame(self, data: FramePushed):
        """Record one frame transfer between two processors."""
        hop = f"{data.source} -> {data.destination}"
        if isinstance(data.frame, AudioRawFrame):
            self._record_audio(hop, type(data.frame).__name__, data.frame, data.timestamp)
        else:
            logger.info(f"[{data.timestamp / 1e9:7.3f}s] {hop}  {data.frame}")

    def _record_audio(self, hop: str, frame_type: str, frame: AudioRawFrame, timestamp: int):
        """Fold one audio frame into its hop's window, and close the window once it has run its length."""
        key = f"{hop}  {frame_type}"
        window = self._windows.get(key)
        if window is None:
            window = _AudioWindow(first_ns=timestamp)
            self._windows[key] = window
        elif window.last_ns is not None:
            gap = timestamp - window.last_ns
            window.gaps.append(gap)
            window.max_gap_ns = max(window.max_gap_ns, gap)

        window.count += 1
        window.audio_bytes += len(frame.audio)
        window.last_ns = timestamp

        if timestamp - window.first_ns >= self._window_ns:
            self._log_window(key, window)
            self._windows[key] = _AudioWindow(first_ns=timestamp, last_ns=timestamp)

    def _log_window(self, key: str, window: _AudioWindow):
        """Print one window: how many frames crossed the hop and how far apart they landed."""
        mean_gap = sum(window.gaps) / len(window.gaps) if window.gaps else 0
        logger.info(
            f"[{window.last_ns / 1e9:7.3f}s] {key}  x{window.count}  {window.audio_bytes} B  "
            f"gap mean {mean_gap / NS_PER_MS:.1f} ms max {window.max_gap_ns / NS_PER_MS:.1f} ms"
        )
