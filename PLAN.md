# Plan

## Stack

Pipecat pipeline, LiveKit as transport, Unity client in a separate project.
LiveKit server runs self-hosted on the dev machine. Join tokens are printed on startup and pasted into Unity for now.

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

`session.py` resolves a run. A field with a single implementation is settled without asking, so the dialog opens only when something is genuinely undecided, and once open it shows the whole session rather than a partial form. A command line that names every model always starts headless. The dialog gains modality and participant ID in milestone 4, at which point it opens every run.

Defaults: Voxtral STT, `mistral-small`, ElevenLabs Flash. Turn-taking is Pipecat's default, Silero VAD to start a turn and Smart Turn v3 to end one, and is fixed rather than selectable until a condition needs to vary it.

Still open: derived metrics - time to first audio, turn latency, interruption latency.

## Milestone 4 - study platform

Session identity, study configuration, per-session JSONL logs. Transcripts and events only, never audio.
Conditions are configuration: interaction modality, explanation behaviour, embodiment, voice.

The system prompt carries the explanation behaviour and the interaction script, so `prompt.py` grows from a placeholder into the largest part of this milestone.
