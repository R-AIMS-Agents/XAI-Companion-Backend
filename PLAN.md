# Plan

## Stack

Pipecat pipeline, LiveKit as transport, Unity client in a separate project.
LiveKit server runs self-hosted on the dev machine, started by the agent when nothing is answering on its port yet and left alone when something is. The agent serves LiveKit's standard token endpoint, so the client fetches where the room is and the token to enter it with rather than being handed one by hand.

Audio enters at 16 kHz, because Silero VAD, Smart Turn and the STT all require it, and leaves at 48 kHz, which is native for both ElevenLabs and LiveKit.

## Milestone 1 - prove the transport - done

Unity joins a LiveKit room, speaks, and hears itself back through the pipeline. No STT, LLM or TTS.
A stutter here is the transport or the client, and nothing else can be blamed.

```
.env.example
agent/
  config.py
  pipeline.py
  run.py
  transports/livekit.py
  observability/timeline.py
```

`pipeline.py` takes the transport as an argument and never imports `transports/`, so a second transport is additive.
The frame observer is built before anything else, so the first run is already instrumented.

Audio proved clean. The loopback processor and its headless peer were removed once the agent replaced them.

## Milestone 2 - transport comparison - deferred

Add `transports/websocket.py` using Pipecat's `WebsocketServerTransport`, the previous project's transport.
Same pipeline, same observer, one flag. This is only meaningful if the Unity side logs its timeline identically on both paths.

Deferred because milestone 1 found no transport problem worth bisecting. The `--transport` flag and the registry behind it stay in place, so this remains one file away.

## Milestone 3 - the agent

STT, LLM and TTS, each selectable by name.

```
agent/
  session.py             # what one run is made of; argparse, then a dialog for whatever is left open
  prompt.py              # what the agent is told it is
  services/catalog.py    # name -> factory, one entry per implementation
  ui/chooser.py          # the dialog
```

`services/catalog.py` is the single source of the model choices: every factory imports its provider inside the function, so selecting one model never loads another's dependencies, and a new entry reaches both the command line and the dialog at once.

`session.py` resolves a run. A field with a single implementation is settled without asking, so the dialog opens only when something is genuinely undecided, and once open it shows the whole session rather than a partial form. A command line that names every model always starts headless. The dialog gains modality and participant ID in milestone 5, at which point it opens every run.

Defaults: Voxtral STT, `mistral-small`, ElevenLabs Flash. Turn-taking is Pipecat's default, Silero VAD to start a turn and Smart Turn v3 to end one, and is fixed rather than selectable until a condition needs to vary it.

Still open: derived metrics - time to first audio, turn latency, interruption latency.

## Milestone 4 - the world channel

Everything that passes between Unity and the agent that is not audio.

LiveKit carries four data paths - data packets, text and byte streams, RPC, data tracks - and Pipecat's transport wires up exactly one of them, data packets, alongside media tracks. On top of the packets Pipecat speaks RTVI, a JSON envelope `PipelineWorker` enables by default, so the agent was publishing its speech and transcript events into the room before this milestone existed. The client implements that envelope rather than a protocol of our own, and gets those events for nothing.

```
agent/world.py           # the non-audio contract with the client; the handshake to start with
agent/join.py            # where the client asks for a room and a token before any of that
tools/client_peer.py     # headless stand-in: joins through the endpoint, announces itself, publishes a camera track
```

What the Unity client has to hold up:

- One reliable data packet per message, `{"label": "rtvi-ai", "type": ..., "id": ..., "data": ...}`. A reliable packet caps at 15 KiB, so anything larger than small JSON is a track or a byte stream, never a packet.
- Unity fetches its connection details from `POST /getToken`, LiveKit's standard token endpoint format: a body naming the room and identity it wants, or an empty one to take the configured defaults, answered with `server_url` and `participant_token`. The Unity SDK's `TokenSourceEndpoint` speaks this already, so nothing is parsed by hand.
- Unity sends `client-ready` naming the RTVI protocol version, 2.1.0. A mismatched major version is answered with an error and the session continues degraded, so the version is pinned on both sides and re-checked on every Pipecat upgrade.
- The agent answers `bot-ready` and opens the conversation. What it opens with comes from the system prompt, so the opening line stays where the conditions vary it.
- Unity receives, with no agent code behind them: `bot-started-speaking`, `bot-stopped-speaking`, `bot-tts-started`, `bot-tts-stopped`, `bot-tts-text` word by word, `bot-output`, `user-started-speaking`, `user-stopped-speaking`, `user-transcription`, `bot-interrupted` and `metrics`. These are the animation and interruption triggers, and nothing has to be invented for them.
- Unity publishes its camera as an ordinary video track, low resolution and low frame rate, and leaves it open. `--vision` decides whether the agent subscribes. Frames are held and never reach the LLM on their own: fetching one is a tool call, and waits for the milestone that gives the agent tools.

Game events and streamed user state are RTVI `client-message`s, aggregated on the Pipecat side, so what the agent perceives stays in the platform rather than in the client. None are defined yet; the first one earns the module that names them.

Still open: audio input starts on its own today (`audio_in_stream_on_start`). Once the Unity client sends `client-ready`, that flips, so the microphone is gated on the handshake and no participant audio is processed before the scene is up.

## Milestone 5 - study platform

Session identity, study configuration, per-session JSONL logs. Transcripts and events only, never audio.
Conditions are configuration: interaction modality, explanation behaviour, embodiment, voice.

The system prompt carries the explanation behaviour and the interaction script, so `prompt.py` grows from a placeholder into the largest part of this milestone.
