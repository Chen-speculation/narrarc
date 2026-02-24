"""Dataset splitting for RealTalk evaluation.

Provides train/test split by conversation file number with 1:1 ARC case mapping.
"""

import json
import re
from pathlib import Path
from typing import Literal

import yaml


def _chat_filename_to_talker_id(filename: str) -> str:
    """Convert Chat_N_Name1_Name2.json to realtalk_name1_name2."""
    # Chat_1_Emi_Elise.json -> realtalk_emi_elise
    stem = Path(filename).stem
    m = re.match(r"Chat_\d+_(.+)", stem, re.IGNORECASE)
    if not m:
        return ""
    names = m.group(1)
    # Emi_Elise -> emi_elise
    return "realtalk_" + names.lower().replace(" ", "_")


def _chat_filename_to_file_number(filename: str) -> int | None:
    """Extract file number from Chat_N_*.json. Returns N or None."""
    stem = Path(filename).stem
    m = re.match(r"Chat_(\d+)_", stem, re.IGNORECASE)
    if not m:
        return None
    return int(m.group(1))


def load_split_config(config_path: str | Path) -> dict:
    """Load eval.realtalk_split from config YAML."""
    path = Path(config_path)
    if not path.exists():
        alt = path.with_suffix(".yaml" if path.suffix == ".yml" else ".yml")
        if alt.exists():
            path = alt
        else:
            raise FileNotFoundError(f"Config not found: {config_path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    eval_block = data.get("eval", {})
    split = eval_block.get("realtalk_split", {})
    return {
        "train_file_range": split.get("train_file_range", [1, 7]),
        "test_file_range": split.get("test_file_range", [8, 10]),
    }


def validate_split_config(config: dict) -> None:
    """Raise ValueError if train and test file ranges overlap."""
    train_lo, train_hi = config["train_file_range"][0], config["train_file_range"][1]
    test_lo, test_hi = config["test_file_range"][0], config["test_file_range"][1]
    train_set = set(range(train_lo, train_hi + 1))
    test_set = set(range(test_lo, test_hi + 1))
    overlap = train_set & test_set
    if overlap:
        raise ValueError(
            f"Train and test sets overlap: file numbers {sorted(overlap)}. "
            f"Train: {train_lo}-{train_hi}, Test: {test_lo}-{test_hi}"
        )


def filter_chat_files(
    data_dir: Path,
    mode: Literal["train", "test", "all"],
    config_path: str | Path | None = None,
    config: dict | None = None,
) -> list[tuple[Path, str]]:
    """Select conversation files based on train/test mode.

    Args:
        data_dir: Directory containing Chat_N_*.json files
        mode: "train", "test", or "all"
        config_path: Path to config.yaml/yml (used if config is None)
        config: Pre-loaded split config (overrides config_path)

    Returns:
        List of (chat_file_path, talker_id) tuples.
    """
    if config is None:
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        config = load_split_config(config_path)
    validate_split_config(config)

    train_lo, train_hi = config["train_file_range"][0], config["train_file_range"][1]
    test_lo, test_hi = config["test_file_range"][0], config["test_file_range"][1]

    if mode == "all":
        allowed = set(range(train_lo, train_hi + 1)) | set(range(test_lo, test_hi + 1))
    elif mode == "train":
        allowed = set(range(train_lo, train_hi + 1))
    else:
        allowed = set(range(test_lo, test_hi + 1))

    result = []
    for p in sorted(data_dir.glob("Chat_*.json")):
        num = _chat_filename_to_file_number(p.name)
        if num is not None and num in allowed:
            talker_id = _chat_filename_to_talker_id(p.name)
            if talker_id:
                result.append((p, talker_id))
    return result


def chat_file_to_arc_file(chat_path: Path, arc_dir: Path) -> Path | None:
    """Return the corresponding ARC case file path for a conversation file.

    1:1 mapping: Chat_N_Name1_Name2.json -> arc_dir/realtalk_name1_name2_arc_cases.json
    """
    talker_id = _chat_filename_to_talker_id(chat_path.name)
    if not talker_id:
        return None
    arc_path = arc_dir / f"{talker_id}_arc_cases.json"
    return arc_path if arc_path.exists() else None


def get_self_id_from_chat(chat_path: Path) -> str:
    """Extract first participant name as self-id (isSend=1) from JSON name.speaker_1."""
    try:
        with open(chat_path) as f:
            data = json.load(f)
        name_block = data.get("name", {})
        return name_block.get("speaker_1", "") or ""
    except Exception:
        pass
    # Fallback: first part of filename (Chat_1_Emi_Elise -> Emi)
    stem = Path(chat_path).stem
    m = re.match(r"Chat_\d+_([^_]+)_(.+)", stem, re.IGNORECASE)
    return m.group(1) if m else ""
