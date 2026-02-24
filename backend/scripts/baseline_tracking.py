"""Baseline tracking for retrieval improvement experiments."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_EXPERIMENTS_DIR = Path(__file__).parent.parent / "experiments"
CSV_HEADERS = [
    "experiment_id",
    "date",
    "train_exact_recall",
    "train_fuzzy_recall",
    "train_precision",
    "train_arc_phase_coverage",
    "test_exact_recall",
    "test_fuzzy_recall",
    "test_precision",
    "test_arc_phase_coverage",
    "config_summary",
]


def ensure_experiments_dir(experiments_dir: Path | None = None) -> Path:
    """Create experiments directory and baseline_metrics.csv if needed."""
    d = experiments_dir or DEFAULT_EXPERIMENTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    csv_path = d / "baseline_metrics.csv"
    if not csv_path.exists():
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(CSV_HEADERS)
    return d


def create_experiment_record(
    experiment_id: str,
    metrics: dict[str, float],
    config_snapshot: dict[str, Any],
    config_changes: str = "",
    split: str = "train",
) -> dict:
    """Create an experiment record with train_* or test_* metrics."""
    record = {
        "experiment_id": experiment_id,
        "date": datetime.now().isoformat(),
        "config_changes": config_changes,
        "config_snapshot": config_snapshot,
    }
    prefix = "train_" if split == "train" else "test_"
    for k, v in metrics.items():
        record[prefix + k] = v
    return record


def append_csv_row(experiments_dir: Path, record: dict) -> None:
    """Append a metrics row to baseline_metrics.csv."""
    ensure_experiments_dir(experiments_dir)
    csv_path = experiments_dir / "baseline_metrics.csv"
    def _get(k: str, default: float = 0) -> float:
        v = record.get(k, default)
        return float(v) if v is not None else default
    row = [
        record.get("experiment_id", ""),
        record.get("date", "")[:19] if record.get("date") else "",
        f"{_get('train_exact_recall', _get('exact_recall')):.4f}",
        f"{_get('train_fuzzy_recall', _get('fuzzy_recall')):.4f}",
        f"{_get('train_precision', _get('precision')):.4f}",
        f"{_get('train_arc_phase_coverage', _get('arc_phase_coverage')):.4f}",
        f"{_get('test_exact_recall'):.4f}",
        f"{_get('test_fuzzy_recall'):.4f}",
        f"{_get('test_precision'):.4f}",
        f"{_get('test_arc_phase_coverage'):.4f}",
        str(record.get("config_changes", ""))[:200],
    ]
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(row)


def append_json_record(experiments_dir: Path, record: dict) -> None:
    """Append full experiment record to experiments.jsonl."""
    ensure_experiments_dir(experiments_dir)
    jsonl_path = experiments_dir / "experiments.jsonl"
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_baseline_metrics(experiments_dir: Path | None = None) -> dict | None:
    """Retrieve first experiment metrics as baseline reference."""
    d = experiments_dir or DEFAULT_EXPERIMENTS_DIR
    csv_path = d / "baseline_metrics.csv"
    if not csv_path.exists():
        return None
    with open(csv_path) as f:
        r = csv.DictReader(f)
        for row in r:
            return dict(row)
    return None


def get_best_experiment(experiments_dir: Path | None = None, metric: str = "test_exact_recall") -> dict | None:
    """Identify experiment with highest test_exact_recall."""
    d = experiments_dir or DEFAULT_EXPERIMENTS_DIR
    csv_path = d / "baseline_metrics.csv"
    if not csv_path.exists():
        return None
    best = None
    best_val = -1.0
    with open(csv_path) as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                val = float(row.get(metric, -1))
                if val > best_val:
                    best_val = val
                    best = dict(row)
            except (ValueError, TypeError):
                pass
    return best


def capture_config_snapshot(cfg: Any, raw_config: dict | None = None) -> dict:
    """Capture embedding model, reranker, candidate limits, LLM model from config."""
    snap = {}
    if hasattr(cfg, "llm") and cfg.llm:
        snap["llm_model"] = getattr(cfg.llm, "model", "?")
    if hasattr(cfg, "embedding") and cfg.embedding:
        snap["embedding_model"] = getattr(cfg.embedding, "model", "?")
    if hasattr(cfg, "reranker") and cfg.reranker:
        snap["reranker_model"] = getattr(cfg.reranker, "model", "?")
    if raw_config:
        eval_block = raw_config.get("eval", {})
        query_block = eval_block.get("query", {})
        snap["q3_candidate_limit"] = query_block.get("q3_candidate_limit", "default")
        snap["reranker_threshold"] = query_block.get("reranker_threshold", "default")
    return snap


def main():
    """CLI: show baseline and best experiment."""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", action="store_true", help="Show baseline (first) experiment metrics")
    p.add_argument("--best", action="store_true", help="Show best experiment by test_exact_recall")
    p.add_argument("--experiments-dir", type=Path, help="Experiments directory")
    args = p.parse_args()
    d = args.experiments_dir or DEFAULT_EXPERIMENTS_DIR
    if args.baseline:
        b = get_baseline_metrics(d)
        print("Baseline:", b if b else "No experiments recorded yet")
    if args.best:
        b = get_best_experiment(d)
        print("Best experiment:", b if b else "No experiments recorded yet")


if __name__ == "__main__":
    main()
