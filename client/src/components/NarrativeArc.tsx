import { useState, useEffect } from 'react';
import { Phase } from '../types';
import { ChevronRight, AlertCircle, CheckCircle2, MessageSquareText, Edit2, Check, RotateCcw } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

interface NarrativeArcProps {
  phases: Phase[];
  onHighlightMessage: (id: number) => void;
  isReviewMode: boolean;
  onReviewComplete: () => void;
  onRestartReview: () => void;
}

export function NarrativeArc({ phases, onHighlightMessage, isReviewMode, onReviewComplete, onRestartReview }: NarrativeArcProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [reviewedIndices, setReviewedIndices] = useState<Set<number>>(new Set());

  const [isEditing, setIsEditing] = useState(false);

  // Reset index when entering review mode
  useEffect(() => {
    if (isReviewMode) {
      setCurrentIndex(0);
      setReviewedIndices(new Set());
      setIsEditing(false);
    }
  }, [isReviewMode]);

  const handleConfirm = () => {
    setReviewedIndices(prev => new Set(prev).add(currentIndex));
    setIsEditing(false);
    if (currentIndex < phases.length - 1) {
      setCurrentIndex(prev => prev + 1);
    } else {
      onReviewComplete();
    }
  };

  if (isReviewMode) {
    const currentPhase = phases[currentIndex];
    const progress = ((currentIndex) / phases.length) * 100;

    return (
      <div className="h-full flex flex-col font-mono transition-colors duration-300 relative w-full max-w-3xl mx-auto py-10">
        {/* Progress Header */}
        <div className="mb-12 space-y-4">
          <div className="flex justify-between items-end text-zinc-500 dark:text-zinc-400">
            <h3 className="font-title text-sm font-bold tracking-widest uppercase flex items-center gap-2">
              <span className="w-2 h-2 bg-indigo-500 rounded-full animate-pulse"></span>
              叙事审阅
            </h3>
            <span className="font-title text-xs font-mono">步骤 {currentIndex + 1} / {phases.length}</span>
          </div>
          <div className="w-full h-1 bg-zinc-200 dark:bg-white/10 rounded-full overflow-hidden">
            <motion.div 
              className="h-full bg-indigo-600 dark:bg-indigo-500"
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>

        <div className="flex-1 relative perspective-1000 min-h-[500px]">
          <AnimatePresence mode="wait">
            <motion.div
              key={currentPhase.phase_index}
              initial={{ opacity: 0, x: 100, rotateY: -10 }}
              animate={{ opacity: 1, x: 0, rotateY: 0 }}
              exit={{ opacity: 0, x: -100, rotateY: 10, scale: 0.9 }}
              transition={{ type: "spring", stiffness: 260, damping: 20 }}
              className="absolute inset-0 z-20"
            >
              <div className="h-full bg-white dark:bg-[#0a0a0a] border border-zinc-200 dark:border-white/10 shadow-2xl flex flex-col overflow-hidden rounded-xl">
                {/* Card Header */}
                <div className="p-8 border-b border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-[#050505] flex justify-between items-start">
                  <div>
                    <div className="flex items-center gap-3 mb-3">
                      <span className="font-title text-[10px] font-bold tracking-widest text-white dark:text-black uppercase bg-indigo-600 dark:bg-indigo-500 px-2 py-0.5 rounded-sm">
                        阶段 {currentPhase.phase_index}
                      </span>
                      <span className="text-xs text-zinc-500 tracking-wide font-mono">[{currentPhase.time_range}]</span>
                    </div>
                    {isEditing ? (
                      <input 
                        type="text" 
                        defaultValue={currentPhase.phase_title}
                        className="w-full bg-transparent border-b border-indigo-500 text-2xl font-bold text-zinc-900 dark:text-white tracking-tight leading-tight focus:outline-none"
                      />
                    ) : (
                      <h4 className="font-title text-2xl font-bold text-zinc-900 dark:text-white tracking-tight leading-tight">
                        {currentPhase.phase_title}
                      </h4>
                    )}
                  </div>
                </div>

                {/* Card Content */}
                <div className="flex-1 overflow-y-auto p-8 space-y-8 bg-white dark:bg-[#0a0a0a]">
                  <div className="prose dark:prose-invert max-w-none">
                    {isEditing ? (
                      <textarea 
                        defaultValue={currentPhase.core_conclusion}
                        className="w-full h-32 bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg p-4 text-lg text-zinc-700 dark:text-zinc-300 leading-relaxed font-sans focus:outline-none focus:border-indigo-500 resize-none"
                      />
                    ) : (
                      <p className="text-lg text-zinc-700 dark:text-zinc-300 leading-relaxed font-sans">
                        {currentPhase.core_conclusion}
                      </p>
                    )}
                  </div>

                  {currentPhase.uncertainty_note && (
                    <motion.div 
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="flex items-start gap-3 bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 p-4 text-sm border border-amber-200 dark:border-amber-500/30 rounded-lg"
                    >
                      <AlertCircle className="w-5 h-5 mt-0.5 flex-shrink-0" />
                      <p className="leading-relaxed"><strong>UNCERTAINTY DETECTED:</strong> {currentPhase.uncertainty_note}</p>
                    </motion.div>
                  )}

                  <div className="space-y-4 pt-4 border-t border-zinc-100 dark:border-white/5">
                    <h5 className="font-title text-[10px] font-semibold text-zinc-500 uppercase tracking-widest flex items-center gap-2">
                      <MessageSquareText className="w-3.5 h-3.5" />
                      关键证据
                    </h5>
                    <div className="grid gap-3">
                      {currentPhase.evidence.map((ev) => (
                        <button
                          key={ev.local_id}
                          onClick={() => onHighlightMessage(ev.local_id)}
                          className="text-left flex flex-col gap-2 p-4 bg-zinc-50 dark:bg-[#050505] hover:bg-indigo-50 dark:hover:bg-indigo-500/10 border border-zinc-200 dark:border-white/5 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all group rounded-lg"
                        >
                          <div className="flex items-center justify-between w-full">
                            <span className="text-[11px] font-bold text-zinc-600 dark:text-zinc-500 group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors uppercase tracking-widest">
                              {ev.sender_display}
                            </span>
                            <span className="text-[10px] text-zinc-400 dark:text-zinc-600 tracking-wide">
                              [{new Date(ev.create_time).toLocaleDateString()}]
                            </span>
                          </div>
                          <p className="text-[13px] text-zinc-600 dark:text-zinc-400 line-clamp-2 leading-relaxed font-sans">{ev.parsed_content}</p>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Card Actions */}
                <div className="p-6 border-t border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-[#050505] flex gap-4">
                  <button 
                    onClick={() => setIsEditing(!isEditing)}
                    className={`flex-1 py-3 px-4 flex items-center justify-center gap-2 border text-xs font-bold uppercase tracking-widest transition-colors rounded-lg ${isEditing ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-500/10' : 'border-zinc-300 dark:border-white/10 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-white/5'}`}
                  >
                    <Edit2 className="w-4 h-4" />
                    {isEditing ? 'SAVE_CHANGES' : 'MODIFY'}
                  </button>
                  <button 
                    onClick={handleConfirm}
                    className="flex-[2] py-3 px-4 flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white transition-colors uppercase tracking-widest text-xs font-bold shadow-lg shadow-indigo-500/20 rounded-lg"
                  >
                    <Check className="w-4 h-4" />
                    CONFIRM & NEXT
                  </button>
                </div>
              </div>
            </motion.div>
          </AnimatePresence>
          
          {/* Stack Effect Background Cards */}
          {currentIndex < phases.length - 1 && (
            <div className="absolute top-4 left-4 right-[-16px] bottom-[-16px] bg-white dark:bg-[#0a0a0a] border border-zinc-200 dark:border-white/5 rounded-xl z-10 opacity-50 scale-[0.98] shadow-lg transform translate-y-2" />
          )}
          {currentIndex < phases.length - 2 && (
            <div className="absolute top-8 left-8 right-[-32px] bottom-[-32px] bg-white dark:bg-[#0a0a0a] border border-zinc-200 dark:border-white/5 rounded-xl z-0 opacity-30 scale-[0.96] shadow-lg transform translate-y-4" />
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8 font-mono transition-colors duration-300">
      <div className="flex justify-between items-center">
        <h3 className="font-title text-sm font-bold text-zinc-800 dark:text-zinc-300 flex items-center gap-3 tracking-widest uppercase">
          <span className="w-2 h-2 bg-indigo-600 dark:bg-indigo-500 rounded-none animate-pulse"></span>
          叙事图谱
        </h3>
        <button 
          onClick={onRestartReview}
          className="font-title flex items-center gap-2 text-[10px] text-zinc-500 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors uppercase tracking-widest"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          重新审阅
        </button>
      </div>
      
      <div className="relative border-l border-dashed border-zinc-300 dark:border-white/10 ml-4 space-y-10 pb-4 transition-colors duration-300">
        {phases.map((phase, i) => (
          <motion.div 
            key={phase.phase_index} 
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.15, duration: 0.5 }}
            className="relative pl-10"
          >
            {/* Timeline dot */}
            <div className="absolute -left-[5px] top-1.5 w-2.5 h-2.5 rounded-none bg-white dark:bg-[#0a0a0a] border border-indigo-500 shadow-[0_0_10px_rgba(99,102,241,0.5)] z-10 transition-colors duration-300" />
            
            <div className="bg-white dark:bg-[#0a0a0a] rounded-none p-8 shadow-sm border border-zinc-200 dark:border-white/10 hover:border-indigo-400 dark:hover:border-indigo-500/50 transition-colors group/card">
              <div className="flex justify-between items-start mb-5">
                <div>
                  <div className="flex items-center gap-3 mb-2">
                    <span className="font-title text-[10px] font-bold tracking-widest text-white dark:text-black uppercase bg-indigo-600 dark:bg-indigo-500 px-2 py-0.5">
                      阶段 {phase.phase_index}
                    </span>
                    <span className="text-xs text-zinc-500 tracking-wide">[{phase.time_range}]</span>
                  </div>
                  <h4 className="font-title text-lg font-bold text-emerald-600 dark:text-emerald-400 mt-4 tracking-tight">{phase.phase_title}</h4>
                </div>
                {phase.verified && (
                  <div className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 px-2.5 py-1.5 text-[10px] tracking-widest uppercase border border-emerald-200 dark:border-emerald-500/30 transition-colors duration-300">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    VERIFIED
                  </div>
                )}
              </div>
              
              <p className="text-zinc-800 dark:text-zinc-300 leading-relaxed mb-8 text-[14px] font-sans transition-colors duration-300">
                {phase.core_conclusion}
              </p>
              
              {phase.uncertainty_note && (
                <div className="mb-8 flex items-start gap-3 bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-400 p-4 text-xs border border-amber-200 dark:border-amber-500/30 transition-colors duration-300">
                  <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                  <p className="leading-relaxed"><strong>WARN_UNCERTAINTY:</strong> {phase.uncertainty_note}</p>
                </div>
              )}

              <div className="space-y-4">
                <h5 className="font-title text-[10px] font-semibold text-zinc-500 uppercase tracking-widest flex items-center gap-2">
                  <MessageSquareText className="w-3.5 h-3.5" />
                  证据 ({phase.evidence.length})
                </h5>
                <div className="grid gap-3">
                  {phase.evidence.map((ev) => (
                    <button
                      key={ev.local_id}
                      onClick={() => onHighlightMessage(ev.local_id)}
                      className="text-left flex flex-col gap-2 p-4 bg-zinc-50 dark:bg-[#050505] hover:bg-indigo-50 dark:hover:bg-indigo-500/10 border border-zinc-200 dark:border-white/5 hover:border-indigo-300 dark:hover:border-indigo-500/50 transition-all group"
                    >
                      <div className="flex items-center justify-between w-full">
                        <span className="text-[11px] font-bold text-zinc-600 dark:text-zinc-500 group-hover:text-indigo-600 dark:group-hover:text-indigo-400 transition-colors uppercase tracking-widest">
                          {ev.sender_display}
                        </span>
                        <span className="text-[10px] text-zinc-400 dark:text-zinc-600 tracking-wide">
                          [{new Date(ev.create_time).toLocaleDateString()}]
                        </span>
                      </div>
                      <p className="text-[13px] text-zinc-600 dark:text-zinc-400 line-clamp-2 leading-relaxed font-sans">{ev.parsed_content}</p>
                    </button>
                  ))}
                </div>
              </div>

              <div className="mt-8 pt-5 border-t border-zinc-200 dark:border-white/5 transition-colors duration-300">
                <details className="group/details">
                  <summary className="flex items-center gap-2 text-[11px] uppercase tracking-widest text-zinc-500 cursor-pointer hover:text-indigo-600 dark:hover:text-indigo-400 font-medium list-none transition-colors">
                    <ChevronRight className="w-4 h-4 transition-transform group-open/details:rotate-90" />
                    展开推理链
                  </summary>
                  <p className="mt-4 text-[13px] text-zinc-600 dark:text-zinc-400 pl-6 leading-relaxed border-l-2 border-zinc-200 dark:border-white/10 ml-2 font-sans transition-colors duration-300">
                    {phase.reasoning_chain}
                  </p>
                </details>
              </div>
            </div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
