# ARCHITECTURE-SUGGESTION.md

Backend and client design for the VR conversational agent. Pipecat pipeline, LiveKit
WebRTC transport, Unity client.

> Scope: module setup only. Consent, disclosure, study instrumentation and domain
> content are deliberately out of scope here and get their own documents once the
> pipeline is proven.

## 0. Organizing principle

Every module boundary below sits where a timing bug would need to be bisected.

The last project's two open problems were audio stutter at each turn start and
interruption behaviour. Both are timing problems spanning two processes and two
clocks, and both were hard to localise because the backend and client could not be
isolated from each other or observed on a shared timeline. This design fixes that
structurally rather than by convention:

- The pipeline is transport-agnostic, so the client can be removed from the picture
  with one flag.
- A frame observer records a timestamped backend timeline without being part of the
  pipeline.
- The client keeps its own timeline and ships it back, so both halves land on one
  clock.

Everything else is ordinary Pipecat.

## 1. Stack

- Pipecat (latest 1.x), managed with `uv`
- LiveKit for WebRTC transport, via Pipecat's `LiveKitTransport`
- Unity client using the LiveKit Unity SDK
- STT / LLM / TTS services chosen in `config.py`, not hardcoded in the pipeline

LiveKit is used as a transport only. The agent logic stays in Pipecat's frame
pipeline; LiveKit Agents is not used. These are separable choices and only the
transport half is worth taking.

## 2. Backend module map

```
pyproject.toml
.env.example
src/agent/
  config.py                 # service catalog + env; the one place to swap STT/LLM/TTS
  pipeline.py               # builds the pipeline; the ONLY place it is assembled
  run.py                    # entrypoint: --transport livekit|local
  transports/
    livekit.py              # LiveKitTransport construction + token minting
    local.py                # LocalAudioTransport, headless
  events/
    schema.py               # pydantic models for app messages, both directions
    inbound.py              # app message frame -> typed event
    outbound.py             # typed event -> LiveKitOutputTransportMessage(Urgent)Frame
  observability/
    timeline.py             # FrameObserver: timestamped frame log
    metrics.py              # derived: TTFB, turn latency, interruption latency
```

### 2.1 `pipeline.py` takes a transport as an argument

`pipeline.py` receives a transport and knows nothing else about it. It never imports
from `transports/`. This makes `--transport local` versus `--transport livekit` a
one-flag A/B with every other component identical, which is the client-versus-backend
bisect, permanently available rather than reconstructed each time something breaks.

This is the single most important constraint in this document. If a change makes the
pipeline aware of which transport it is running on, that change is wrong.

### 2.2 `observability/timeline.py`

A Pipecat `FrameObserver` sees every frame moving through the pipeline without being a
processor in it. It records timestamps for at least:

- `UserStartedSpeakingFrame`, `UserStoppedSpeakingFrame`
- `TranscriptionFrame`
- `LLMFullResponseStartFrame`
- `TTSStartedFrame`, first `TTSAudioRawFrame`
- `InterruptionFrame`
- `BotStartedSpeakingFrame`, `BotStoppedSpeakingFrame`

Build this before the AI services. It is the instrument everything else is debugged
with, and it costs nothing at runtime when disabled.

`metrics.py` derives the numbers that matter from that log rather than measuring them
inline: time to first audio byte, total turn latency, and interruption latency
(user speech onset to bot audio actually stopping in the client).

### 2.3 `events/`

Typed app messages in both directions, defined once in `schema.py` so the Unity side
has a single contract to mirror. Two delivery classes:

- Queued (`LiveKitOutputTransportMessageFrame`) for anything that belongs in sequence
  with speech.
- Urgent (`LiveKitOutputTransportMessageUrgentFrame`) for anything that must not be
  delivered behind queued TTS audio: game state, and the interruption flush below.

Inbound, LiveKit delivers data packets as UTF-8 text, so messages are JSON. Audio is a
WebRTC track and is never an app message; there is no binary framing to maintain.

## 3. Unity module map

```
Assets/Scripts/Agent/
  AgentConnection.cs        # LiveKit room join, token fetch
  AgentAudio.cs             # track playback + prebuffer + underrun counter
  AgentEvents.cs            # typed data channel send/receive, mirrors events/schema.py
  AgentTimeline.cs          # local timestamped log, shipped back as app messages
  AgentDebugHud.cs          # in-world overlay: buffer depth, underruns, RTT, state
```

### 3.1 `AgentAudio.cs`

The LiveKit SDK owns jitter buffering and track playback, so this module is thin. It
stays a separate module anyway because it is where the previous project's stutter
lived, and it needs instrumentation regardless of who owns the buffer:

- One `AudioSource` that plays continuously for the whole session. Never stopped and
  restarted per turn, never one `AudioClip` per utterance or per chunk.
- A prebuffer before releasing audio at the start of a turn, if hand-rolling playback.
- A cumulative underrun counter, exposed to the HUD.

Check `AudioSettings.outputSampleRate` against the TTS output rate at startup and log
a warning on mismatch.

### 3.2 `AgentDebugHud.cs`

Not optional. The failure modes reproduce in the headset, and a console cannot be read
with a headset on. Buffer depth, cumulative underruns, RTT and connection state are
visible in-world from the first build.

### 3.3 `AgentTimeline.cs`

The client half of the shared timeline: playback start, first sample rendered, underrun
events, buffer flushes, with local timestamps. Shipped back to the backend as app
messages so both halves can be correlated. Without both halves on one clock, a stutter
diagnosis is guesswork.

## 4. Interruption

Pipecat cancels downstream work on `InterruptionFrame`, but audio already sitting in
the client's jitter buffer keeps playing, so the agent talks over the user for a few
hundred milliseconds after it should have stopped.

Therefore: on interruption the backend sends an urgent app message instructing the
client to drop its audio buffer, and the client flushes on receipt and reports the
flush on its timeline.

This is designed in from the start because retrofitting it means touching both sides
and re-testing the whole turn-taking path.

## 5. Build order

Each step is testable on its own and each removes a class of variance from the next.

1. **Loopback.** Transport in, transport out. No STT, no LLM, no TTS. Unity speaks and
   hears itself. This isolates the audio path completely: a stutter here is transport
   or playback and nothing else can be blamed.
2. **TTS only.** A fixed sentence triggered by a Unity button. Isolates TTS chunk
   pacing from ASR and LLM latency variance.
3. **Full loop.** STT, LLM, TTS.
4. **Interruption tests.** Barge-in at several points in a bot turn, measured against
   the timeline from both sides.

Steps 1 and 2 are where audio timing problems get resolved. By step 3 they should
already be answered, because adding an LLM introduces latency variance that masks
buffer problems.

## 6. Open questions

- **Standalone headset or PCVR.** Decides how much WebRTC is actually buying. On
  same-machine PCVR the jitter buffer and congestion control solve problems that do not
  exist; on a standalone headset over Wi-Fi they matter a great deal, as does client
  side echo cancellation.
- **LiveKit Unity SDK platform support** for the target headset. This is the main
  integration risk and is worth a spike before anything else in this document is built.
  If the SDK does not support the target, `AgentAudio.cs` grows back into a full
  hand-rolled ring buffer and the prebuffer above becomes mandatory rather than
  a fallback.

## 7. Embodiment

Out of scope for this document, but noted so it is not rediscovered: no voice framework
supplies FML or BML. Behaviour markup lives in ECA realizers (Greta/VIB, SmartBody,
AsapRealizer), which are generally more integration cost than hand-rolled Unity
animation unless gesture or gaze is an independent variable in the study. Embodiment is
Unity work under any backend choice, and it does not constrain anything above.
