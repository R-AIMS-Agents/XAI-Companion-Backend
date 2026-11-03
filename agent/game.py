"""Game events from the client: each snapshot goes into the LLM context, and its reaction decides whether and when the agent speaks about it, once any intro is over."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
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
from pipecat.services.llm_service import FunctionCallParams
from pipecat.utils.utils import obj_id

from agent.observability.study_log import StudyLog

# Says where the snapshot comes from, since Mistral receives it as a user message.
HEADER = "Game state update from the client. The participant did not say this."

# How long the agent has to stay idle before a held reaction runs, so a user turn about to run the LLM gets there first.
GRACE_S = 0.3

# How long an event stays what just happened. After that the snapshot stays in the context with its event and detail cleared.
EVENT_TIMEOUT_S = 10.0

# Offered to the LLM in a session with an intro, which ends when the agent calls it.
START_TASK = FunctionSchema(
    name="start_task",
    description="Start the task. Call this only after you have asked the participant whether they are ready to start and they have said yes.",
    properties={},
    required=[],
)

# What start_task returns, last in the context the LLM's next run reads.
STARTED = {"started": True, "next": "Introduce the task as your instructions describe before giving the first step."}


class Reaction(Enum):
    """What a game event makes the agent do once its snapshot is in the context."""

    SILENT = "silent"
    WHEN_IDLE = "when_idle"
    INTERRUPT = "interrupt"


class Game(BaseObserver):
    """Keeps the newest game snapshot in the LLM context and runs the LLM when an event calls for it, once nobody is speaking and no reply is underway, and never during an intro."""

    def __init__(
        self,
        reaction: Callable[[dict[str, Any]], Reaction],
        queue: Callable[[list[Frame]], Awaitable[None]],
        study: StudyLog,
        intro: bool = False,
        **kwargs,
    ):
        """Take the scenario's reaction table, the worker's way to queue frames, the study log every event is written to, and whether the session opens with an intro that holds every reaction until start_task."""
        super().__init__(observe_every_push=False, **kwargs)
        self._reaction = reaction
        self._queue = queue
        self._study = study
        self._snapshot: dict[str, Any] | None = None
        self._latest: dict[str, Any] | None = None
        self._expiry: asyncio.TimerHandle | None = None
        self._expiring: asyncio.Task | None = None
        self._intro = intro
        # A session with an intro has already opened with its greeting, so its first snapshot is no opening.
        self._opened = intro
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
        """Put a snapshot into the context in place of the previous one and act on its event; during an intro nothing acts on it, and otherwise the session's first snapshot opens the conversation."""
        if self._intro:
            reaction = Reaction.SILENT
            label = "intro"
        elif self._opened:
            reaction = self._reaction(snapshot)
            label = reaction.value
        else:
            self._opened = True
            reaction = Reaction.WHEN_IDLE
            label = "opening"
        self._study.write("game_event", reaction=label, data=snapshot)
        self._latest = snapshot
        self._arm_expiry()

        frames: list[Frame] = [LLMMessagesTransformFrame(transform=self._swap_in(snapshot), run_llm=False)]
        if reaction is Reaction.INTERRUPT and not self._user_speaking:
            self._owed = False
            await self._queue([InterruptionFrame(), *frames, LLMRunFrame()])
            return
        await self._queue(frames)
        if reaction is not Reaction.SILENT:
            self._owed = True
            self._reconsider()

    async def start_task(self, params: FunctionCallParams):
        """End the intro, so the reaction table applies from here on, and hand the LLM a result to continue the task from."""
        self._intro = False
        await params.result_callback(STARTED)

    def _arm_expiry(self):
        """Start the newest event's timeout over."""
        if self._expiry is not None:
            self._expiry.cancel()
        self._expiry = asyncio.get_running_loop().call_later(EVENT_TIMEOUT_S, self._expire)

    def _expire(self):
        """Swap in the newest snapshot with its event and detail cleared, so the agent does not take an old event for what just happened; a reaction still waiting on the event keeps it until it has run."""
        self._expiry = None
        if self._owed:
            self._arm_expiry()
            return
        expired = {**self._latest, "event": None, "detail": None}
        frames = [LLMMessagesTransformFrame(transform=self._swap_in(expired), run_llm=False)]
        self._expiring = asyncio.create_task(self._queue(frames))

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
