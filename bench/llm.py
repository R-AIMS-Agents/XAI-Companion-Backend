"""LLM benchmark: replays scripted conversations from bench/cases/llm against a catalog LLM, through the same Pipecat service and context aggregators a session uses, and records what it said, how fast, and which checks it passed."""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    FunctionCallsStartedFrame,
    LLMMessagesAppendFrame,
    LLMMessagesTransformFrame,
    LLMRunFrame,
    LLMTextFrame,
    MetricsFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData, TTFBMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.llm_service import FunctionCallParams, LLMService
from pipecat.utils.types import NOT_GIVEN
from pipecat.workers.runner import WorkerRunner

from agent import config, scenarios
from agent.game import HEADER, START_TASK, STARTED
from agent.services import catalog
from bench import checks, record

CASES = Path(__file__).resolve().parent / "cases" / "llm"

# The catalog entry that grades every candidate, the same for all of them so their scores compare.
JUDGE = "mistral-large"

# The judge is never spoken, so it reasons as much as it can rather than as little as a session needs.
JUDGE_REASONING = "high"

# How long one LLM run may take before the step is recorded as failed.
TIMEOUT_S = 60.0

# Mistral accepts only tool call ids of nine letters and digits.
TOOL_CALL_ID = "benchcall"


@dataclass
class Reply:
    """What the LLM produced for one step, across every run it took, such as a tool call followed by the text after its result."""

    text: str = ""
    tools: list[str] = field(default_factory=list)
    first_text_s: float | None = None
    duration_s: float | None = None
    ttfb_s: list[float] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None


class Conversation(BaseObserver):
    """One scripted session with an LLM: the context aggregators around it in a pipeline, driven a step at a time, with every frame the LLM pushes gathered into the step's reply."""

    def __init__(self, llm: LLMService, system_prompt: str, greeting: str | None, tools: list):
        """Assemble the pipeline on a context that opens with the system prompt and, when the scenario has one, its spoken greeting."""
        super().__init__(observe_every_push=False)
        messages = [{"role": "system", "content": system_prompt}]
        if greeting:
            messages.append({"role": "assistant", "content": greeting})
        aggregators = LLMContextAggregatorPair(LLMContext(messages=messages, tools=tools or NOT_GIVEN))
        aggregators.assistant().add_event_handler("on_assistant_turn_stopped", self._on_turn_stopped)
        self._llm = llm
        self._worker = PipelineWorker(
            Pipeline([aggregators.user(), llm, aggregators.assistant()]),
            params=PipelineParams(enable_metrics=True, enable_usage_metrics=True),
            observers=[self],
            idle_timeout_secs=None,
        )
        self._runner = WorkerRunner(handle_sigint=False)
        self._running: asyncio.Task | None = None
        self._snapshot: dict | None = None
        self._reply = Reply()
        self._started = 0.0
        self._calling = False
        self._done = asyncio.Event()

    async def start(self):
        """Start the pipeline in the background."""
        await self._runner.add_workers(self._worker)
        self._running = asyncio.create_task(self._runner.run())

    async def stop(self):
        """End the pipeline once it has processed everything queued, and wait for it."""
        await self._worker.stop_when_done()
        if self._running is not None:
            await self._running

    async def append(self, messages: list[dict[str, Any]]):
        """Put messages into the context without running the LLM, for history a case states rather than generates."""
        await self._worker.queue_frames([LLMMessagesAppendFrame(messages=messages, run_llm=False)])

    async def say(self, text: str, run: bool) -> Reply | None:
        """Add a participant line to the context and, when asked, return the LLM's reply to it."""
        frame = LLMMessagesAppendFrame(messages=[{"role": "user", "content": text}], run_llm=run)
        if not run:
            await self._worker.queue_frames([frame])
            return None
        return await self._run([frame])

    async def show(self, snapshot: dict[str, Any], run: bool) -> Reply | None:
        """Swap a game snapshot into the context in place of the previous one, as the game does, and, when asked, return the LLM's reply to it."""
        previous = self._snapshot
        message = {"role": "developer", "content": f"{HEADER}\n{json.dumps(snapshot, ensure_ascii=False)}"}
        self._snapshot = message
        frames: list[Frame] = [
            LLMMessagesTransformFrame(transform=lambda ms: [m for m in ms if m is not previous] + [message], run_llm=False)
        ]
        if not run:
            await self._worker.queue_frames(frames)
            return None
        return await self._run([*frames, LLMRunFrame()])

    async def _run(self, frames: list[Frame]) -> Reply:
        """Queue frames that run the LLM and wait until its reply, including any run after a tool result, is in the context."""
        self._reply = Reply()
        self._calling = False
        self._done.clear()
        self._started = time.perf_counter()
        await self._worker.queue_frames(frames)
        try:
            await asyncio.wait_for(self._done.wait(), TIMEOUT_S)
        except TimeoutError:
            self._reply.error = f"no reply within {TIMEOUT_S:.0f}s"
        self._reply.duration_s = round(time.perf_counter() - self._started, 3)
        return self._reply

    async def _on_turn_stopped(self, _aggregator, _message):
        """Finish the step when a response has reached the context, unless it called a tool, whose result runs the LLM again."""
        if self._calling:
            self._calling = False
            return
        self._done.set()

    async def on_push_frame(self, data: FramePushed):
        """Gather the text, tool calls, latency and token usage the LLM pushes, and end the step on an error from anywhere."""
        frame = data.frame
        if isinstance(frame, ErrorFrame):
            self._reply.error = frame.error
            self._done.set()
            return
        if data.source is not self._llm:
            return
        if isinstance(frame, LLMTextFrame):
            if self._reply.first_text_s is None and frame.text.strip():
                self._reply.first_text_s = round(time.perf_counter() - self._started, 3)
            self._reply.text += frame.text
        elif isinstance(frame, FunctionCallsStartedFrame):
            self._calling = True
            self._reply.tools += [call.function_name for call in frame.function_calls]
        elif isinstance(frame, MetricsFrame):
            for metric in frame.data:
                if isinstance(metric, TTFBMetricsData):
                    self._reply.ttfb_s.append(round(metric.value, 3))
                elif isinstance(metric, LLMUsageMetricsData):
                    self._reply.prompt_tokens += metric.value.prompt_tokens
                    self._reply.completion_tokens += metric.value.completion_tokens


def _tool_call(name: str) -> list[dict[str, Any]]:
    """Return the context messages of a tool call and its result as a session leaves them, for history that has already passed a tool call."""
    return [
        {
            "role": "assistant",
            "tool_calls": [{"id": TOOL_CALL_ID, "type": "function", "function": {"name": name, "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": TOOL_CALL_ID, "content": json.dumps(STARTED)},
    ]


def _setup(case: dict[str, Any]) -> tuple[str, str | None, list]:
    """Return the system prompt, greeting and tools a session of the case's scenario and language starts with."""
    scenario = scenarios.SCENARIOS[case["scenario"]]
    greeting = scenario.greeting[case["language"]] if scenario.greeting else None
    intro = scenario.reaction is not None and greeting is not None
    return scenario.system_prompt(case["language"]), greeting, [START_TASK] if intro else []


def setup_hash(case: dict[str, Any]) -> str:
    """Hash everything the scenario puts in front of the LLM, so results from before a prompt change are not compared with results after it."""
    system_prompt, greeting, tools = _setup(case)
    return record.digest([system_prompt, greeting, [tool.to_default_dict() for tool in tools], STARTED, HEADER])


async def run_case(llm: LLMService, judge: LLMService, case: dict[str, Any]) -> dict[str, Any]:
    """Play one case through the LLM once and return every step's reply, measurements and checks, and the checks on the whole conversation."""
    system_prompt, greeting, tools = _setup(case)
    for tool in tools:
        llm.register_function(tool.name, _start_task)
    conversation = Conversation(llm, system_prompt, greeting, tools)
    transcript: list[tuple[str, str]] = [("agent", greeting)] if greeting else []
    steps = []
    await conversation.start()
    try:
        for index, step in enumerate(case["steps"]):
            reply = None
            if "game" in step:
                transcript.append(("game", json.dumps(step["game"], ensure_ascii=False)))
                reply = await conversation.show(step["game"], step.get("run", False))
            elif "say" in step:
                transcript.append(("participant", step["say"]))
                reply = await conversation.say(step["say"], step.get("run", True))
            elif "agent" in step:
                transcript.append(("agent", step["agent"]))
                await conversation.append([{"role": "assistant", "content": step["agent"]}])
            elif "tool" in step:
                transcript.append(("tool", step["tool"]))
                await conversation.append(_tool_call(step["tool"]))
            if reply is None:
                continue
            transcript += [("tool", name) for name in reply.tools]
            transcript.append(("agent", reply.text))
            passed, reasons = await checks.evaluate(
                step.get("expect", []), reply.text, reply.tools, judge, transcript, len(transcript) - 1
            )
            steps.append(
                {
                    "step": index,
                    **vars(reply),
                    **checks.measure(reply.text),
                    "checks": {**checks.automatic(reply.text), **passed},
                    "reasons": reasons,
                }
            )
            if reply.error:
                break
    finally:
        await conversation.stop()
    error = next((step["error"] for step in steps if step["error"]), None)
    passed, reasons = {}, {}
    if error is None:
        spoken = " ".join(what for who, what in transcript if who == "agent")
        called = [what for who, what in transcript if who == "tool"]
        passed, reasons = await checks.evaluate(case.get("expect", []), spoken, called, judge, transcript, None)
    return {"steps": steps, "checks": passed, "reasons": reasons, "error": error}


async def _start_task(params: FunctionCallParams):
    """Answer start_task as the game does, so the LLM continues from the same result a session gives it."""
    await params.result_callback(STARTED)


def build(name: str, cfg: config.Config, **overrides: str | None) -> LLMService:
    """Build a catalog LLM with any of the arguments its entry binds replaced, such as an older snapshot or the reasoning effort that snapshot accepts; an override of None keeps the entry's own."""
    factory = catalog.LLM[name]
    overrides = {key: value for key, value in overrides.items() if value is not None}
    unbound = [key for key in overrides if not (isinstance(factory, partial) and key in factory.keywords)]
    if unbound:
        sys.exit(f"'{name}' does not bind {', '.join(unbound)}, so it cannot be replaced.")
    return factory(cfg, **overrides)


def load(names: list[str] | None) -> dict[str, dict[str, Any]]:
    """Read the named cases, or every case, by the file name they are known by."""
    paths = sorted(CASES.glob("*.json"))
    cases = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in paths}
    if names:
        unknown = set(names) - cases.keys()
        if unknown:
            sys.exit(f"Unknown cases: {', '.join(sorted(unknown))}")
        cases = {name: cases[name] for name in names}
    return cases


async def main():
    """Run the chosen cases until each has the requested number of error-free repetitions for this model, setup and judge."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", required=True, choices=sorted(catalog.LLM), help="catalog entry to measure")
    parser.add_argument("--model", help="snapshot to measure in place of the entry's own, such as an older one")
    parser.add_argument(
        "--reasoning",
        choices=["none", "low", "medium", "high"],
        help="reasoning effort in place of the entry's own, for a snapshot that does not accept it",
    )
    parser.add_argument("--case", nargs="*", help="cases to run, by file name; default: all")
    parser.add_argument("--reps", type=int, default=5, help="error-free repetitions each case should have (default: 5)")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    cfg = config.load()
    judge = build(JUDGE, cfg, reasoning_effort=JUDGE_REASONING)
    judge_hash = record.digest([record.settings(judge), checks.JUDGE_SYSTEM, checks.JUDGE_SCHEMA])
    candidate = build(args.llm, cfg, model=args.model, reasoning_effort=args.reasoning)
    model = candidate.settings.model
    done = record.read("llm")

    for name, case in load(args.case).items():
        key = {
            "model": model,
            "settings": record.settings(candidate),
            "case": name,
            "case_hash": record.digest(case),
            "setup_hash": setup_hash(case),
            "judge": judge.settings.model,
            "judge_hash": judge_hash,
        }
        have = sum(1 for line in done if line["error"] is None and all(line[k] == v for k, v in key.items()))
        for rep in range(have, args.reps):
            result = await run_case(build(args.llm, cfg, model=args.model, reasoning_effort=args.reasoning), judge, case)
            record.append("llm", {"llm": args.llm, **key, "rep": rep, **result})
            verdicts = [item for step in result["steps"] for item in step["checks"].items()]
            verdicts += list(result["checks"].items())
            failed = [check for check, ok in verdicts if ok is False]
            unjudged = [check for check, ok in verdicts if ok is None]
            status = result["error"] or ", ".join(
                [f"failed {', '.join(failed)}"] * bool(failed) + [f"unjudged {', '.join(unjudged)}"] * bool(unjudged)
            ) or "passed"
            print(f"{model} {name} rep {rep + 1}/{args.reps}: {status}")
        if have >= args.reps:
            print(f"{model} {name}: {have} repetitions already recorded")


if __name__ == "__main__":
    asyncio.run(main())
