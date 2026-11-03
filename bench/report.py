"""Compare the recorded benchmark results model by model, one table per case, only across results whose case, setup and judge hashes match."""

import statistics
from collections import defaultdict
from typing import Any

from bench import record


def _median(values: list[float], digits: int = 2) -> str:
    """Format the median of some measurements, or a dash when there are none."""
    return f"{statistics.median(values):.{digits}f}" if values else "-"


def _label(line: dict[str, Any]) -> str:
    """Name the configured model a result line measured, with a settings hash that tells apart runs of one model with different settings."""
    return f"{line['model']} ({record.digest(line['settings'])[:6]})"


def _table(header: list[str], rows: list[list[str]]) -> str:
    """Lay out a markdown table."""
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return "\n".join(lines + ["| " + " | ".join(row) + " |" for row in rows])


def llm(lines: list[dict[str, Any]]) -> str:
    """Tabulate the LLM results: per model, how often each check passed, the latency to the first spoken word, reply length and tokens."""
    groups: dict[tuple, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for line in lines:
        groups[(line["case"], line["case_hash"], line["setup_hash"], line["judge"], line["judge_hash"])][_label(line)].append(line)

    sections = []
    for (case, case_hash, setup_hash, judge, judge_hash), models in sorted(groups.items()):
        names = list(dict.fromkeys(name for runs in models.values() for run in runs for step in run["steps"] for name in step["checks"]))
        names += list(dict.fromkeys(name for runs in models.values() for run in runs for name in run["checks"]))
        rows = []
        for model, runs in sorted(models.items()):
            good = [run for run in runs if run["error"] is None]
            steps = [step for run in good for step in run["steps"]]
            row = [model, str(len(good)), str(len(runs) - len(good))]
            for name in names:
                verdicts = [step["checks"][name] for step in steps if step["checks"].get(name) is not None]
                verdicts += [run["checks"][name] for run in good if run["checks"].get(name) is not None]
                row.append(f"{sum(verdicts) / len(verdicts):.0%}" if verdicts else "-")
            row.append(_median([step["first_text_s"] for step in steps if step["first_text_s"] is not None]))
            row.append(_median([step["words"] for step in steps], 0))
            row.append(_median([step["prompt_tokens"] + step["completion_tokens"] for step in steps], 0))
            rows.append(row)
        header = ["model (settings)", "runs", "errors", *names, "first word s", "words", "tokens"]
        title = f"### {case}\n\ncase {case_hash}, setup {setup_hash}, judge {judge} {judge_hash}. Checks: share of passes. Medians per reply."
        sections.append(f"{title}\n\n{_table(header, rows)}")
    return "\n\n".join(sections)


def stt(lines: list[dict[str, Any]]) -> str:
    """Tabulate the STT results: per model, the mean word error rate and the median delay from speech end to final transcript."""
    groups: dict[tuple, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for line in lines:
        groups[(line["case"], line["case_hash"])][_label(line)].append(line)

    sections = []
    for (case, case_hash), models in sorted(groups.items()):
        rows = []
        for model, runs in sorted(models.items()):
            good = [run for run in runs if run["error"] is None]
            mean_wer = f"{statistics.mean(run['wer'] for run in good):.1%}" if good else "-"
            latency = _median([value for run in good for value in run["latencies_s"]])
            rows.append([model, str(len(good)), str(len(runs) - len(good)), mean_wer, latency])
        title = f"### {case}\n\ncase {case_hash}. Latency: median seconds from speech end to final transcript."
        sections.append(f"{title}\n\n{_table(['model (settings)', 'runs', 'errors', 'WER', 'latency s'], rows)}")
    return "\n\n".join(sections)


def main():
    """Print both comparisons as markdown."""
    print(f"## LLM\n\n{llm(record.read('llm')) or 'No results yet.'}\n\n## STT\n\n{stt(record.read('stt')) or 'No results yet.'}")


if __name__ == "__main__":
    main()
