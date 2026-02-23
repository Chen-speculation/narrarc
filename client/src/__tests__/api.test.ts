import { jest } from '@jest/globals';

const mockInvoke = jest.fn();
const mockListen = jest.fn();
const mockCreate = jest.fn();

jest.unstable_mockModule('@tauri-apps/api/core', () => ({
  invoke: mockInvoke,
}));

jest.unstable_mockModule('@tauri-apps/api/event', () => ({
  listen: mockListen,
}));

jest.unstable_mockModule('@tauri-apps/plugin-shell', () => ({
  Command: { create: mockCreate },
}));

const api = await import('../api');

beforeEach(() => {
  mockInvoke.mockClear();
  mockListen.mockClear();
  mockCreate.mockClear();
  if (typeof globalThis.window === 'undefined') {
    (globalThis as unknown as { window: { __TAURI_INTERNALS__?: unknown } }).window = { __TAURI_INTERNALS__: {} };
  } else {
    (globalThis.window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
  }
  mockInvoke.mockImplementation((cmd: string, args?: { payload?: unknown; talkerId?: string; talker?: string; question?: string }) => {
    if (cmd === 'get_backend_dir') return Promise.resolve('/fake/backend');
    if (cmd === 'backend_request' && args?.payload) {
      const p = args.payload as Record<string, unknown>;
      if (p.cmd === 'list_sessions') return Promise.resolve([]);
      if (p.cmd === 'delete_session') return Promise.resolve({ status: 'deleted' });
      if (p.cmd === 'get_messages') return Promise.resolve([]);
      if (p.cmd === 'query') return Promise.resolve({ conversation_id: '', question: '', phases: [], agent_trace: { steps: [], total_llm_calls: 0, total_duration_ms: 0 }, all_messages: [] });
      if (p.cmd === 'import') return Promise.resolve({ talker_id: 'wxid_xxx', message_count: 0, build_status: 'pending' });
    }
    if (cmd === 'spawn_backend_build') return Promise.resolve(undefined);
    if (cmd === 'backend_query_stream') return Promise.resolve({ type: 'result', conversation_id: '', question: '', phases: [], agent_trace: { steps: [] }, all_messages: [] });
    return Promise.reject(new Error(`unmocked invoke: ${cmd}`));
  });
  mockListen.mockResolvedValue(() => {});
});

describe('listSessions', () => {
  it('returns Session array via backend_request', async () => {
    const sessions = [
      {
        talker_id: 'wxid_xxx',
        display_name: '张经理',
        last_timestamp: 1707922800000,
        build_status: 'complete',
        message_count: 125,
      },
    ];
    mockInvoke.mockResolvedValueOnce(sessions);

    const result = await api.listSessions();

    expect(result).toEqual(sessions);
    expect(mockInvoke).toHaveBeenCalledWith('backend_request', { payload: { cmd: 'list_sessions' } });
    expect(result[0]).toMatchObject({
      talker_id: expect.any(String),
      display_name: expect.any(String),
      last_timestamp: expect.any(Number),
      build_status: expect.any(String),
      message_count: expect.any(Number),
    });
  });
});

describe('queryNarrative', () => {
  it('parses QueryResponse with phases[0].phase_index and agent_trace.total_duration_ms', async () => {
    const queryResponse = {
      conversation_id: 'wxid_xxx',
      question: 'test',
      phases: [{ phase_index: 1, phase_title: 'Phase 1', time_range: '', core_conclusion: '', evidence: [], reasoning_chain: '', uncertainty_note: null, verified: true }],
      agent_trace: { steps: [], total_llm_calls: 0, total_duration_ms: 5000 },
      all_messages: [],
    };
    mockInvoke.mockResolvedValueOnce(queryResponse);

    const result = await api.queryNarrative('wxid_xxx', 'test question');

    expect(result.phases[0].phase_index).toBe(1);
    expect(typeof result.agent_trace.total_duration_ms).toBe('number');
    expect(result.agent_trace.total_duration_ms).toBe(5000);
    expect(mockInvoke).toHaveBeenCalledWith('backend_request', {
      payload: { cmd: 'query', talker: 'wxid_xxx', question: 'test question', config: 'config.yml', stream: false },
    });
  });
});

describe('error handling', () => {
  it('throws when backend_request rejects (Rust returns Err)', async () => {
    mockInvoke.mockRejectedValueOnce(new Error('Database file not found'));

    await expect(api.listSessions()).rejects.toThrow('Database file not found');
  });
});

describe('deleteSession', () => {
  it('calls backend_request with delete_session and talker', async () => {
    mockInvoke.mockResolvedValueOnce({ status: 'deleted', talker_id: 'wxid_xxx' });

    await api.deleteSession('wxid_xxx');

    expect(mockInvoke).toHaveBeenCalledWith('backend_request', { payload: { cmd: 'delete_session', talker: 'wxid_xxx' } });
  });
});

describe('triggerBuild', () => {
  it('calls Command.spawn in non-DEV (no import.meta.env in Jest)', async () => {
    const spawnMock = jest.fn().mockResolvedValue(undefined);
    mockCreate.mockReturnValue({ spawn: spawnMock });
    mockInvoke.mockResolvedValueOnce('/fake/backend');

    await api.triggerBuild('wxid_xxx');

    expect(mockInvoke).toHaveBeenCalledWith('get_backend_dir');
    expect(mockCreate).toHaveBeenCalled();
    expect(spawnMock).toHaveBeenCalled();
  });
});
