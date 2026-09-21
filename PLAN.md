# Plan

## Stack

Pipecat pipeline, LiveKit as transport, Unity client in a separate project.
LiveKit server runs self-hosted on the dev machine. Join tokens are printed on startup and pasted into Unity for now.

## Milestone 1 - prove the transport

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

Not yet: derived metrics, events, anything study related.

## Milestone 2 - transport comparison

Add `transports/websocket.py` using Pipecat's `WebsocketServerTransport`, the previous project's transport.
Same pipeline, same observer, one flag. This is only meaningful if the Unity side logs its timeline identically on both paths.

## Milestone 3 - the agent

STT, LLM and TTS, selected in one place. Derived metrics: time to first audio, turn latency, interruption latency.

## Milestone 4 - study platform

Session identity, study configuration, per-session JSONL logs. Transcripts and events only, never audio.
Conditions are configuration: interaction modality, explanation behaviour, embodiment, voice.
