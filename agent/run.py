"""Entrypoint: settle the session, build the transport and services, run the pipeline."""

import asyncio
import subprocess
from pathlib import Path

from loguru import logger
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.transcriptions.language import Language
from pipecat.workers.runner import WorkerRunner

from agent import config, join, livekit_server, pipeline, roster, scenarios, session, world
from agent.config import AUDIO_IN, AUDIO_OUT
from agent.game import Game
from agent.observability import debug_log
from agent.observability.llm_exchange import LLMExchange
from agent.observability.study_log import StudyLog
from agent.observability.timeline import Timeline
from agent.services import catalog


def _commit() -> str | None:
    """Name the code version this session ran, marked dirty when it had uncommitted changes, or None outside a git checkout."""
    try:
        described = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return described.stdout.strip()


async def main():
    """Run the agent until interrupted."""
    # The environment is checked before the dialog opens, so a missing key is not discovered after the operator has chosen.
    cfg = config.load()
    run = session.resolve()

    study_path = roster.session_path(run.participant)
    log_path = debug_log.start(study_path.stem)
    study = StudyLog(study_path)
    # Written to the study log and sent to the client from this one dict, so the two cannot disagree about what the session is.
    settings = {
        "participant": run.participant,
        "session": study_path.stem,
        "language": run.language,
        "scenario": run.scenario,
        "transport": run.transport,
        "vision": run.vision,
        "stt": run.stt,
        "llm": run.llm,
        "tts": run.tts,
        "commit": _commit(),
    }
    study.write("session_start", **settings)

    server = None
    endpoint = None
    try:
        transport = session.TRANSPORTS[run.transport](cfg, run.vision)

        # The server comes up after the dialog, so a cancelled selection never leaves one running.
        server = await livekit_server.ensure(cfg)
        endpoint = await join.serve(cfg)

        logger.info(f"Study log at {study_path}")
        logger.info(f"Debug log at {log_path}")
        logger.info(
            f"Session {study_path.stem}: language={run.language} scenario={run.scenario} stt={run.stt} llm={run.llm} tts={run.tts} vision={run.vision}"
        )
        logger.info(f"Room '{cfg.room}' on {cfg.livekit_url}")
        logger.info(f"Client connection details on port {join.PORT} at {join.PATH}")

        language = Language(run.language)
        scenario = scenarios.SCENARIOS[run.scenario]
        worker = PipelineWorker(
            pipeline.build(
                transport,
                catalog.STT[run.stt](cfg, language),
                catalog.LLM[run.llm](cfg),
                catalog.TTS[run.tts](cfg, language),
                scenario.system_prompt(run.language),
            ),
            params=PipelineParams(
                audio_in_sample_rate=AUDIO_IN,
                audio_out_sample_rate=AUDIO_OUT,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            observers=[Timeline(), LLMExchange(), *study.observers],
            idle_timeout_secs=None,
        )

        game = None
        if scenario.reaction is not None:
            game = Game(scenario.reaction, worker.queue_frames, study)
            worker.add_observer(game)
        greeting = scenario.greeting[run.language] if scenario.greeting else None
        world.attach(worker, greeting, study, settings, game)

        runner = WorkerRunner()
        await runner.add_workers(worker)
        await runner.run()
    finally:
        study.close()
        if endpoint is not None:
            await endpoint.cleanup()
        livekit_server.stop(server)


if __name__ == "__main__":
    asyncio.run(main())
