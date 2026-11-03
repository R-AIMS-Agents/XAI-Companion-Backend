# XAI-Companion

**A study platform for transparent, trustworthy AI Agents in XR.**

Backend for an Intelligent Virtual Agent, an embodied AI human in VR/AR, built as a reusable platform for user studies on transparent and explainable agents in XR. Pipecat orchestrates the AI models; LiveKit carries audio and data to a Unity client, which is a separate project.

![The Unity client exchanges audio and data with the Pipecat agent through the LiveKit server; the agent writes the session logs.](docs/overview.svg)

## Setup

Windows, with [uv](https://docs.astral.sh/uv/) installed. uv fetches Python 3.14 itself.

1. Install the dependencies.

   ```powershell
   uv sync
   ```

2. Copy `.env.example` to `.env` and fill in the API keys.

3. Download `livekit-server.exe` from the [LiveKit releases](https://github.com/livekit/livekit/releases) into the project root. The agent starts it when nothing listens on `LIVEKIT_URL` yet.

4. Optional, for `--stt nemotron`: a local NVIDIA NIM container from `nemotron.compose.yaml`, which needs Docker Desktop, an NVIDIA GPU and an [NGC API key](https://org.ngc.nvidia.com/setup/api-keys). Put `NGC_API_KEY` in `.env`, log in with `docker login nvcr.io` (user `$oauthtoken`, the key as password), then build the model once:

   ```powershell
   docker compose -f nemotron.compose.yaml run --rm nemotron-export
   ```

   This takes about 15 minutes and writes the built model to `%USERPROFILE%\nim_export`. Run it only once: it rebuilds from scratch each time, and the build only barely fits an 8 GB GPU, so close Unity and the headset software first. From then on the dialog starts the container as soon as `nemotron` is selected, or the agent does at the start of a scripted run. It takes about 40 s and stays running for the next session.

## Running

### Interactive

```powershell
uv run python -m agent.run
```

A dialog asks for participant ID, language, scenario and models.

> [!NOTE]
> IDs of the form `P` and a number, such as `P04`, count as study participants. Any other ID, such as `test`, is for development.

### Scripted

Naming everything on the command line skips the dialog:

```powershell
uv run python -m agent.run `
    --participant test `
    --language en `
    --scenario chat `
    --stt nemotron `
    --llm mistral-small `
    --tts elevenlabs-flash
```

### Without Unity

`tools.local_client` lets you talk to the agent through the local microphone and speakers without Unity. It currently works with the `chat` scenario only: `lab` opens on Unity's first game snapshot, which the local client never sends. Start the XAI-Companion first, then the client in a second terminal:

```powershell
uv run python -m tools.local_client
```

### Logs

Each session writes a study log and a debug log under `logs/`.

### Tests

- `uv run pytest`

- `tests/test_live_client.py` checks the Unity protocol against a running agent: token, handshake and camera track. Run with `uv run pytest -m live`

## Adding a model

Every model is a named entry in `agent/services/catalog.py`, and a new entry shows up on the command line and in the dialog at once.

| Adding…                                 | What to change                                                                                                                                                                                                                                                                                                                      |
|-----------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Another model from an existing provider | One line in the `STT`, `LLM` or `TTS` registry, such as `"mistral-large": partial(_mistral_llm, model="mistral-large-latest")`.                                                                                                                                                                                                     |
| A new provider                          | A factory beside the others that builds its Pipecat service and imports it inside the function.<br/>Add the provider's extra to `pipecat-ai[...]` in `pyproject.toml` and run `uv sync`.<br/>If it needs a key, add it to `Config` and `load()` in `agent/config.py`, to `.env.example`, and read it in the factory with `_demand`. |
| A voice                                 | Also an entry in `TTS_LANGUAGES` naming the session languages it speaks.                                                                                                                                                                                                                                                            |

## Further reading

| Document                             | What it covers                                                          |
|--------------------------------------|-------------------------------------------------------------------------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Data flow, configuration seams, the Unity contract and the log formats. |
| `agent/scenarios/<name>/README.md`   | What each scenario is about and which game events it takes.             |
| [`ROADMAP.md`](ROADMAP.md)           | Upcoming work.                                                          |
