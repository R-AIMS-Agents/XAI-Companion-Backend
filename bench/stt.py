"""STT benchmark: plays the recordings in bench/cases/stt in real time into a catalog STT, behind the same Silero VAD a session uses, and records the transcript, its word error rate and the delay from speech end to final transcript."""

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
import wave
from functools import partial
from pathlib import Path
from typing import Any

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import ErrorFrame, InputAudioRawFrame, MetricsFrame, TranscriptionFrame
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.services.stt_service import STTService
from pipecat.transcriptions.language import Language
from pipecat.workers.runner import WorkerRunner

from agent import config, nemotron_server
from agent.config import AUDIO_IN
from agent.services import catalog
from bench import record

ROOT = Path(__file__).resolve().parent.parent
CASES = Path(__file__).resolve().parent / "cases" / "stt"

# Audio is sent in chunks of this length, at the pace it was spoken.
CHUNK_S = 0.02

# Silence after the recording, so the VAD sees the speech end and the STT finalises.
TAIL_S = 2.0

# How long after the last final transcript the run waits for another before it ends.
SETTLE_S = 3.0

WORD = re.compile(r"[\w']+")


def words(text: str) -> list[str]:
    """Split a transcript into lowercased words without punctuation, with hyphenated compounds as separate words, so formatting is not counted as an error."""
    return WORD.findall(text.lower().replace("-", " "))


def wer(reference: str, hypothesis: str) -> float:
    """Return the word error rate: substitutions, deletions and insertions needed to turn the hypothesis into the reference, per reference word."""
    ref, hyp = words(reference), words(hypothesis)
    row = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        previous, row[0] = row[0], i
        for j, hyp_word in enumerate(hyp, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ref_word != hyp_word))
    return round(row[-1] / max(len(ref), 1), 4)


class Listener(BaseObserver):
    """Gathers the STT's final transcripts and its speech-end-to-transcript latencies, and any error from the pipeline."""

    def __init__(self, stt: STTService):
        """Watch the frames one STT service pushes."""
        super().__init__(observe_every_push=False)
        self._stt = stt
        self.finals: list[str] = []
        self.latencies_s: list[float] = []
        self.last_final = time.perf_counter()
        self.error: str | None = None

    async def on_push_frame(self, data: FramePushed):
        """Record a final transcript, an STT latency metric or an error."""
        frame = data.frame
        if isinstance(frame, ErrorFrame):
            self.error = frame.error
        elif data.source is not self._stt:
            return
        elif isinstance(frame, TranscriptionFrame):
            self.finals.append(frame.text)
            self.last_final = time.perf_counter()
        elif isinstance(frame, MetricsFrame):
            self.latencies_s += [round(m.value, 3) for m in frame.data if isinstance(m, TTFBMetricsData)]


async def run_case(stt: STTService, case: dict[str, Any]) -> dict[str, Any]:
    """Play one recording through the STT once and return its transcript, word error rate and latencies."""
    with wave.open(str(ROOT / case["audio"])) as recording:
        if (recording.getframerate(), recording.getnchannels(), recording.getsampwidth()) != (AUDIO_IN, 1, 2):
            sys.exit(f"{case['audio']} must be 16-bit mono at {AUDIO_IN} Hz")
        audio = recording.readframes(recording.getnframes())
    audio += bytes(int(TAIL_S * AUDIO_IN) * 2)
    chunk = int(CHUNK_S * AUDIO_IN) * 2

    listener = Listener(stt)
    worker = PipelineWorker(
        Pipeline([VADProcessor(vad_analyzer=SileroVADAnalyzer()), stt]),
        params=PipelineParams(audio_in_sample_rate=AUDIO_IN, enable_metrics=True),
        observers=[listener],
        idle_timeout_secs=None,
    )
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    running = asyncio.create_task(runner.run())

    start = time.perf_counter()
    for index, offset in enumerate(range(0, len(audio), chunk)):
        await worker.queue_frame(InputAudioRawFrame(audio=audio[offset : offset + chunk], sample_rate=AUDIO_IN, num_channels=1))
        await asyncio.sleep(max(0.0, start + (index + 1) * CHUNK_S - time.perf_counter()))
    while listener.error is None and time.perf_counter() - listener.last_final < SETTLE_S:
        await asyncio.sleep(0.1)
    await worker.stop_when_done()
    await running

    transcript = " ".join(text.strip() for text in listener.finals)
    return {
        "transcript": transcript,
        "wer": wer(case["reference"], transcript),
        "latencies_s": listener.latencies_s,
        "median_latency_s": statistics.median(listener.latencies_s) if listener.latencies_s else None,
        "error": listener.error,
    }


def build(name: str, model: str | None, cfg: config.Config, language: Language) -> STTService:
    """Build a catalog STT, with its snapshot replaced when a model is named, so models the catalog no longer lists can still be measured."""
    factory = catalog.STT[name]
    if model is None:
        return factory(cfg, language)
    if not (isinstance(factory, partial) and "model" in factory.keywords):
        sys.exit(f"'{name}' is not bound to a model, so --model cannot replace it.")
    return factory(cfg, language, model=model)


def load(names: list[str] | None) -> dict[str, dict[str, Any]]:
    """Read the named cases, or every case, by the file name they are known by."""
    cases = {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(CASES.glob("*.json"))}
    if names:
        unknown = set(names) - cases.keys()
        if unknown:
            sys.exit(f"Unknown cases: {', '.join(sorted(unknown))}")
        cases = {name: cases[name] for name in names}
    return cases


async def main():
    """Run the chosen cases until each has the requested number of error-free repetitions for this model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stt", required=True, choices=sorted(catalog.STT), help="catalog entry to measure")
    parser.add_argument("--model", help="snapshot to measure in place of the entry's own, such as an older one")
    parser.add_argument("--case", nargs="*", help="cases to run, by file name; default: all")
    parser.add_argument("--reps", type=int, default=3, help="error-free repetitions each case should have (default: 3)")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    cfg = config.load()
    if args.stt == nemotron_server.STT:
        await nemotron_server.ensure()
    done = record.read("stt")

    for name, case in load(args.case).items():
        language = Language(case["language"])
        candidate = build(args.stt, args.model, cfg, language)
        model = candidate.settings.model
        key = {"model": model, "settings": record.settings(candidate), "case": name, "case_hash": record.digest(case)}
        have = sum(1 for line in done if line["error"] is None and all(line[k] == v for k, v in key.items()))
        for rep in range(have, args.reps):
            result = await run_case(build(args.stt, args.model, cfg, language), case)
            record.append("stt", {"stt": args.stt, **key, "rep": rep, **result})
            status = result["error"] or f"WER {result['wer']:.1%}, median latency {result['median_latency_s']}s"
            print(f"{model} {name} rep {rep + 1}/{args.reps}: {status}")
        if have >= args.reps:
            print(f"{model} {name}: {have} repetitions already recorded")


if __name__ == "__main__":
    asyncio.run(main())
