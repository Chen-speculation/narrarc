import { Session } from '../types';
import { MessageSquare, CheckCircle2, Clock, Loader2, PlusCircle, Terminal, Sun, Moon, Trash2 } from 'lucide-react';

export function Sidebar({ sessions, activeSession, onSelectSession, onDeleteSession, isDarkMode, toggleTheme, onOpenImport }: { 
  sessions: Session[], 
  activeSession: Session | null, 
  onSelectSession: (s: Session) => void,
  onDeleteSession: (s: Session) => void,
  isDarkMode: boolean,
  toggleTheme: () => void,
  onOpenImport: () => void
}) {
  return (
    <div className="w-[240px] min-w-[200px] bg-white dark:bg-[#0a0a0a] text-zinc-600 dark:text-zinc-300 flex flex-col h-full flex-shrink-0 border-r border-zinc-200 dark:border-white/5 font-mono transition-colors duration-300">
      <div className="p-7 border-b border-zinc-200 dark:border-white/5">
        <h1 className="font-title text-lg font-bold text-zinc-900 dark:text-white flex items-center gap-3 tracking-tight mb-4">
          <Terminal className="w-5 h-5 text-indigo-600 dark:text-indigo-500" />
          <span className="font-title tracking-widest">叙事镜鉴</span>
          <span className="animate-pulse text-indigo-600 dark:text-indigo-500">_</span>
        </h1>
        
        <button 
          onClick={toggleTheme} 
          className="w-full flex items-center justify-between px-4 py-2.5 rounded-lg bg-zinc-100 dark:bg-white/5 hover:bg-zinc-200 dark:hover:bg-white/10 transition-all group border border-transparent hover:border-zinc-300 dark:hover:border-white/10"
        >
          <span className="text-[10px] font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-widest group-hover:text-zinc-800 dark:group-hover:text-zinc-200 transition-colors">
            {isDarkMode ? 'SWITCH_TO_LIGHT' : 'SWITCH_TO_DARK'}
          </span>
          {isDarkMode ? (
            <Sun className="w-3.5 h-3.5 text-zinc-500 dark:text-zinc-400 group-hover:text-amber-500 transition-colors" />
          ) : (
            <Moon className="w-3.5 h-3.5 text-zinc-500 dark:text-zinc-400 group-hover:text-indigo-500 transition-colors" />
          )}
        </button>
      </div>

      <div className="p-5">
        <button 
          onClick={onOpenImport}
          className="font-title w-full flex items-center justify-center gap-2 bg-zinc-50 dark:bg-[#050505] hover:bg-zinc-100 dark:hover:bg-white/5 text-emerald-600 dark:text-emerald-400 py-3 transition-all text-xs font-medium border border-zinc-200 dark:border-white/5 hover:border-emerald-500/30 uppercase tracking-widest"
        >
          <PlusCircle className="w-3.5 h-3.5" />
          导入数据
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-1">
        <h2 className="font-title px-4 text-[10px] font-semibold text-zinc-400 dark:text-zinc-600 uppercase tracking-widest mb-4 mt-2">会话列表</h2>
        {sessions.map((session) => (
          <div
            key={session.talker_id}
            className={`w-full text-left p-4 transition-all flex flex-col gap-3 group border-l-2 relative
              ${activeSession?.talker_id === session.talker_id 
                ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-900 dark:text-white border-indigo-500' 
                : 'border-transparent hover:bg-zinc-50 dark:hover:bg-white/5 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200'
              }
            `}
          >
            <button
              onClick={() => onSelectSession(session)}
              className="flex-1 text-left flex flex-col gap-3"
            >
              <div className="flex items-center justify-between gap-2 min-w-0">
                <div className="flex items-center gap-2.5 font-medium text-[13px] tracking-wide min-w-0 flex-1">
                  <MessageSquare className={`w-3.5 h-3.5 shrink-0 ${activeSession?.talker_id === session.talker_id ? 'text-indigo-600 dark:text-indigo-400' : 'text-zinc-400 dark:text-zinc-600 group-hover:text-zinc-500 dark:group-hover:text-zinc-400'}`} />
                  <span className="truncate" title={session.display_name}>{session.display_name}</span>
                </div>
                {session.build_status === 'complete' && <CheckCircle2 className="w-3.5 h-3.5 shrink-0 text-emerald-600 dark:text-emerald-500/80" />}
                {session.build_status === 'in_progress' && <Loader2 className="w-3.5 h-3.5 shrink-0 text-indigo-600 dark:text-indigo-400 animate-spin" />}
                {session.build_status === 'pending' && <Clock className="w-3.5 h-3.5 shrink-0 text-zinc-400 dark:text-zinc-600" />}
              </div>
              
              <div className="flex items-center justify-between text-[10px]">
                <span className="font-title text-zinc-500 dark:text-zinc-500 bg-zinc-100 dark:bg-black/40 px-2 py-0.5 border border-zinc-200 dark:border-white/5">{session.message_count} 条</span>
                <span className="text-zinc-400 dark:text-zinc-600 tracking-wide">{new Date(session.last_timestamp).toLocaleDateString()}</span>
              </div>
              {session.build_status === 'in_progress' && session.build_progress?.detail && (
                <p className="text-[10px] text-indigo-600 dark:text-indigo-400 truncate" title={session.build_progress.detail}>
                  {session.build_progress.detail}
                </p>
              )}
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); onDeleteSession(session); }}
              className="absolute top-3 right-3 p-1.5 rounded opacity-0 group-hover:opacity-100 hover:bg-red-500/20 text-zinc-400 hover:text-red-500 dark:text-zinc-500 dark:hover:text-red-400 transition-all"
              title="删除会话"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
