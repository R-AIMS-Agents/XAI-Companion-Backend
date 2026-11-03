"""The study log: one append-only JSONL file per session, holding the transcript, the turn structure and every measurement the analysis needs, and never audio."""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    FunctionCallResultFrame,
    InterruptionFrame,
    LLMContextAssistantTurnFrame,
    LLMContextUserTurnFrame,
    LLMThoughtEndFrame,
    LLMThoughtStartFrame,
    LLMThoughtTextFrame,
    MetricsFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData, STTUsageMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.observers.turn_tracking_observer import TurnTrackingObserver
from pipecat.observers.user_bot_latency_observer import LatencyBreakdown, UserBotLatencyObserver
from pipecat.processors.frame_processor import FrameDirection

# Usage counters summed per turn and per session.
_USAGE = ("prompt_tokens", "completion_tokens", "tts_characters", "stt_audio_seconds")


class StudyLog(BaseObserver):
    """Writes one session's study log, one flushed line per event, so a crash mid-session keeps everything before it."""

    def __init__(self, path: Path, **kwargs):
        """Open the session's file, refusing one that already exists so two sessions can never share a log."""
        super().__init__(observe_every_push=False, **kwargs)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("x", encoding="utf-8")
        self._started = time.monotonic()
        self._turn = 0
        self._interrupted_turns = 0
        self._turn_usage = dict.fromkeys(_USAGE, 0)
        self._session_usage = dict.fromkeys(_USAGE, 0)
        self._bot_speaking = False
        self._barge_in_at: int | None = None
        self._interrupted = False
        self._thought: list[str] = []

        self._turns = TurnTrackingObserver()
        self._turns.add_event_handler("on_turn_started", self._on_turn_started)
        self._turns.add_event_handler("on_turn_ended", self._on_turn_ended)
        self._latency = UserBotLatencyObserver()
        self._latency.add_event_handler("on_latency_measured", self._on_latency_measured)
        self._latency.add_event_handler("on_latency_breakdown", self._on_latency_breakdown)
        self._latency.add_event_handler("on_first_bot_speech_latency", self._on_first_speech)

    @property
    def observers(self) -> list[BaseObserver]:
        """The observers the worker has to run for this log: itself, and the pipecat trackers it reads turns and latency from."""
        return [self, self._turns, self._latency]

    def write(self, event: str, **fields: Any):
        """Append one event as a JSON line, stamped with wall-clock time and the current turn, and flush it to disk."""
        line = {
            "event": event,
            "ts": time.time(),
            "iso": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "turn": self._turn,
            **fields,
        }
        self._file.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        self._file.flush()

    def close(self):
        """Write the session's totals and close the file; a second call does nothing."""
        if self._file.closed:
            return
        self.write(
            "session_end",
            duration_s=round(time.monotonic() - self._started, 3),
            turns=self._turn,
            interrupted_turns=self._interrupted_turns,
            **self._session_usage,
        )
        self._file.close()

    async def on_push_frame(self, data: FramePushed):
        """Pick out the frames the study needs: what was said by whom, what the LLM thought, tool calls, usage, and the moments of a barge-in."""
        frame = data.frame
        # A frame broadcast both ways arrives twice under two ids, so only its upstream copy is read.
        if frame.broadcast_sibling_id is not None and data.direction == FrameDirection.DOWNSTREAM:
            return

        if isinstance(frame, LLMContextUserTurnFrame):
            self.write("user_transcript", text=frame.text)
        elif isinstance(frame, LLMContextAssistantTurnFrame):
            self.write("assistant_message", text=frame.text)
        elif isinstance(frame, LLMThoughtStartFrame):
            self._thought = []
        elif isinstance(frame, LLMThoughtTextFrame):
            self._thought.append(frame.text)
        elif isinstance(frame, LLMThoughtEndFrame):
            self.write("llm_thought", text="".join(self._thought))
            self._thought = []
        elif isinstance(frame, FunctionCallResultFrame):
            self.write(
                "tool_call",
                name=frame.function_name,
                arguments=frame.arguments,
                result=frame.result,
                error=frame.error,
            )
        elif isinstance(frame, MetricsFrame):
            self._count_usage(frame)
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, VADUserStartedSpeakingFrame) and self._bot_speaking:
            self._barge_in_at = data.timestamp
        elif isinstance(frame, InterruptionFrame) and self._barge_in_at is not None:
            self._interrupted = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
            # Time from the participant starting to speak over the agent to the agent falling silent.
            if self._interrupted and self._barge_in_at is not None:
                self.write("interruption_latency", seconds=round((data.timestamp - self._barge_in_at) / 1e9, 3))
            self._barge_in_at = None
            self._interrupted = False

    def _count_usage(self, frame: MetricsFrame):
        """Add a metrics frame's token, character and audio-second counts to the running totals."""
        for item in frame.data:
            if isinstance(item, LLMUsageMetricsData):
                self._add("prompt_tokens", item.value.prompt_tokens)
                self._add("completion_tokens", item.value.completion_tokens)
            elif isinstance(item, TTSUsageMetricsData):
                self._add("tts_characters", item.value)
            elif isinstance(item, STTUsageMetricsData):
                self._add("stt_audio_seconds", item.value.audio_seconds)

    def _add(self, counter: str, amount: float):
        """Add to one usage counter for both the turn and the session."""
        self._turn_usage[counter] += amount
        self._session_usage[counter] += amount

    async def _on_turn_started(self, _observer, turn: int):
        """Number every following line with the new turn."""
        self._turn = turn
        self.write("turn_started")

    async def _on_turn_ended(self, _observer, turn: int, duration: float, interrupted: bool):
        """Close the turn with its duration, whether it was cut off, and what it used."""
        self._interrupted_turns += interrupted
        self.write("turn_ended", duration_s=round(duration, 3), interrupted=interrupted, **self._turn_usage)
        self._turn_usage = dict.fromkeys(_USAGE, 0)

    async def _on_latency_measured(self, _observer, seconds: float):
        """Record how long the participant waited between stopping speaking and hearing the agent."""
        self.write("response_latency", seconds=round(seconds, 3))

    async def _on_latency_breakdown(self, _observer, breakdown: LatencyBreakdown):
        """Record where that wait went, stage by stage, including each service's time to first byte."""
        self.write("latency_breakdown", **breakdown.model_dump(mode="json"))

    async def _on_first_speech(self, _observer, seconds: float):
        """Record how long the client waited from connecting to hearing the agent's first audio."""
        self.write("first_speech_latency", seconds=round(seconds, 3))
