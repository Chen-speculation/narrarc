"""JSON CLI API for narrative-mirror client integration.

All subcommands output JSON to stdout. Errors go to stderr with exit code 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from typing import Optional

from .models import RawMessage, Session, Contact
from .db import (
    init_db,
    get_talkers_with_stats,
    get_build_status,
    get_build_progress,
    set_build_progress,
    clear_build_progress,
    get_all_messages,
    get_messages_by_ids,
    upsert_messages,
    delete_session,
)
from .workflow import run_workflow, run_workflow_stream_values

# Stdio daemon mode: when True, _die() prints JSON error and raises StdioModeError instead of exiting
_stdio_mode = False


class StdioModeError(Exception):
    """Raised by _die() in stdio mode so the daemon loop can continue."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


# Node name to display name mapping for AgentTrace steps
NODE_NAME_DISPLAY = {
    "planner": "意图解析",
    "retriever": "检索锚点与节点",
    "grader": "证据评估",
    "explorer": "深度探查",
    "generator": "叙事生成",
    "factual_retriever": "精准检索",
    "factual_generator": "事实回答",
}


def msg_to_client(msg: RawMessage, phase_index: Optional[int] = None) -> dict:
    """Convert RawMessage to client Message format.

    sender_display: "我" when is_send, else sender_username.
    Optionally attach phase_index for evidence messages.
    """
    d = {
        "local_id": msg.local_id,
        "create_time": msg.create_time,
        "is_send": msg.is_send,
        "sender_display": "我" if msg.is_send else msg.sender_username,
        "parsed_content": msg.parsed_content,
    }
    if phase_index is not None:
        d["phase_index"] = phase_index
    return d


def _die(msg: str) -> None:
    """Write error to stderr and exit with code 1. In stdio mode, print JSON to stdout and raise instead."""
    print(msg, file=sys.stderr)
    if _stdio_mode:
        print(json.dumps({"type": "error", "message": msg}, ensure_ascii=False), flush=True)
        raise StdioModeError(msg)
    sys.exit(1)


def _ensure_db(path: str):
    """Ensure db exists and return connection. Die on failure."""
    if not os.path.exists(path):
        _die(f"Database file not found: {path}")
    conn = init_db(path)
    return conn


# ---------------------------------------------------------------------------
# SqliteDataSource for build command (reads from existing SQLite)
# ---------------------------------------------------------------------------


class _SqliteDataSource:
    """ChatDataSource that reads from an existing SQLite connection."""

    def __init__(self, conn, talker_id: str):
        self._conn = conn
        self._talker_id = talker_id

    def list_sessions(self) -> list[Session]:
        stats = get_talkers_with_stats(self._conn)
        return [
            Session(
                username=s["talker_id"],
                display_name=s["display_name"],
                last_timestamp=s["last_timestamp"],
            )
            for s in stats
        ]

    def get_messages(
        self,
        talker_id: str,
        limit: int = 10000,
        offset: int = 0,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
    ) -> list[RawMessage]:
        msgs = get_all_messages(self._conn, talker_id, excluded=False)
        if start_ts is not None:
            msgs = [m for m in msgs if m.create_time >= start_ts]
        if end_ts is not None:
            msgs = [m for m in msgs if m.create_time <= end_ts]
        return msgs[offset : offset + limit]

    def get_contact(self, username: str) -> Optional[Contact]:
        return None


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


def _cmd_list_sessions(args) -> None:
    conn = _ensure_db(args.db)
    try:
        stats = get_talkers_with_stats(conn)
        result = []
        for s in stats:
            status = get_build_status(conn, s["talker_id"])
            row = {
                "talker_id": s["talker_id"],
                "display_name": s["display_name"],
                "last_timestamp": s["last_timestamp"],
                "build_status": status,
                "message_count": s["message_count"],
            }
            if status in ("pending", "in_progress"):
                progress = get_build_progress(conn, s["talker_id"])
                if progress:
                    row["build_progress"] = progress
            result.append(row)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# get_messages
# ---------------------------------------------------------------------------


def _cmd_get_messages(args) -> None:
    conn = _ensure_db(args.db)
    try:
        msgs = get_all_messages(conn, args.talker, excluded=False)
        offset = getattr(args, 'offset', 0) or 0
        limit = getattr(args, 'limit', None)
        if limit is not None:
            msgs = msgs[offset: offset + limit]
        elif offset:
            msgs = msgs[offset:]
        out = [msg_to_client(m) for m in msgs]
        print(json.dumps(out, ensure_ascii=False), flush=True)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


def _build_query_response(trace, talker_id: str, start_ms: int, end_ms: int, conn) -> dict:
    """Convert AgentTrace to client QueryResponse format."""
    total_duration_ms = int(end_ms - start_ms)

    # Build phase_index -> evidence_msg_ids mapping
    phase_evidence_ids: dict[int, set[int]] = {}
    for i, phase in enumerate(trace.phases):
        idx = i + 1
        phase_evidence_ids[idx] = set(phase.evidence_msg_ids)

    # Build msg_id -> phase_index for evidence messages
    msg_to_phase: dict[int, int] = {}
    for phase_idx, ids in phase_evidence_ids.items():
        for lid in ids:
            msg_to_phase[lid] = phase_idx

    # Phases
    phases_out = []
    for i, phase in enumerate(trace.phases):
        phase_idx = i + 1
        evidence_msgs = get_messages_by_ids(conn, talker_id, phase.evidence_msg_ids)
        evidence_out = [
            msg_to_client(m, phase_index=phase_idx) for m in evidence_msgs
        ]
        unc = phase.uncertainty_note
        phases_out.append({
            "phase_index": phase_idx,
            "phase_title": phase.phase_title,
            "time_range": phase.time_range,
            "core_conclusion": phase.core_conclusion,
            "evidence": evidence_out,
            "reasoning_chain": phase.reasoning_chain,
            "uncertainty_note": None if unc == "" else unc,
            "verified": phase.verified,
        })

    # AgentTrace steps with node_name_display and timestamp_ms (real completion time)
    steps = trace.steps
    n = len(steps)
    steps_out = []
    for i, step in enumerate(steps):
        ts_ms = step.timestamp_ms if getattr(step, "timestamp_ms", 0) > 0 else (
            start_ms + int(total_duration_ms * i / n) if n > 0 else start_ms
        )
        node_display = NODE_NAME_DISPLAY.get(step.node_name, step.node_name)
        steps_out.append({
            "node_name": step.node_name,
            "node_name_display": node_display,
            "input_summary": step.input_summary,
            "output_summary": step.output_summary,
            "llm_calls": step.llm_calls,
            "timestamp_ms": ts_ms,
        })

    # all_messages: full list, evidence messages get phase_index
    all_msgs = get_all_messages(conn, talker_id, excluded=False)
    all_out = [
        msg_to_client(m, phase_index=msg_to_phase.get(m.local_id))
        for m in all_msgs
    ]

    # answer_mode and factual_answer
    answer_mode = getattr(trace, "answer_mode", "full_narrative")
    factual_answer_out = None
    if answer_mode == "factual_rag":
        fa = getattr(trace, "factual_answer", None)
        if fa:
            evidence_msgs = get_messages_by_ids(conn, talker_id, fa.get("evidence_msg_ids", []))
            factual_answer_out = {
                "answer": fa.get("answer", ""),
                "evidence": [msg_to_client(m) for m in evidence_msgs],
            }

    return {
        "conversation_id": talker_id,
        "question": trace.question,
        "answer_mode": answer_mode,
        "factual_answer": factual_answer_out,
        "phases": phases_out,
        "agent_trace": {
            "steps": steps_out,
            "total_llm_calls": trace.total_llm_calls,
            "total_duration_ms": total_duration_ms,
        },
        "all_messages": all_out,
    }


def _serialize_trace_steps_for_progress(steps: list, start_ms: int, end_ms: int) -> list[dict]:
    """Serialize trace_steps for streaming progress (NDJSON). Uses real timestamp_ms from steps."""
    total_ms = max(1, end_ms - start_ms)
    n = len(steps)
    out = []
    for i, step in enumerate(steps):
        ts_ms = step.timestamp_ms if getattr(step, "timestamp_ms", 0) > 0 else (
            start_ms + int(total_ms * i / n) if n > 0 else start_ms
        )
        node_display = NODE_NAME_DISPLAY.get(step.node_name, step.node_name)
        out.append({
            "node_name": step.node_name,
            "node_name_display": node_display,
            "input_summary": step.input_summary,
            "output_summary": step.output_summary,
            "llm_calls": step.llm_calls,
            "timestamp_ms": ts_ms,
        })
    return out


def _cmd_query(args) -> None:
    conn = _ensure_db(args.db)
    try:
        from .tools import get_all_tools

        if args.stub:
            from .llm import StubCoTLLM, StubNonCoTLLM
            llm_cot = StubCoTLLM()
            llm_noncot = StubNonCoTLLM()
        else:
            if not args.config:
                _die("--config is required unless --stub is used")
            from .config import load_config
            from .llm import from_config
            config = load_config(args.config)
            llm_noncot, llm_cot, reranker = from_config(config)

        chroma_dir = args.chroma_dir or os.path.join(os.path.dirname(args.db), "chroma")
        tools = get_all_tools(conn, args.talker, chroma_dir, llm_noncot)

        start_ms = int(time.time() * 1000)

        if args.stream:
            # Stream mode: output NDJSON progress lines, then final result
            from .models import AgentTrace, NarrativePhase

            # Emit one initial progress line so the client gets a response immediately and does not
            # block waiting for the first workflow yield (which can be slow due to first LLM call).
            print(json.dumps({"type": "progress", "trace_steps": []}, ensure_ascii=False), flush=True)

            for steps, full_state in run_workflow_stream_values(
                question=args.question,
                talker_id=args.talker,
                llm=llm_cot,
                conn=conn,
                tools=tools,
                llm_noncot=llm_noncot,
                max_iterations=3,
                debug=False,
            ):
                if steps:
                    end_ms = int(time.time() * 1000)
                    steps_out = _serialize_trace_steps_for_progress(steps, start_ms, end_ms)
                    progress = {"type": "progress", "trace_steps": steps_out}
                    print(json.dumps(progress, ensure_ascii=False), flush=True)

            end_ms = int(time.time() * 1000)
            # Build final trace from last full_state
            steps = full_state.get("trace_steps", [])
            phases = full_state.get("phases", [])
            answer_mode = full_state.get("answer_mode", "full_narrative")
            factual_answer = full_state.get("factual_answer")
            # Agentic path: factual_rag gets phases from generator; derive factual_answer for client compat
            if answer_mode == "factual_rag" and factual_answer is None and phases:
                first = phases[0]
                factual_answer = {"answer": first.core_conclusion, "evidence_msg_ids": first.evidence_msg_ids}
            elif answer_mode == "factual_rag" and factual_answer is None:
                factual_answer = {"answer": "未找到相关记录。", "evidence_msg_ids": []}
            total_llm_calls = sum(s.llm_calls for s in steps)
            trace = AgentTrace(
                question=args.question,
                steps=steps,
                final_answer="",
                phases=phases,
                total_llm_calls=total_llm_calls,
                answer_mode=answer_mode,
                factual_answer=factual_answer,
            )
            resp = _build_query_response(trace, args.talker, start_ms, end_ms, conn)
            print(json.dumps({"type": "result", **resp}, ensure_ascii=False), flush=True)
        else:
            trace = run_workflow(
                question=args.question,
                talker_id=args.talker,
                llm=llm_cot,
                conn=conn,
                tools=tools,
                llm_noncot=llm_noncot,
                max_iterations=3,
                debug=False,
                chroma_dir=chroma_dir,
            )
            end_ms = int(time.time() * 1000)
            resp = _build_query_response(trace, args.talker, start_ms, end_ms, conn)
            print(json.dumps(resp, ensure_ascii=False), flush=True)
    except Exception as e:
        _die(f"query failed: {e}")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def parse_import_json(content: str) -> tuple[str, str, list[RawMessage]]:
    """Parse single-file import JSON.

    Supports multiple formats:
    - Flat: top-level display_name, talker_id, messages (e.g. realtalk export)
    - WeFlow: weflow + session (displayName) + messages

    Returns (display_name, talker_id, messages).
    - createTime: if < 10^10 treat as seconds, multiply by 1000
    - localType 10000/10002 -> excluded=True
    - Missing talker_id: generate via md5(display_name + str(messages[0].createTime))[:12]
    """
    data = json.loads(content)
    messages_data = data.get("messages")
    if messages_data is None:
        raise ValueError("Missing required field: messages")

    # Resolve display_name: flat "display_name" or WeFlow "session.displayName" / "session.display_name"
    display_name = data.get("display_name")
    if not display_name and data.get("session"):
        session = data["session"]
        display_name = session.get("displayName") or session.get("display_name") or session.get("remark") or session.get("nickname")
    if not display_name:
        raise ValueError("Missing required field: display_name (or session.displayName in WeFlow format)")

    talker_id = data.get("talker_id")
    if not talker_id and data.get("session"):
        talker_id = data["session"].get("wxid") or data["session"].get("talker_id")
    if not talker_id and messages_data:
        first_ts = messages_data[0].get("createTime", 0)
        raw = f"{display_name}{first_ts}"
        talker_id = hashlib.md5(raw.encode()).hexdigest()[:12]
    elif not talker_id:
        talker_id = hashlib.md5(display_name.encode()).hexdigest()[:12]

    messages = []
    for item in messages_data:
        ct = item.get("createTime", 0)
        if ct < 10**10:
            ct *= 1000
        local_type = item.get("localType", 1)
        excluded = local_type in (10000, 10002)
        # parsedContent (realtalk) or content (WeFlow)
        parsed_content = item.get("parsedContent") or item.get("content") or ""
        messages.append(RawMessage(
            local_id=item.get("localId", 0),
            talker_id=talker_id,
            create_time=ct,
            is_send=item.get("isSend", 0) == 1,
            sender_username=item.get("senderUsername", ""),
            parsed_content=parsed_content,
            local_type=local_type,
            excluded=excluded,
        ))

    return (display_name, talker_id, messages)


def _cmd_import(args) -> None:
    with open(args.file, "r", encoding="utf-8") as f:
        content = f.read()
    try:
        display_name, talker_id, messages = parse_import_json(content)
    except (json.JSONDecodeError, ValueError) as e:
        _die(f"Invalid import JSON: {e}")

    db_dir = os.path.dirname(args.db)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = init_db(args.db)
    try:
        upsert_messages(conn, messages)
        count = len(messages)
        status = get_build_status(conn, talker_id)
        out = {
            "talker_id": talker_id,
            "message_count": count,
            "build_status": status,
        }
        print(json.dumps(out, ensure_ascii=False), flush=True)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# delete_session
# ---------------------------------------------------------------------------


def _cmd_delete_session(args) -> None:
    conn = _ensure_db(args.db)
    try:
        stats = get_talkers_with_stats(conn)
        if not any(s["talker_id"] == args.talker for s in stats):
            _die(f"Session not found: {args.talker}")
        delete_session(conn, args.talker)
        chroma_dir = args.chroma_dir or os.path.join(os.path.dirname(args.db), "chroma")
        chroma_path = os.path.join(chroma_dir, "chroma")
        if os.path.isdir(chroma_path):
            try:
                import chromadb
                client = chromadb.PersistentClient(path=chroma_path)
                safe_name = f"narrative_mirror_{args.talker}".replace("-", "_")
                try:
                    client.delete_collection(name=safe_name)
                except Exception:
                    pass
            except Exception:
                pass
        out = {"status": "deleted", "talker_id": args.talker}
        print(json.dumps(out, ensure_ascii=False), flush=True)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def _cmd_build(args) -> None:
    conn = _ensure_db(args.db)
    try:
        from .config import load_config
        from .llm import from_config
        from .build import build_layer1
        from .metadata import build_layer15
        from .layer2 import build_layer2

        talker_id = args.talker
        debug = getattr(args, "debug", False)

        def on_progress(stage: str, step: str, detail: str) -> None:
            set_build_progress(conn, talker_id, stage, step, detail)

        config = load_config(args.config)
        llm_noncot, llm_cot, reranker = from_config(config)
        source = _SqliteDataSource(conn, talker_id)

        try:
            set_build_progress(conn, talker_id, "layer1", "start", "开始构建 Layer 1：消息聚合与话题分类")
            build_layer1(
                talker_id=talker_id,
                source=source,
                llm=llm_noncot,
                conn=conn,
                gap_seconds=1800,
                debug=debug,
                progress_callback=on_progress,
            )
        except Exception as e:
            print("build_layer1", file=sys.stderr)
            _die(str(e))

        try:
            set_build_progress(conn, talker_id, "layer1.5", "metadata", "计算元数据与异常锚点")
            build_layer15(
                talker_id=talker_id,
                llm=llm_noncot,
                conn=conn,
                debug=debug,
            )
        except Exception as e:
            print("metadata", file=sys.stderr)
            _die(str(e))

        chroma_dir = args.chroma_dir or os.path.join(os.path.dirname(args.db), "chroma")
        try:
            set_build_progress(conn, talker_id, "layer2", "start", "开始构建 Layer 2：语义链路")
            build_layer2(
                talker_id=talker_id,
                llm_noncot=llm_noncot,
                reranker=reranker,
                llm_cot=llm_cot,
                conn=conn,
                data_dir=chroma_dir,
                debug=debug,
                progress_callback=on_progress,
            )
        except Exception as e:
            print("layer2", file=sys.stderr)
            _die(str(e))

        clear_build_progress(conn, talker_id)
        out = {"status": "complete", "talker_id": talker_id}
        print(json.dumps(out, ensure_ascii=False), flush=True)
    except Exception as e:
        _die(str(e))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# stdio daemon (one process per client lifecycle)
# ---------------------------------------------------------------------------


class _Namespace:
    """Minimal namespace for dispatching to _cmd_* without argparse."""

    def __init__(self, d: dict) -> None:
        self.__dict__.update(d)


def _cmd_stdio(args) -> None:
    """Read JSON lines from stdin, dispatch to existing _cmd_* by cmd, write responses to stdout."""
    global _stdio_mode
    _stdio_mode = True
    default_db = args.db
    default_config = getattr(args, "config", None) or "config.yml"

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps({"type": "error", "message": f"Invalid JSON: {e}"}, ensure_ascii=False), flush=True)
            continue

        cmd = data.get("cmd")
        if not cmd:
            print(json.dumps({"type": "error", "message": "Missing 'cmd' field"}, ensure_ascii=False), flush=True)
            continue

        # Build namespace with defaults; payload keys match CLI option names (e.g. talker, limit, offset)
        base = {"db": default_db}
        if cmd == "list_sessions":
            ns = _Namespace(base)
            func = _cmd_list_sessions
        elif cmd == "get_messages":
            ns = _Namespace({
                **base,
                "talker": data.get("talker"),
                "limit": data.get("limit"),
                "offset": data.get("offset", 0),
            })
            func = _cmd_get_messages
        elif cmd == "query":
            ns = _Namespace({
                **base,
                "talker": data.get("talker"),
                "question": data.get("question"),
                "config": data.get("config") or default_config,
                "chroma_dir": data.get("chroma_dir"),
                "stub": data.get("stub", False),
                "stream": data.get("stream", False),
            })
            func = _cmd_query
        elif cmd == "import":
            ns = _Namespace({**base, "file": data.get("file")})
            func = _cmd_import
        elif cmd == "delete_session":
            ns = _Namespace({
                **base,
                "talker": data.get("talker"),
                "chroma_dir": data.get("chroma_dir"),
            })
            func = _cmd_delete_session
        else:
            print(json.dumps({"type": "error", "message": f"Unknown cmd: {cmd}"}, ensure_ascii=False), flush=True)
            continue

        try:
            func(ns)
        except StdioModeError:
            pass
        except Exception as e:
            print(json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    # Force UTF-8 for stdout/stderr on Windows so Chinese (topic_name etc.) renders correctly
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Narrative Mirror JSON CLI")
    parser.add_argument("--db", default="data/mirror.db", help="SQLite database path")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # list_sessions
    p_list = subparsers.add_parser("list_sessions")
    p_list.set_defaults(func=_cmd_list_sessions)

    # get_messages
    p_get = subparsers.add_parser("get_messages")
    p_get.add_argument("--talker", required=True, help="Talker ID")
    p_get.add_argument("--limit", type=int, default=None, help="Max messages to return")
    p_get.add_argument("--offset", type=int, default=0, help="Skip first N messages")
    p_get.set_defaults(func=_cmd_get_messages)

    # query
    p_query = subparsers.add_parser("query")
    p_query.add_argument("--talker", required=True, help="Talker ID")
    p_query.add_argument("--question", required=True, help="User question")
    p_query.add_argument("--config", default=None, help="Path to config.yml (omit with --stub)")
    p_query.add_argument("--chroma-dir", dest="chroma_dir", default=None, help="ChromaDB directory")
    p_query.add_argument("--stub", action="store_true", help="Use stub LLM for testing")
    p_query.add_argument("--stream", action="store_true", help="Stream progress as NDJSON to stdout")
    p_query.set_defaults(func=_cmd_query)

    # import
    p_import = subparsers.add_parser("import")
    p_import.add_argument("--file", required=True, help="Path to import JSON file")
    p_import.set_defaults(func=_cmd_import)

    # delete_session
    p_del = subparsers.add_parser("delete_session")
    p_del.add_argument("--talker", required=True, help="Talker ID to delete")
    p_del.add_argument("--chroma-dir", dest="chroma_dir", default=None, help="ChromaDB directory (optional)")
    p_del.set_defaults(func=_cmd_delete_session)

    # build
    p_build = subparsers.add_parser("build")
    p_build.add_argument("--talker", required=True, help="Talker ID")
    p_build.add_argument("--config", required=True, help="Path to config.yml")
    p_build.add_argument("--chroma-dir", dest="chroma_dir", default=None, help="ChromaDB directory (optional)")
    p_build.add_argument("--debug", action="store_true", help="Print progress logs to stderr")
    p_build.set_defaults(func=_cmd_build)

    # stdio daemon (one process per client; requests as JSON lines on stdin)
    p_stdio = subparsers.add_parser("stdio")
    p_stdio.add_argument("--config", default="config.yml", help="Default config path for query")
    p_stdio.set_defaults(func=_cmd_stdio)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as e:
        _die(str(e))


if __name__ == "__main__":
    main()
