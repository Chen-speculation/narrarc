import { useEffect, useRef } from 'react';
import { Message } from '../types';
import { motion } from 'motion/react';

export function ChatPanel({ messages, highlightedMessageId }: { messages: Message[], highlightedMessageId: number | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const messageRefs = useRef<{ [key: number]: HTMLDivElement | null }>({});

  useEffect(() => {
    if (highlightedMessageId && messageRefs.current[highlightedMessageId]) {
      messageRefs.current[highlightedMessageId]?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }, [highlightedMessageId]);

  return (
    <motion.div 
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5, delay: 0.1 }}
      ref={containerRef} 
      className="flex-1 overflow-y-auto p-6 space-y-3 bg-zinc-50 dark:bg-[#050505] font-mono transition-colors duration-300"
    >
      {messages.map((msg) => {
        const isHighlighted = msg.local_id === highlightedMessageId;
        const isSend = msg.is_send;
        return (
          <div 
            key={msg.local_id} 
            ref={(el) => messageRefs.current[msg.local_id] = el}
            className={`group flex ${isSend ? 'justify-end' : 'justify-start'} transition-all duration-300`}
          >
            <div
              className={`max-w-[85%] flex flex-col gap-1 py-2 px-4 rounded-xl border transition-all duration-300
                ${isSend 
                  ? 'rounded-br-sm bg-indigo-50 dark:bg-indigo-500/10 border-indigo-200 dark:border-indigo-500/30' 
                  : 'rounded-bl-sm bg-white dark:bg-[#0a0a0a] border-zinc-200 dark:border-white/10'
                }
                ${isHighlighted 
                  ? 'ring-2 ring-indigo-500 dark:ring-indigo-400' 
                  : 'hover:bg-zinc-50 dark:hover:bg-white/5'
                }
              `}
            >
              <div className="flex items-center gap-2 text-[10px] text-zinc-500 dark:text-zinc-400">
                <span className={`font-bold uppercase ${isSend ? 'text-emerald-600 dark:text-emerald-500' : 'text-indigo-600 dark:text-indigo-400'}`}>
                  {msg.sender_display}
                </span>
                <span className="tracking-wider">
                  {new Date(msg.create_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
              <div className={`text-[13px] leading-relaxed ${isHighlighted ? 'text-zinc-900 dark:text-indigo-100' : 'text-zinc-700 dark:text-zinc-300'}`}>
                {msg.parsed_content}
              </div>
            </div>
          </div>
        );
      })}
    </motion.div>
  );
}
