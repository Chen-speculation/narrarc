import { motion, AnimatePresence } from 'motion/react';
import { useEffect, useRef } from 'react';
import { AgentStep } from '../types';

export function AgentProgress({ steps, logs }: { steps: AgentStep[]; logs: string[] }) {
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <div className="flex flex-col items-center justify-center h-full max-w-4xl mx-auto w-full p-8">
      <motion.div 
        initial={{ opacity: 0, y: 30, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        className="w-full min-h-[420px] bg-white dark:bg-[#0a0a0a] rounded-3xl shadow-[0_32px_64px_-16px_rgba(0,0,0,0.1)] dark:shadow-[0_32px_64px_-16px_rgba(0,0,0,0.5)] border border-zinc-200 dark:border-white/10 overflow-hidden flex transition-colors duration-300"
      >
        {/* Left: Steps */}
        <div className="w-1/2 p-10 border-r border-zinc-200 dark:border-white/5 relative bg-white dark:bg-[#0a0a0a] transition-colors duration-300">
          {/* Subtle glow behind steps */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-64 h-64 bg-indigo-500/10 blur-[80px] rounded-full pointer-events-none" />
          
          <div className="text-[10px] text-zinc-500 mb-10 tracking-[0.2em] font-mono uppercase">
            System.Agent_Trace // Narrative_Extraction
          </div>

          <div className="space-y-8 relative">
            {steps.length === 0 && (
              <div className="text-zinc-500 dark:text-zinc-600 text-sm">正在分析...</div>
            )}
            {steps.map((step, idx) => {
              const isCompleted = steps.length > 1 && idx < steps.length - 1;
              const isCurrent = idx === steps.length - 1;
              const isPending = false;

              let statusText = "WAIT";
              if (isCompleted) statusText = "DONE";
              if (isCurrent) statusText = "EXEC";

              return (
                <motion.div 
                  key={idx}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: isPending ? 0.3 : 1, x: 0 }}
                  transition={{ delay: idx * 0.1 }}
                  className="relative flex items-start gap-5 font-mono"
                >
                  <div className={`text-[10px] mt-1 tracking-widest flex-shrink-0 w-12 ${isCurrent ? 'text-indigo-600 dark:text-indigo-400 animate-pulse' : isCompleted ? 'text-emerald-600 dark:text-emerald-500/70' : 'text-zinc-400 dark:text-zinc-600'}`}>
                    [{statusText}]
                  </div>
                  <div className="flex-1">
                    <h4 className={`text-[13px] tracking-wide ${isCompleted ? 'text-zinc-400' : isCurrent ? 'text-zinc-900 dark:text-white' : 'text-zinc-400 dark:text-zinc-600'}`}>
                      {step.node_name_display}
                    </h4>
                    
                    <AnimatePresence>
                      {isCurrent && (
                        <motion.div 
                          initial={{ height: 0, opacity: 0 }} 
                          animate={{ height: 'auto', opacity: 1 }} 
                          exit={{ height: 0, opacity: 0 }}
                          className="text-[11px] text-zinc-500 mt-3 leading-relaxed overflow-hidden"
                        >
                          <div className="text-indigo-600 dark:text-indigo-400/70 mb-1">&gt; INPUT: {step.input_summary}</div>
                          <div className="text-emerald-600 dark:text-emerald-400/70">
                            &gt; OUTPUT: {step.output_summary}
                            <motion.span 
                              animate={{ opacity: [0, 1, 0] }} 
                              transition={{ repeat: Infinity, duration: 0.8 }}
                              className="inline-block w-1.5 h-3 bg-emerald-600 dark:bg-emerald-400/70 ml-1 align-middle"
                            />
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>

        {/* Right: Terminal Stream */}
        <div className="w-1/2 p-10 bg-zinc-50 dark:bg-[#050505] relative overflow-hidden font-mono text-[10px] leading-relaxed flex flex-col transition-colors duration-300">
          <div className="text-zinc-500 dark:text-zinc-600 mb-6 tracking-[0.2em] uppercase flex justify-between">
            <span>Process_Log</span>
            <span className="text-indigo-600 dark:text-indigo-500/50 animate-pulse">● REC</span>
          </div>
          
          <div className="flex-1 overflow-y-auto pr-2 space-y-1.5 text-zinc-500 dark:text-zinc-400" style={{ scrollbarWidth: 'none' }}>
            {logs.map((log, i) => {
              const stepIdx = Math.floor(i / 4);
              const ts = steps[stepIdx]?.timestamp_ms;
              const timeStr = ts
                ? new Date(ts).toISOString().split('T')[1].slice(0, 12)
                : new Date().toISOString().split('T')[1].slice(0, 12);
              return (
                <motion.div 
                  key={i}
                  initial={{ opacity: 0, x: 10 }}
                  animate={{ opacity: 1, x: 0 }}
                  className={log?.includes('OUTPUT:') || log?.includes('DONE') ? 'text-emerald-600 dark:text-emerald-400/80' : log?.includes('INPUT:') ? 'text-indigo-600 dark:text-indigo-400/80' : ''}
                >
                  <span className="text-zinc-400 dark:text-zinc-600 mr-3">{timeStr}</span>
                  {log}
                </motion.div>
              );
            })}
            <div ref={logsEndRef} />
          </div>
          
          {/* Gradient mask for smooth fading at top/bottom of terminal */}
          <div className="absolute top-0 left-0 right-0 h-16 bg-gradient-to-b from-zinc-50 dark:from-[#050505] to-transparent pointer-events-none" />
          <div className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-zinc-50 dark:from-[#050505] to-transparent pointer-events-none" />
        </div>
      </motion.div>
    </div>
  );
}
