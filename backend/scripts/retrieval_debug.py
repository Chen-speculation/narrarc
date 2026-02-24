"""Retrieval debugging: checkpoint logging and ground truth tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckpointLog:
    """Structured debug log for one retrieval checkpoint."""
    checkpoint_name: str
    candidate_ids: list[int]
    ground_truth_ids: list[int]
    ground_truth_present: list[int]  # subset of ground_truth_ids that appear in candidates
    scores: list[float] | None = None
    candidate_count: int = 0


def nodes_to_local_ids(nodes: list) -> list[int]:
    """Extract all local_ids from nodes (start_local_id to end_local_id inclusive)."""
    ids = []
    for n in nodes:
        for lid in range(n.start_local_id, n.end_local_id + 1):
            ids.append(lid)
    return list(set(ids))


def check_ground_truth_presence(candidate_ids: list[int], ground_truth_ids: list[int]) -> list[int]:
    """Return ground truth IDs that appear in candidates."""
    cand_set = set(candidate_ids)
    return [g for g in ground_truth_ids if g in cand_set]


def identify_failure_point(checkpoints: list[CheckpointLog]) -> str | None:
    """Identify which checkpoint lost ground truth evidence. Returns checkpoint name or None."""
    if not checkpoints or not checkpoints[0].ground_truth_ids:
        return None
    prev_present = set(checkpoints[0].ground_truth_ids)
    for cp in checkpoints[1:]:
        curr_present = set(cp.ground_truth_present)
        lost = prev_present - curr_present
        if lost:
            return f"{cp.checkpoint_name}: lost {lost}"
        prev_present = curr_present
    return None


def log_checkpoint(
    checkpoint_name: str,
    candidate_ids: list[int],
    ground_truth_ids: list[int],
    scores: list[float] | None = None,
    verbosity: str = "minimal",
) -> CheckpointLog:
    """Create checkpoint log with ground truth tracking."""
    present = check_ground_truth_presence(candidate_ids, ground_truth_ids)
    log = CheckpointLog(
        checkpoint_name=checkpoint_name,
        candidate_ids=candidate_ids if verbosity == "full" else [],
        ground_truth_ids=ground_truth_ids,
        ground_truth_present=present,
        scores=scores,
        candidate_count=len(candidate_ids),
    )
    return log


def checkpoint_to_dict(log: CheckpointLog, verbosity: str = "minimal") -> dict:
    """Serialize checkpoint for JSON output."""
    d = {
        "checkpoint_name": log.checkpoint_name,
        "candidate_count": log.candidate_count,
        "ground_truth_ids": log.ground_truth_ids,
        "ground_truth_present": log.ground_truth_present,
        "ground_truth_missing": [g for g in log.ground_truth_ids if g not in log.ground_truth_present],
    }
    if verbosity == "full":
        d["candidate_ids"] = log.candidate_ids
        d["scores"] = log.scores
    return d


def aggregate_failure_patterns(all_checkpoints: list[list[CheckpointLog]]) -> dict:
    """Aggregate debug logs across cases to identify common failure patterns."""
    failure_at: dict[str, int] = {}
    for case_cps in all_checkpoints:
        fp = identify_failure_point(case_cps)
        if fp:
            # Extract checkpoint name (before ":")
            ckpt = fp.split(":")[0] if ":" in fp else fp
            failure_at[ckpt] = failure_at.get(ckpt, 0) + 1
    return {"failure_at_checkpoint": failure_at}
