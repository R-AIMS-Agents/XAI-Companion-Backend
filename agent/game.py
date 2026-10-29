"""Game events from the client: each snapshot goes into the LLM context, and its reaction decides whether and when the agent speaks about it."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMMessagesTransformFrame,
    LLMRunFrame,
    LLMTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.utils.utils import obj_id

from agent.observability.study_log import StudyLog

# Says where the snapshot comes from, since Mistral receives it as a user message.
HEADER = "Game state update from the client. The participant did not say this."

# How long the agent has to stay idle before a held reaction runs, so a user turn about to run the LLM gets there first.
GRACE_S = 0.3


class Reaction(Enum):
    """What a game event makes the agent do once its snapshot is in the context."""

    SILENT = "silent"
    WHEN_IDLE = "when_idle"
    INTERRUPT = "interrupt"


class Game(BaseObserver):
    """Keeps the newest game snapshot in the LLM context and runs the LLM when an event calls for it, once nobody is speaking and no reply is underway."""

    def __init__(
        self,
        reaction: Callable[[dict[str, Any]], Reaction],
        queue: Callable[[list[Frame]], Awaitable[None]],
        study: StudyLog,
        **kwargs,
    ):
        """Take the scenario's reaction table, the worker's way to queue frames, and the study log every event is written to."""
        super().__init__(observe_every_push=False, **kwargs)
        self._reaction = reaction
        self._queue = queue
        self._study = study
        self._snapshot: dict[str, Any] | None = None
        self._opened = False
        # A reaction that waits for the agent to be idle, and the id frames created after the snapshot entered the context are above.
        self._owed = False
        self._entered: int | None = None
        self._user_speaking = False
        self._replying = False
        self._reply_unheard = False
        self._bot_speaking = False
        self._timer: asyncio.TimerHandle | None = None
        self._run: asyncio.Task | None = None

    async def receive(self, snapshot: dict[str, Any]):
        """Put a snapshot into the context in place of the previous one and act on its event; the session's first snapshot opens the conversation."""
        if self._opened:
            reaction = self._reaction(snapshot)
            label = reaction.value
        else:
            self._opened = True
            reaction = Reaction.WHEN_IDLE
            label = "opening"
        self._study.write("game_event", reaction=label, data=snapshot)

        frames: list[Frame] = [LLMMessagesTransformFrame(transform=self._swap_in(snapshot), run_llm=False)]
        if reaction is Reaction.INTERRUPT and not self._user_speaking:
            self._owed = False
            await self._queue([InterruptionFrame(), *frames, LLMRunFrame()])
            return
        await self._queue(frames)
        if reaction is not Reaction.SILENT:
            self._owed = True
            self._reconsider()

    def _swap_in(self, snapshot: dict[str, Any]) -> Callable[[list], list]:
        """Build the context transform that drops the previous snapshot and appends this one, noting when it ran."""
        previous = self._snapshot
        message = {"role": "developer", "content": f"{HEADER}\n{json.dumps(snapshot, ensure_ascii=False)}"}
        self._snapshot = message
        self._entered = None

        def swap(messages: list) -> list:
            """Runs inside the user aggregator, so a frame created from here on is built on a context holding this snapshot."""
            self._entered = obj_id()
            return [m for m in messages if m is not previous] + [message]

        return swap

    async def on_push_frame(self, data: FramePushed):
        """Follow who is speaking and whether a reply is underway, and let a held reaction run once neither is."""
        frame = data.frame
        if isinstance(frame, UserStartedSpeakingFrame):
            self._user_speaking = True
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
        elif isinstance(frame, LLMContextFrame):
            self._replying = True
            # A run built on a context that already holds the snapshot answers it, so the held reaction is settled.
            if self._entered is not None and frame.id > self._entered:
                self._owed = False
        elif isinstance(frame, LLMTextFrame) and frame.text.strip():
            self._reply_unheard = True
        elif isinstance(frame, LLMFullResponseEndFrame):
            self._replying = False
        elif isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
            self._reply_unheard = False
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False
        elif isinstance(frame, InterruptionFrame):
            self._replying = False
            self._reply_unheard = False
        else:
            return
        self._reconsider()

    def _idle(self) -> bool:
        """Whether nobody is speaking and no reply is generating or waiting to be heard."""
        return not (self._user_speaking or self._replying or self._reply_unheard or self._bot_speaking)

    def _reconsider(self):
        """Restart the grace period while a reaction is held and the agent is idle, and drop it whenever the agent gets busy."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._owed and self._idle():
            self._timer = asyncio.get_running_loop().call_later(GRACE_S, self._fire)

    def _fire(self):
        """Run the LLM on the context as it stands, which holds the newest snapshot."""
        self._timer = None
        self._owed = False
        self._run = asyncio.create_task(self._queue([LLMRunFrame()]))
