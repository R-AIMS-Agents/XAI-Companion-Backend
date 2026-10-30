"""Frame observer that records every LLM call in full: the context it was given, the tool calls it made, and the text it returned."""

import json

from loguru import logger

from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import (
    FunctionCallResultFrame,
    FunctionCallsStartedFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.llm_service import LLMService

# Tagged so the debug log can keep these records out of the console.
log = logger.bind(llm=True)


def _snapshot(value):
    """Copy a value into plain JSON types now, since the context it comes from keeps changing after the record is queued."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _tools(context: LLMContext) -> list[dict]:
    """List the tools a context offers the LLM, as their schemas; empty when it offers none."""
    if not isinstance(context.tools, ToolsSchema):
        return []
    return [tool.to_default_dict() for tool in context.tools.standard_tools]


class LLMExchange(BaseObserver):
    """Logs each LLM call's input, tool calls and output to the debug log, for explaining afterwards why the agent said what it said."""

    def __init__(self, **kwargs):
        """Set up the observer with no response in progress."""
        super().__init__(observe_every_push=False, **kwargs)
        self._output: list[str] | None = None

    async def on_push_frame(self, data: FramePushed):
        """Record a context as it enters an LLM, and the calls and text that come out of it."""
        frame = data.frame
        if isinstance(frame, LLMContextFrame) and isinstance(data.destination, LLMService):
            context = frame.context
            log.debug(
                "LLM input",
                messages=_snapshot(context.get_messages()),
                tools=_tools(context),
                speculation=frame.speculation,
            )
        elif not isinstance(data.source, LLMService):
            return
        elif isinstance(frame, LLMFullResponseStartFrame):
            self._output = []
        elif isinstance(frame, LLMTextFrame) and self._output is not None:
            self._output.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame) and self._output is not None:
            log.debug("LLM output", text="".join(self._output))
            self._output = None
        elif isinstance(frame, FunctionCallsStartedFrame):
            for call in frame.function_calls:
                log.debug("LLM tool call", name=call.function_name, arguments=_snapshot(call.arguments))
        elif isinstance(frame, FunctionCallResultFrame):
            log.debug("LLM tool result", name=frame.function_name, result=_snapshot(frame.result), error=frame.error)
