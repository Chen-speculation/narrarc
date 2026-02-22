import React, { useState, useRef } from 'react';
import { Session, QueryResponse, Message } from '../types';
import { NarrativeArc } from './NarrativeArc';
import { ChatPanel } from './ChatPanel';
import { AgentTracePanel } from './AgentTracePanel';
import { AgentProgress } from './AgentProgress';
import { Loader2, Terminal } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import * as api from '../api';


interface MainAreaProps {
  activeSession: Session | null;
  sessionMessages: Message[];
  queryResult: QueryResponse | null;
  onQueryComplete: (result: QueryResponse) => void;
  highlightedMessageId: number | null;
  onHighlightMessage: (id: number | null) => void;
}

export function MainArea({
  activeSession,
  sessionMessages,
  queryResult,
  onQueryComplete,
  highlightedMessageId,
  onHighlightMessage,
}: MainAreaProps) {
  const [query, setQuery] = useState('');
  const [queryState, setQueryState] = useState<'idle' | 'analyzing' | 'complete'>('idle');
  const [isReviewMode, setIsReviewMode] = useState(true);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [agentSteps, setAgentSteps] = useState<import('../types').AgentStep[]>([]);
  const [agentLogs, setAgentLogs] = useState<string[]>([]);

  React.useEffect(() => {
    setQueryState('idle');
    setQuery('');
    setIsReviewMode(true);
    setAgentSteps([]);
    setAgentLogs([]);
  }, [activeSession]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim() || !activeSession) return;

    setQueryState('analyzing');
    setQueryError(null);
    setAgentSteps([]);
    setAgentLogs([]);

    try {
      await api.queryNarrativeStream(activeSession.talker_id, query.trim(), {
        onProgress: (steps) => {
          setAgentSteps(steps);
          // 从真实 step 数据派生 log，与 Backend 一一对应
          const logs: string[] = [];
          for (const s of steps) {
            logs.push(`[SYS] ${s.node_name_display} ENTRY`);
            logs.push(`> INPUT: ${s.input_summary}`);
            logs.push(`> OUTPUT: ${s.output_summary}`);
            logs.push(`[SYS] ${s.node_name_display} DONE`);
          }
          setAgentLogs(logs);
        },
        onComplete: (result) => {
          onQueryComplete(result);
          setQueryState('complete');
        },
        onError: (err) => {
          setQueryError(err.message);
          setQueryState('idle');
        },
      });
    } catch (e) {
      setQueryError(e instanceof Error ? e.message : String(e));
      setQueryState('idle');
    }
  };

  if (!activeSession) {
    return (
      <div className="flex-1 flex items-center justify-center bg-zinc-50 dark:bg-[#050505] font-mono transition-colors duration-300">
        <div className="text-center text-zinc-400 dark:text-zinc-600">
          <Terminal className="w-12 h-12 mx-auto mb-4 text-zinc-300 dark:text-zinc-800" />
          <p className="text-sm tracking-widest uppercase">Awaiting Session Selection...</p>
          <p className="text-[10px] mt-2 text-zinc-500 dark:text-zinc-700">Please select a target from the sidebar</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-zinc-50 dark:bg-[#050505] text-zinc-800 dark:text-zinc-300 font-mono transition-colors duration-300">
      {/* Header & Query Input */}
      <div className="border-b border-zinc-200 dark:border-white/10 bg-white dark:bg-[#0a0a0a] z-30 sticky top-0 px-8 py-6 shadow-sm transition-colors duration-300">
        <div className="max-w-4xl mx-auto">
          <div className="flex items-center justify-between mb-5">
            <h2 className="font-title text-xl font-bold text-zinc-900 dark:text-white flex items-center gap-3">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              目标：{activeSession.display_name}
            </h2>
            <div className="font-title flex items-center gap-2 text-[10px] text-zinc-500 bg-zinc-100 dark:bg-black/50 border border-zinc-200 dark:border-white/5 px-3 py-1.5">
              共 {activeSession.message_count} 条
            </div>
          </div>
          <form onSubmit={handleSubmit} className="relative">
            <div className="relative flex items-center shadow-sm group">
              <span className="absolute left-5 text-indigo-500 font-bold text-lg">{'>'}</span>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="输入查询..."
                className="w-full pl-12 pr-4 py-4 bg-zinc-50 dark:bg-[#050505] border border-zinc-200 dark:border-white/10 focus:outline-none focus:border-indigo-500/50 transition-all text-sm text-zinc-900 dark:text-emerald-400 placeholder:text-zinc-400 dark:placeholder:text-zinc-600"
                disabled={activeSession.build_status !== 'complete' || queryState === 'analyzing'}
              />
              {queryState === 'analyzing' && (
                <div className="absolute right-5">
                  <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
                </div>
              )}
            </div>
            {queryError && (
              <p className="mt-2 text-sm text-amber-600 dark:text-amber-500">{queryError}</p>
            )}
          </form>
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 flex overflow-hidden relative bg-zinc-50 dark:bg-[#050505] transition-colors duration-300">
        <AnimatePresence mode="wait">
          {queryState === 'idle' ? (
            <motion.div
              key="idle"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex-1 flex justify-center overflow-hidden w-full"
            >
              <div className="w-full max-w-4xl flex flex-col h-full border-x border-zinc-200 dark:border-white/5 bg-white dark:bg-[#0a0a0a] transition-colors duration-300">
                <div className="p-4 border-b border-zinc-200 dark:border-white/5 bg-zinc-50 dark:bg-[#050505] text-center transition-colors duration-300">
                  <p className="font-title text-[10px] text-zinc-400 dark:text-zinc-600 uppercase tracking-widest">原始数据流</p>
                </div>
                {sessionMessages.length > 0 ? (
                  <ChatPanel messages={sessionMessages} highlightedMessageId={null} />
                ) : (
                  <div className="flex-1 flex items-center justify-center">
                    <div className="text-center text-zinc-400 dark:text-zinc-500 max-w-md">
                      {activeSession.build_status === 'in_progress' ? (
                        <>
                          <Loader2 className="w-6 h-6 animate-spin text-indigo-500 mx-auto mb-4" />
                          <p className="text-sm tracking-widest uppercase mb-2">BUILDING INDEX...</p>
                          <p className="text-[10px] text-zinc-500 dark:text-zinc-600">Please wait while the system analyzes the structure.</p>
                        </>
                      ) : (
                        <>
                          <p className="text-sm tracking-widest uppercase mb-2">AWAITING BUILD</p>
                          <p className="text-[10px] text-zinc-500 dark:text-zinc-600">This session has not been indexed yet.</p>
                        </>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </motion.div>
          ) : queryState === 'analyzing' ? (
            <motion.div
              key="analyzing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, scale: 0.98 }}
              className="absolute inset-0 flex items-center justify-center bg-white/90 dark:bg-[#050505]/90 backdrop-blur-md z-20 transition-colors duration-300"
            >
              <AgentProgress steps={agentSteps} logs={agentLogs} />
            </motion.div>
          ) : queryState === 'complete' && queryResult ? (
            <motion.div
              key="results"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex-1 flex overflow-hidden w-full"
            >
              {/* Left: Narrative Arc & Agent Trace */}
              <div className="flex-1 overflow-y-auto p-8 border-r border-zinc-200 dark:border-white/5 bg-zinc-50 dark:bg-[#050505] transition-colors duration-300 min-w-0">
                <div className="max-w-4xl mx-auto space-y-10 pb-12 h-full flex flex-col">
                  <NarrativeArc
                    phases={queryResult.phases}
                    onHighlightMessage={onHighlightMessage}
                    isReviewMode={isReviewMode}
                    onReviewComplete={() => setIsReviewMode(false)}
                    onRestartReview={() => setIsReviewMode(true)}
                  />
                  {!isReviewMode && (
                    <motion.div
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.2 }}
                    >
                      <AgentTracePanel trace={queryResult.agent_trace} />
                    </motion.div>
                  )}
                </div>
              </div>

              {/* Right: Chat History */}
              <div className="w-[320px] min-w-[280px] max-w-[400px] flex-shrink-0 bg-white dark:bg-[#0a0a0a] border-l border-zinc-200 dark:border-white/5 flex flex-col z-10 transition-colors duration-300">
                <div className="p-5 border-b border-zinc-200 dark:border-white/5 bg-white dark:bg-[#0a0a0a] z-10 sticky top-0 flex justify-between items-center transition-colors duration-300">
                  <h3 className="font-title text-xs font-bold tracking-widest uppercase text-zinc-500 dark:text-zinc-300">原始数据流</h3>
                  <span className="font-title text-[10px] text-zinc-500 bg-zinc-100 dark:bg-black/50 border border-zinc-200 dark:border-white/5 px-2 py-1">
                    共 {queryResult.all_messages.length} 条
                  </span>
                </div>
                <ChatPanel messages={queryResult.all_messages} highlightedMessageId={highlightedMessageId} />
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </div>
  );
}
