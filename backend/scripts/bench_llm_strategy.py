"""Micro-benchmark: parallel-individual vs serial-batch LLM calls.

Runs both strategies on the same N prompts and measures wall time,
so we can pick the globally optimal approach for L1 / L1.5.
"""

import sys, os, time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from narrative_mirror.config import load_config
from narrative_mirror.llm import from_config

cfg = load_config(os.path.join(os.path.dirname(__file__), "..", "config.yml"))
noncot, _, _ = from_config(cfg)

# ── Realistic classify_burst prompt (single burst) ──────────────────────────
SYSTEM = "你是一个对话分析助手，负责识别和分类对话中的话题。"

def single_prompt(idx: int) -> str:
    return f"""分析以下对话片段，识别话题。请返回JSON格式：
{{"topic_name": "主话题名称", "segments": [{{"topic_name": "话题名称", "start_local_id": 起始消息ID, "end_local_id": 结束消息ID}}]}}

对话内容：
[{idx*10+1}] 我: 你最近怎么样？
[{idx*10+2}] TA: 还好，有点忙
[{idx*10+3}] 我: 忙什么呢？
[{idx*10+4}] TA: 在准备期末考试
[{idx*10+5}] 我: 加油！考完我们出去吃饭"""

def batch_prompt(n: int) -> str:
    sections = []
    for idx in range(n):
        lines = [
            f"[{idx*10+1}] 我: 你最近怎么样？",
            f"[{idx*10+2}] TA: 还好，有点忙",
            f"[{idx*10+3}] 我: 忙什么呢？",
            f"[{idx*10+4}] TA: 在准备期末考试",
            f"[{idx*10+5}] 我: 加油！考完我们出去吃饭",
        ]
        sections.append(f"片段{idx}:\n" + "\n".join(lines))
    return f"""分析以下 {n} 个对话片段，分别识别每个片段的话题。
返回JSON格式：{{"bursts": [{{"segments": [{{"topic_name": "话题名称", "start_local_id": 起始消息ID, "end_local_id": 结束消息ID}}]}}]}}
数组长度必须等于 {n}，顺序与输入一致。

{chr(10).join(sections)}"""


def run_parallel(n: int, workers: int = 8) -> float:
    """N concurrent individual calls."""
    start = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(noncot.complete, SYSTEM, single_prompt(i), 256,
                             "json_object") for i in range(n)]
        for f in as_completed(futures):
            f.result()
    return time.time() - start


def run_batch(n: int) -> float:
    """1 serial batch call for N items."""
    start = time.time()
    noncot.complete(SYSTEM, batch_prompt(n), n * 300, "json_object")
    return time.time() - start


SIZES = [4, 8, 16]
REPEATS = 2

print(f"{'N':>4}  {'parallel (8w)':>16}  {'batch (serial)':>16}  {'winner':>8}")
print("-" * 55)

for n in SIZES:
    p_times, b_times = [], []
    for rep in range(REPEATS):
        print(f"  N={n} rep={rep+1}: parallel...", end="", flush=True)
        t = run_parallel(n)
        p_times.append(t)
        print(f" {t:.1f}s  batch...", end="", flush=True)
        t = run_batch(n)
        b_times.append(t)
        print(f" {t:.1f}s")

    p_avg = sum(p_times) / len(p_times)
    b_avg = sum(b_times) / len(b_times)
    winner = "parallel" if p_avg < b_avg else "batch"
    print(f"  N={n}  avg parallel={p_avg:.1f}s  avg batch={b_avg:.1f}s  → {winner}")
    print()
