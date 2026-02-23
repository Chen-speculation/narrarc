import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';
import { Command } from '@tauri-apps/plugin-shell';
import type { Session, Message, QueryResponse, AgentStep } from './types';

const CONFIG_PATH = 'config.yml';

let _backendDir: string | null = null;

function isTauriContext(): boolean {
  return typeof window !== 'undefined' && !!(window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
}

async function getBackendDir(): Promise<string> {
  if (_backendDir) return _backendDir;
  if (!isTauriContext()) {
    throw new Error(
      'Tauri API 不可用。请通过 npm run tauri:dev 或运行构建后的应用启动，不要直接在浏览器中打开 localhost。'
    );
  }
  _backendDir = await invoke<string>('get_backend_dir');
  return _backendDir;
}

/** Single request to the long-lived backend process (stdio daemon). */
async function backendRequest<T>(payload: Record<string, unknown>): Promise<T> {
  if (!isTauriContext()) {
    throw new Error(
      'Tauri API 不可用。请通过 npm run tauri:dev 或运行构建后的应用启动。'
    );
  }
  const result = await invoke<unknown>('backend_request', { payload });
  return result as T;
}

export interface QueryStreamCallbacks {
  onProgress: (steps: AgentStep[]) => void;
  onComplete: (result: QueryResponse) => void;
  onError: (err: Error) => void;
}

export async function listSessions(): Promise<Session[]> {
  return backendRequest<Session[]>({ cmd: 'list_sessions' });
}

export async function getMessages(
  talkerId: string,
  limit?: number,
  offset?: number
): Promise<Message[]> {
  const payload: Record<string, unknown> = {
    cmd: 'get_messages',
    talker: talkerId,
    offset: offset ?? 0,
  };
  if (limit !== undefined) payload.limit = limit;
  return backendRequest<Message[]>(payload);
}

export async function queryNarrative(
  talkerId: string,
  question: string
): Promise<QueryResponse> {
  return backendRequest<QueryResponse>({
    cmd: 'query',
    talker: talkerId,
    question,
    config: CONFIG_PATH,
    stream: false,
  });
}

/** Stream query via backend_query_stream; progress via backend://progress event. */
export async function queryNarrativeStream(
  talkerId: string,
  question: string,
  callbacks: QueryStreamCallbacks
): Promise<void> {
  if (!isTauriContext()) {
    callbacks.onError(new Error('Tauri API 不可用'));
    return;
  }
  const unlisten = await listen<{ trace_steps?: AgentStep[] }>(
    'backend://progress',
    (event) => {
      if (Array.isArray(event.payload?.trace_steps)) {
        callbacks.onProgress(event.payload.trace_steps);
      }
    }
  );
  try {
    const result = await invoke<Record<string, unknown>>('backend_query_stream', {
      talker: talkerId,
      question,
    });
    const { type: _, ...rest } = result as { type?: string; [k: string]: unknown };
    callbacks.onComplete(rest as unknown as QueryResponse);
  } catch (err) {
    callbacks.onError(err instanceof Error ? err : new Error(String(err)));
  } finally {
    unlisten();
  }
}

export async function importData(filePath: string): Promise<Session> {
  const out = await backendRequest<{
    talker_id: string;
    message_count: number;
    build_status: string;
  }>({ cmd: 'import', file: filePath });
  return {
    talker_id: out.talker_id,
    display_name: out.talker_id,
    last_timestamp: 0,
    build_status: out.build_status as Session['build_status'],
    message_count: out.message_count,
  };
}

export async function deleteSession(talkerId: string): Promise<void> {
  await backendRequest<unknown>({ cmd: 'delete_session', talker: talkerId });
}

export async function triggerBuild(talkerId: string): Promise<void> {
  if (import.meta.env?.DEV) {
    await invoke('spawn_backend_build', { talkerId });
  } else {
    const cwd = await getBackendDir();
    const cmd = Command.create(
      'uv',
      [
        'run',
        'python',
        '-m',
        'narrative_mirror.cli_json',
        '--db',
        'data/mirror.db',
        'build',
        '--talker',
        talkerId,
        '--config',
        CONFIG_PATH,
      ],
      { cwd }
    );
    await cmd.spawn();
  }
}
