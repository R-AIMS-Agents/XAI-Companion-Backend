"""Entrypoint: settle the session, build the transport and services, run the pipeline."""

import asyncio

from loguru import logger
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.workers.runner import WorkerRunner

from agent import config, pipeline, session
from agent.config import AUDIO_IN, AUDIO_OUT
from agent.observability.timeline import Timeline
from agent.services import catalog
from agent.transports import livekit


async def main():
    """Run the agent until interrupted."""
    # The environment is checked before the dialog opens, so a missing key is not discovered after the operator has chosen.
    cfg = config.load()
    run = session.resolve()
    transport = session.TRANSPORTS[run.transport](cfg)

    logger.info(f"Session: stt={run.stt} llm={run.llm} tts={run.tts}")
    logger.info(f"Room '{cfg.room}' on {cfg.livekit_url}")
    logger.info(f"Client join token:\n{livekit.client_token(cfg)}")

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

    runner = WorkerRunner()
    await runner.add_workers(worker)
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
