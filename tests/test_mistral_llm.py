"""Mistral's thinking reaches the pipeline as thought frames, its answer as text, and the voice never hears the thinking."""

from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta
from pipecat.frames.frames import LLMThoughtEndFrame, LLMThoughtStartFrame, LLMThoughtTextFrame

from agent.services.mistral_llm import ThinkingMistralLLMService


def _thinking(text: str) -> list[dict]:
    """A content delta carrying one piece of thinking, as Mistral streams it."""
    return [{"type": "thinking", "thinking": [{"type": "text", "text": text}], "closed": True}]


# The chunk where Mistral moves from thinking to answering: an empty thinking part beside the first answer text.
HANDOVER = [{"type": "thinking", "thinking": []}, {"type": "text", "text": "No, "}]


def _chunk(content=None, tool_calls=None) -> ChatCompletionChunk:
    """A streamed chunk built unvalidated, as the OpenAI SDK builds them, since a list is not a valid content type to its schema."""
    delta = ChoiceDelta.model_construct(content=content, tool_calls=tool_calls)
    return ChatCompletionChunk.model_construct(choices=[Choice.model_construct(delta=delta, index=0)])


class _Stream:
    """Stand-in for the OpenAI stream: yields the given chunks and records being closed."""

    def __init__(self, chunks: list[ChatCompletionChunk]):
        """Hold the chunks to yield."""
        self._chunks = chunks
        self.closed = False

    def __aiter__(self):
        """Yield the chunks in order."""
        return self._iterate()

    async def _iterate(self):
        """Yield the chunks in order."""
        for chunk in self._chunks:
            yield chunk

    async def close(self):
        """Record that the stream was closed."""
        self.closed = True


async def _run(chunks: list[ChatCompletionChunk]) -> tuple[list, list, _Stream]:
    """Pass chunks through the split and return the frames it pushed, the content the base loop sees, and the stream."""
    llm = ThinkingMistralLLMService(api_key="test")
    pushed = []

    async def push_frame(frame, *_args, **_kwargs):
        """Collect a pushed frame."""
        pushed.append(frame)

    llm.push_frame = push_frame
    stream = _Stream(chunks)
    contents = [chunk.choices[0].delta.content async for chunk in llm._split_thinking(stream)]
    return pushed, contents, stream


async def test_thinking_becomes_one_thought_and_the_answer_stays_text():
    """Thinking streamed over several chunks is one thought, and the handover chunk keeps its first answer words."""
    pushed, contents, _ = await _run([_chunk(_thinking("The user")), _chunk(_thinking(" asks.")), _chunk(HANDOVER), _chunk("391 is not prime.")])
    assert [type(frame) for frame in pushed] == [LLMThoughtStartFrame, LLMThoughtTextFrame, LLMThoughtTextFrame, LLMThoughtEndFrame]
    assert "".join(frame.text for frame in pushed if isinstance(frame, LLMThoughtTextFrame)) == "The user asks."
    assert contents == [None, None, "No, ", "391 is not prime."]


async def test_a_reply_without_thinking_passes_through_untouched():
    """A model answering straight away sees no change."""
    pushed, contents, _ = await _run([_chunk("Hallo"), _chunk(" Mirko.")])
    assert pushed == []
    assert contents == ["Hallo", " Mirko."]


async def test_a_tool_call_ends_the_thought():
    """A turn that thinks and then calls a tool closes its thought before the call."""
    pushed, _, _ = await _run([_chunk(_thinking("Ready, so start.")), _chunk(tool_calls=[object()])])
    assert [type(frame) for frame in pushed] == [LLMThoughtStartFrame, LLMThoughtTextFrame, LLMThoughtEndFrame]


async def test_a_stream_that_ends_while_thinking_still_ends_the_thought_and_closes():
    """A stream cut off mid-thought still ends the thought and releases the HTTP stream."""
    pushed, _, stream = await _run([_chunk(_thinking("Hmm"))])
    assert isinstance(pushed[-1], LLMThoughtEndFrame)
    assert stream.closed
