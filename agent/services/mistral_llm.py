"""Mistral's chat models with their reasoning split from their answer, so thinking reaches the pipeline as thought frames and never the voice."""

from collections.abc import AsyncIterator

from openai.types.chat import ChatCompletionChunk
from pipecat.frames.frames import LLMThoughtEndFrame, LLMThoughtStartFrame, LLMThoughtTextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.mistral.llm import MistralLLMService


class ThinkingMistralLLMService(MistralLLMService):
    """A Mistral LLM that turns the thinking parts Mistral streams as content into LLMThought frames and passes only the answer on as text."""

    async def get_chat_completions(self, context: LLMContext) -> AsyncIterator[ChatCompletionChunk]:
        """Open the completion stream with its thinking split off."""
        stream = await super().get_chat_completions(context)
        return self._split_thinking(stream)

    async def _split_thinking(self, stream: AsyncIterator[ChatCompletionChunk]) -> AsyncIterator[ChatCompletionChunk]:
        """Push each chunk's thinking as thought frames and rewrite its content to the answer text alone, yielding every chunk for the base loop."""
        thinking = False
        try:
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    yield chunk
                    continue
                if isinstance(delta.content, list):
                    for part in delta.content:
                        if part.get("type") != "thinking":
                            continue
                        text = "".join(piece.get("text", "") for piece in part.get("thinking", []))
                        if text and not thinking:
                            thinking = True
                            await self.push_frame(LLMThoughtStartFrame())
                        if text:
                            await self.push_frame(LLMThoughtTextFrame(text=text))
                    delta.content = "".join(part.get("text", "") for part in delta.content if part.get("type") == "text") or None
                if thinking and (delta.content or delta.tool_calls):
                    thinking = False
                    await self.push_frame(LLMThoughtEndFrame())
                yield chunk
        finally:
            if thinking:
                await self.push_frame(LLMThoughtEndFrame())
            # The base loop closes this wrapper but not the HTTP stream inside it, which would otherwise stay open after an interruption.
            await stream.close()
