# Roadmap

Upcoming work only. What is built is described by the code and ARCHITECTURE.md.

## Lab tutor, first runs

The lab scenario is built and has not met the Unity client yet. What the first sessions have to show:

- Whether Iva talks too much, tuned from the `game_event` and turn lines in the study logs. The reaction table in `agent/scenarios/lab/__init__.py` and the prompt are the two places to turn it down.
- Whether the 0.3 s grace and the check that a participant's own turn already answered a snapshot hold up against real pipeline timing.
- A participant's self-talk still triggers a reply every time.
- A prose history of past events, if the newest snapshot proves too little.
- A reply whose text never becomes audio, such as a failing TTS, leaves the agent busy for good, and no reaction runs after it.

## Later

- Conditions and the balancing of participants across them, once the next study defines them: interaction modality, explanation behaviour, embodiment and nonverbals, voice and speech style. A demo condition that skips the study, once there is something to skip.
- The microphone gated on the handshake. Audio input starts on its own today (`audio_in_stream_on_start`); once the Unity client sends `client-ready` that flips, so no participant audio is processed before the scene is up.
- Camera frames for the LLM. Unity publishes its camera and `--vision` decides whether the agent subscribes, but frames never reach the LLM on their own: fetching one is a tool call, once the agent has tools.
- Transport comparison, deferred: `transports/websocket.py` using Pipecat's `WebsocketServerTransport`, behind the existing `--transport` flag. Only meaningful if the Unity side logs its timeline identically on both paths, and only worth doing if a transport problem turns up.
