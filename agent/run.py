"""Entrypoint: build the transport, run the pipeline, print how the client joins."""

import argparse
import asyncio

from loguru import logger
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.workers.runner import WorkerRunner

from agent import config, pipeline
from agent.config import SAMPLE_RATE
from agent.observability.timeline import Timeline
from agent.transports import livekit

TRANSPORTS = {"livekit": livekit.create}


def _parse_args() -> argparse.Namespace:
    """Read the command line: which transport the pipeline runs on."""
    parser = argparse.ArgumentParser(description="Run the AI-Companion agent.")
    parser.add_argument("--transport", choices=sorted(TRANSPORTS), default="livekit")
    return parser.parse_args()


async def main():
    """Run the agent until interrupted."""
    args = _parse_args()
    cfg = config.load()
    transport = TRANSPORTS[args.transport](cfg)

    logger.info(f"Room '{cfg.room}' on {cfg.livekit_url}")
    logger.info(f"Client join token:\n{livekit.client_token(cfg)}")

    worker = PipelineWorker(
        pipeline.build(transport),
        params=PipelineParams(
            audio_in_sample_rate=SAMPLE_RATE,
            audio_out_sample_rate=SAMPLE_RATE,
        ),
        observers=[Timeline()],
        idle_timeout_secs=None,
    )
    await WorkerRunner().run(worker)


if __name__ == "__main__":
    asyncio.run(main())
