"""Entrypoint: settle the session, build the transport and services, run the pipeline."""

import asyncio

from loguru import logger
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.workers.runner import WorkerRunner

from agent import config, join, livekit_server, pipeline, session, world
from agent.config import AUDIO_IN, AUDIO_OUT
from agent.observability import debug_log
from agent.observability.timeline import Timeline
from agent.services import catalog


async def main():
    """Run the agent until interrupted."""
    log_path = debug_log.start()
    # The environment is checked before the dialog opens, so a missing key is not discovered after the operator has chosen.
    cfg = config.load()
    run = session.resolve()
    transport = session.TRANSPORTS[run.transport](cfg, run.vision)

    # The server comes up after the dialog, so a cancelled selection never leaves one running.
    server = await livekit_server.ensure(cfg)
    endpoint = await join.serve(cfg)

    logger.info(f"Debug log at {log_path}")
    logger.info(f"Session: stt={run.stt} llm={run.llm} tts={run.tts} vision={run.vision}")
    logger.info(f"Room '{cfg.room}' on {cfg.livekit_url}")
    logger.info(f"Client connection details on port {join.PORT} at {join.PATH}")

    worker = PipelineWorker(
        pipeline.build(
            transport,
            catalog.STT[run.stt](cfg),
            catalog.LLM[run.llm](cfg),
            catalog.TTS[run.tts](cfg),
        ),
        params=PipelineParams(
            audio_in_sample_rate=AUDIO_IN,
            audio_out_sample_rate=AUDIO_OUT,
        ),
        observers=[Timeline()],
        idle_timeout_secs=None,
    )

    world.attach(worker)

    runner = WorkerRunner()
    await runner.add_workers(worker)
    try:
        await runner.run()
    finally:
        await endpoint.cleanup()
        livekit_server.stop(server)


if __name__ == "__main__":
    asyncio.run(main())
