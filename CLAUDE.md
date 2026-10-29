# AI-Companion

Backend for an Intelligent Virtual Agent: an embodied AI human in VR/AR.
Pipecat orchestrates the AI models, LiveKit carries audio and data to a Unity client that lives in a separate project folder.

Research context: transparent, responsible and explainable agents for XR, evaluated in user studies.
The deliverable is a reusable study platform, not a one-off agent. One codebase serves every study; conditions are configuration, never copies of the folder.

`ARCHITECTURE.md` describes the data flow, the configuration seams, the Unity contract and the log formats. A change to any of these updates it in the same change.

## Working agreement

- Mirco is the coordinator. He decides scope, order and design.
- Propose a plan, get approval, then execute. Nothing is created, edited or deleted without approval.
- Interview instead of assuming. Routine mechanics are fine to just do; anything that shapes code or architecture is a question.
- Report honestly: what ran, what failed, what was skipped and why.
- Commit only when told. No chat URLs in commit messages.
- Stay in scope. No unrequested extras, refactors or files.
- Be honest in your response.

## Code style

- Comments on one line. The IDE wraps them; never wrap by hand.
- Every module, class and function carries a docstring: one or two sentences on what it is for, not a restatement of its name.
- No change-history, decision-log or rationale comments. A comment says what the code does when that is not obvious.
- Clean pipeline: one direction of data flow, one job per module, no reaching into another module's internals.
- No abstraction before a second caller exists. Small project, keep it small.

## Study platform

- What varies between conditions: interaction modality (conversational, UI only, hybrid), explanation behaviour, embodiment and nonverbals, voice and speech style. Each of these needs a configuration seam. Nothing else does.
- The model stack is fixed across conditions and selected in one place.
- Logs: one append-only JSONL file per session, on disk.
- Transcripts and events only. Raw audio is never written to disk. Participants are identified by pseudonymous ID.

## Milestones

See `PLAN.md`. Milestones live there only, never restated here.

## Environment

- Python 3.14, managed with uv. `uv sync` and `uv run`, never bare pip.
- Windows 11, PowerShell. The Unity client is a separate project.
