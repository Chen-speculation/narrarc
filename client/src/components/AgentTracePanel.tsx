import { AgentTrace } from '../types';
import { Activity, ChevronRight, Clock, Cpu } from 'lucide-react';
import { motion } from 'motion/react';

export function AgentTracePanel({ trace }: { trace: AgentTrace }) {
  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.6, duration: 0.5 }}
      className="bg-white dark:bg-[#0a0a0a] rounded-none border border-zinc-200 dark:border-white/10 shadow-sm overflow-hidden font-mono transition-colors duration-300"
    >
      <details className="group">
        <summary className="flex items-center justify-between p-5 cursor-pointer bg-zinc-50 dark:bg-[#050505] hover:bg-zinc-100 dark:hover:bg-white/5 transition-colors list-none">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-indigo-50 dark:bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 rounded-none border border-indigo-200 dark:border-indigo-500/30">
              <Activity className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-semibold text-zinc-900 dark:text-zinc-100 uppercase tracking-widest text-xs">AGENT_TRACE</h3>
              <p className="text-[10px] text-zinc-500 mt-1 flex items-center gap-3">
                <span className="flex items-center gap-1"><Cpu className="w-3 h-3" /> {trace.total_llm_calls} CALLS</span>
                <span className="flex items-center gap-1"><Clock className="w-3 h-3" /> {(trace.total_duration_ms / 1000).toFixed(1)}s</span>
              </p>
            </div>
          </div>
          <ChevronRight className="w-4 h-4 text-zinc-400 transition-transform group-open:rotate-90" />
        </summary>
        
        <div className="p-5 border-t border-zinc-200 dark:border-white/10 bg-white dark:bg-[#0a0a0a] transition-colors duration-300">
          <div className="relative border-l border-zinc-200 dark:border-white/10 ml-3 space-y-6 pb-2">
            {trace.steps.map((step, idx) => (
              <div key={idx} className="relative pl-6">
                <div className="absolute -left-[5px] top-1.5 w-2.5 h-2.5 rounded-none bg-white dark:bg-[#0a0a0a] border border-indigo-500" />
                <div className="mb-1 flex items-center gap-2">
                  <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-wider">{step.node_name_display}</span>
                  <span className="text-[10px] text-zinc-500 dark:text-zinc-400 tracking-wide bg-zinc-100 dark:bg-white/5 px-1.5 py-0.5 border border-zinc-200 dark:border-white/5">
                    {new Date(step.timestamp_ms).toLocaleTimeString([], {hour12: false, hour: '2-digit', minute:'2-digit', second:'2-digit'})}
                  </span>
                </div>
                <div className="text-[11px] text-zinc-600 dark:text-zinc-400 space-y-2 mt-3">
                  <p className="flex gap-2"><span className="text-zinc-400 dark:text-zinc-500 w-12 flex-shrink-0">INPUT:</span> {step.input_summary}</p>
                  <p className="flex gap-2"><span className="text-zinc-400 dark:text-zinc-500 w-12 flex-shrink-0">OUTPUT:</span> <span className="text-emerald-600 dark:text-emerald-400">{step.output_summary}</span></p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </details>
    </motion.div>
  );
}
