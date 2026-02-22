import { invoke } from '@tauri-apps/api/core';
import { Command } from '@tauri-apps/plugin-shell';
import type { Session, Message, QueryResponse, AgentStep } from './types';

const DB_PATH = 'data/mirror.db';
const CONFIG_PATH = 'config.yml';

let _backendDir: string | null = null;

function isTauriContext(): boolean {
  return typeof window !== 'undefined' && !!window.__TAURI_INTERNALS__;
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

function cliArgs(subcommand: string, extra: string[] = []): string[] {
  return ['--db', DB_PATH, subcommand, ...extra];
}

async function runCli<T>(args: string[]): Promise<T> {
  const cwd = await getBackendDir();
  const cmd = Command.create(
    'uv',
    ['run', 'python', '-m', 'narrative_mirror.cli_json', ...args],
    { cwd }
  );
  const output = await cmd.execute();
  if (output.code !== 0) {
    throw new Error(`CLI error: ${output.stderr}`);
  }
  return JSON.parse(output.stdout) as T;
}

export interface QueryStreamCallbacks {
  onProgress: (steps: AgentStep[]) => void;
  onComplete: (result: QueryResponse) => void;
  onError: (err: Error) => void;
}

export async function listSessions(): Promise<Session[]> {
  return runCli<Session[]>(cliArgs('list_sessions'));
}

/** Use spawn + stream stdout to avoid pipe buffer deadlock with large payloads (400+ msgs). */
export async function getMessages(talkerId: string, limit?: number, offset?: number): Promise<Message[]> {
  const cwd = await getBackendDir();
  const extra: string[] = [];
  if (limit !== undefined) extra.push('--limit', String(limit));
  if (offset !== undefined && offset > 0) extra.push('--offset', String(offset));
  const args = cliArgs('get_messages', ['--talker', talkerId, ...extra]);
  const cmd = Command.create('uv', ['run', 'python', '-m', 'narrative_mirror.cli_json', ...args], { cwd });
  let stdout = '';
  cmd.stdout.on('data', (chunk: string) => { stdout += chunk; });
  const output = await new Promise<{ code: number; stderr: string }>((resolve, reject) => {
    cmd.on('close', (e) => resolve({ code: e.code ?? -1, stderr: '' }));
    cmd.spawn().catch(reject);
  });
  if (output.code !== 0) throw new Error(`CLI error: ${output.stderr || 'exit ' + output.code}`);
  return JSON.parse(stdout) as Message[];
}

export async function queryNarrative(
  talkerId: string,
  question: string
): Promise<QueryResponse> {
  return runCli<QueryResponse>(
    cliArgs('query', ['--talker', talkerId, '--question', question, '--config', CONFIG_PATH])
  );
}

/** Stream query with real-time progress. Uses spawn + stdout NDJSON. */
export async function queryNarrativeStream(
  talkerId: string,
  question: string,
  callbacks: QueryStreamCallbacks
): Promise<void> {
  const cwd = await getBackendDir();
  const args = cliArgs('query', [
    '--talker', talkerId,
    '--question', question,
    '--config', CONFIG_PATH,
    '--stream',
  ]);
  const cmd = Command.create('uv', ['run', 'python', '-m', 'narrative_mirror.cli_json', ...args], { cwd });

  let buffer = '';
  let resultReceived = false;

  const processLine = (line: string) => {
    if (!line.trim()) return;
    try {
      const obj = JSON.parse(line) as { type?: string; trace_steps?: AgentStep[] };
      if (obj.type === 'progress' && Array.isArray(obj.trace_steps)) {
        callbacks.onProgress(obj.trace_steps);
      } else if (obj.type === 'result') {
        const { type: _, ...rest } = obj;
        resultReceived = true;
        callbacks.onComplete(rest as QueryResponse);
      }
    } catch {
      // ignore parse errors for non-JSON lines
    }
  };

  const onData = (chunk: string) => {
    buffer += chunk;
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) processLine(line);
  };

  cmd.stdout.on('data', onData);

  return new Promise<void>((resolve, reject) => {
    cmd.on('close', (event) => {
      // Flush remaining buffer
      if (buffer.trim()) processLine(buffer);
      if (event.code !== 0 && event.code != null && !resultReceived) {
        callbacks.onError(new Error(`Process exited with code ${event.code}`));
        reject(new Error(`Process exited with code ${event.code}`));
      } else {
        resolve();
      }
    });
    cmd.spawn().catch(reject);
  });
}

export async function importData(filePath: string): Promise<Session> {
  return runCli<Session>(cliArgs('import', ['--file', filePath]));
}

export async function deleteSession(talkerId: string): Promise<void> {
  return runCli<void>(cliArgs('delete_session', ['--talker', talkerId]));
}

export async function triggerBuild(talkerId: string): Promise<void> {
  if (import.meta.env.DEV) {
    // Dev 模式：通过 Rust 侧 spawn，stdout/stderr 继承到 tauri dev 终端，方便排查
    await invoke('spawn_backend_build', { talkerId });
  } else {
    const cwd = await getBackendDir();
    const cmd = Command.create(
      'uv',
      ['run', 'python', '-m', 'narrative_mirror.cli_json', ...cliArgs('build', ['--talker', talkerId, '--config', CONFIG_PATH])],
      { cwd }
    );
    await cmd.spawn();
  }
}
