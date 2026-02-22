import { jest } from '@jest/globals';

const mockCreate = jest.fn();

jest.unstable_mockModule('@tauri-apps/plugin-shell', () => ({
  Command: { create: mockCreate },
}));

const api = await import('../api');

beforeEach(() => {
  mockCreate.mockClear();
});

describe('listSessions', () => {
  it('returns Session array with correct field types', async () => {
    const sessions = [
      {
        talker_id: 'wxid_xxx',
        display_name: '张经理',
        last_timestamp: 1707922800000,
        build_status: 'complete',
        message_count: 125,
      },
    ];
    mockCreate.mockReturnValue({
      execute: jest.fn().mockResolvedValue({ code: 0, stdout: JSON.stringify(sessions), stderr: '' }),
    });

    const result = await api.listSessions();

    expect(result).toEqual(sessions);
    expect(result[0]).toMatchObject({
      talker_id: expect.any(String),
      display_name: expect.any(String),
      last_timestamp: expect.any(Number),
      build_status: expect.any(String),
      message_count: expect.any(Number),
    });
    expect(mockCreate).toHaveBeenCalledWith('uv', expect.arrayContaining(['list_sessions', '--db']));
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
    mockCreate.mockReturnValue({
      execute: jest.fn().mockResolvedValue({ code: 0, stdout: JSON.stringify(queryResponse), stderr: '' }),
    });

    const result = await api.queryNarrative('wxid_xxx', 'test question');

    expect(result.phases[0].phase_index).toBe(1);
    expect(typeof result.agent_trace.total_duration_ms).toBe('number');
    expect(result.agent_trace.total_duration_ms).toBe(5000);
  });
});

describe('error handling', () => {
  it('throws Error with stderr when exit code is non-zero', async () => {
    mockCreate.mockReturnValue({
      execute: jest.fn().mockResolvedValue({ code: 1, stdout: '', stderr: 'uv: command not found' }),
    });

    await expect(api.listSessions()).rejects.toThrow('CLI error: uv: command not found');
  });
});

describe('deleteSession', () => {
  it('calls delete_session with --talker', async () => {
    mockCreate.mockReturnValue({
      execute: jest.fn().mockResolvedValue({ code: 0, stdout: '{"status":"deleted","talker_id":"wxid_xxx"}', stderr: '' }),
    });

    await api.deleteSession('wxid_xxx');

    expect(mockCreate).toHaveBeenCalledWith('uv', expect.arrayContaining(['delete_session', '--talker', 'wxid_xxx']));
  });
});

describe('triggerBuild', () => {
  it('uses spawn() not execute()', async () => {
    const spawnMock = jest.fn().mockResolvedValue(undefined);
    const executeMock = jest.fn();
    mockCreate.mockReturnValue({
      execute: executeMock,
      spawn: spawnMock,
    });

    await api.triggerBuild('wxid_xxx');

    expect(spawnMock).toHaveBeenCalled();
    expect(executeMock).not.toHaveBeenCalled();
  });
});
