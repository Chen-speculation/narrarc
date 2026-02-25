export type BuildStatus = 'pending' | 'in_progress' | 'complete';

export interface BuildProgress {
  stage: string;
  step: string;
  detail: string;
  updated_at: string;
}

export interface Session {
  talker_id: string;
  display_name: string;
  last_timestamp: number;
  build_status: BuildStatus;
  message_count: number;
  build_progress?: BuildProgress;
}

export interface Message {
  local_id: number;
  create_time: number;
  is_send: boolean;
  sender_username?: string;
  sender_display: string;
  parsed_content: string;
  phase_index?: number;
}

export interface Phase {
  phase_index: number;
  phase_title: string;
  time_range: string;
  core_conclusion: string;
  evidence: Message[];
  reasoning_chain: string;
  uncertainty_note: string | null;
  verified: boolean;
}

export interface AgentStep {
  node_name: string;
  node_name_display: string;
  input_summary: string;
  output_summary: string;
  llm_calls: number;
  timestamp_ms: number;
}

export interface AgentTrace {
  steps: AgentStep[];
  total_llm_calls: number;
  total_duration_ms: number;
}

/** Backend config (LLM, embedding, reranker) for settings form. */
export interface BackendConfig {
  llm: {
    provider: string;
    model: string;
    api_key: string;
    base_url: string;
    max_workers: number;
  };
  embedding: {
    provider: string;
    model: string;
    api_key: string;
    base_url: string;
  };
  reranker: {
    model: string;
    api_key: string;
    base_url: string;
  };
}

/** Partial overrides applied on top of config.yml. */
export type ConfigOverrides = Partial<BackendConfig>;

export interface QueryResponse {
  conversation_id: string;
  question: string;
  phases: Phase[];
  agent_trace: AgentTrace;
  all_messages: Message[];
}
