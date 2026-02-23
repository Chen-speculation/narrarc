"""Core data models for Narrative Mirror."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import uuid


@dataclass
class RawMessage:
    """A raw message from the chat data source."""

    local_id: int
    talker_id: str
    create_time: int  # Unix timestamp in milliseconds
    is_send: bool  # True if sent by the user (isSend=1)
    sender_username: str
    parsed_content: str
    local_type: int
    excluded: bool = False  # True for system messages (local_type 10000/10002)


@dataclass
class Session:
    """A chat session (conversation)."""

    username: str  # talker_id
    display_name: str
    last_timestamp: int  # Unix timestamp in milliseconds


@dataclass
class Contact:
    """A contact in the chat."""

    username: str
    display_name: str


@dataclass
class Burst:
    """A burst of messages grouped by time proximity."""

    burst_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    talker_id: str = ""
    messages: list[RawMessage] = field(default_factory=list)
    start_time: int = 0  # Unix timestamp in milliseconds
    end_time: int = 0  # Unix timestamp in milliseconds

    def __post_init__(self):
        if self.messages:
            self.start_time = self.messages[0].create_time
            self.end_time = self.messages[-1].create_time


@dataclass
class TopicNode:
    """A topic node in Layer 1, representing a conversation segment."""

    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    talker_id: str = ""
    burst_id: str = ""
    topic_name: str = ""
    start_local_id: int = 0
    end_local_id: int = 0
    start_time: int = 0  # Unix timestamp in milliseconds
    end_time: int = 0  # Unix timestamp in milliseconds
    parent_node_id: Optional[str] = None


@dataclass
class MetadataSignals:
    """Layer 1.5 metadata signals for a TopicNode."""

    node_id: str = ""
    talker_id: str = ""
    reply_delay_avg_s: float = 0.0
    reply_delay_max_s: float = 0.0
    term_shift_score: float = 0.0
    silence_event: bool = False
    topic_frequency: int = 0
    initiator_ratio: float = 0.0
    emotional_tone: float = 0.0  # -1.0 to 1.0
    conflict_intensity: float = 0.0  # 0.0 to 1.0


@dataclass
class AnomalyAnchor:
    """An anomaly anchor pointing to an unusual signal in a TopicNode."""

    anchor_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    talker_id: str = ""
    node_id: str = ""
    signal_name: str = ""
    signal_value: float = 0.0
    baseline_mean: float = 0.0
    baseline_std: float = 0.0
    event_date: str = ""  # ISO date string (YYYY-MM-DD)


@dataclass
class QueryIntent:
    """Parsed query intent from user's question."""

    query_type: str  # "arc_narrative", "time_point", "event_retrieval", "phase_query"
    focus_dimensions: list[str] = field(default_factory=list)
    time_range: Optional[str] = None  # e.g., "2023-06"
    scope: Optional[dict] = None  # {type, time_hint, topic_hint}
    output_mode: str = "narrative"  # "narrative" | "fact" | "summary"


@dataclass
class NarrativePhase:
    """A phase in the narrative segmentation."""

    phase_title: str = ""
    time_range: str = ""
    core_conclusion: str = ""
    evidence_msg_ids: list[int] = field(default_factory=list)
    evidence_segments: list[tuple[int, int]] = field(default_factory=list)  # [(start_id, end_id), ...] inclusive
    reasoning_chain: str = ""
    uncertainty_note: str = ""
    verified: bool = False


@dataclass
class AgentStep:
    """A single step in the agent workflow execution trace."""

    node_name: str  # e.g., "planner", "retriever", "grader", "explorer", "generator"
    input_summary: str  # summary of state when node started
    output_summary: str  # summary of what the node produced
    llm_calls: int = 0  # number of LLM calls in this step
    timestamp_ms: int = 0  # wall-clock ms when step completed (real completion time)


@dataclass
class AgentTrace:
    """Full execution trace for an agent workflow run."""

    question: str
    steps: list[AgentStep] = field(default_factory=list)
    final_answer: str = ""
    phases: list[NarrativePhase] = field(default_factory=list)
    total_llm_calls: int = 0
    answer_mode: str = "full_narrative"  # "full_narrative" or "factual_rag"
    factual_answer: Optional[dict] = None  # {"answer": str, "evidence_msg_ids": list[int]}
