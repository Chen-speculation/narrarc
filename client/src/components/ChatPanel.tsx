import { useEffect, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { Message } from '../types';
import { motion } from 'motion/react';

const ESTIMATE_ITEM_HEIGHT = 80;
const LOAD_THRESHOLD = 400; // px from edge to trigger load

interface ChatPanelProps {
  messages: Message[];
  highlightedMessageId: number | null;
  hasMoreBefore?: boolean;
  hasMoreAfter?: boolean;
  onLoadMoreBefore?: () => Promise<void>;
  onLoadMoreAfter?: () => Promise<void>;
}

export function ChatPanel({
  messages,
  highlightedMessageId,
  hasMoreBefore,
  hasMoreAfter,
  onLoadMoreBefore,
  onLoadMoreAfter,
}: ChatPanelProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const prevFirstIdRef = useRef<number | null>(null);
  const [isLoadingBefore, setIsLoadingBefore] = useState(false);
  const [isLoadingAfter, setIsLoadingAfter] = useState(false);

  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ESTIMATE_ITEM_HEIGHT,
    overscan: 3,
  });

  // Maintain scroll position when messages are prepended
  useEffect(() => {
    if (messages.length === 0) {
      prevFirstIdRef.current = null;
      return;
    }
    const firstId = messages[0].local_id;
    if (prevFirstIdRef.current !== null && firstId !== prevFirstIdRef.current) {
      const oldFirstIndex = messages.findIndex((m) => m.local_id === prevFirstIdRef.current);
      if (oldFirstIndex > 0) {
        virtualizer.scrollToIndex(oldFirstIndex, { align: 'start', behavior: 'auto' });
      }
    }
    prevFirstIdRef.current = firstId;
  }, [messages]);

  // Scroll to highlighted message
  useEffect(() => {
    if (highlightedMessageId != null) {
      const idx = messages.findIndex((m) => m.local_id === highlightedMessageId);
      if (idx >= 0) {
        virtualizer.scrollToIndex(idx, { align: 'center', behavior: 'smooth' });
      }
    }
  }, [highlightedMessageId, messages]);

  // Auto-load on scroll
  useEffect(() => {
    const el = parentRef.current;
    if (!el) return;

    const handleScroll = () => {
      const { scrollTop, scrollHeight, clientHeight } = el;

      if (scrollTop < LOAD_THRESHOLD && hasMoreBefore && !isLoadingBefore) {
        setIsLoadingBefore(true);
        onLoadMoreBefore?.().finally(() => setIsLoadingBefore(false));
      }

      if (scrollHeight - scrollTop - clientHeight < LOAD_THRESHOLD && hasMoreAfter && !isLoadingAfter) {
        setIsLoadingAfter(true);
        onLoadMoreAfter?.().finally(() => setIsLoadingAfter(false));
      }
    };

    el.addEventListener('scroll', handleScroll, { passive: true });
    return () => el.removeEventListener('scroll', handleScroll);
  }, [hasMoreBefore, hasMoreAfter, isLoadingBefore, isLoadingAfter, onLoadMoreBefore, onLoadMoreAfter]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5, delay: 0.1 }}
      className="flex-1 flex flex-col min-h-0 bg-zinc-50 dark:bg-[#050505] font-mono transition-colors duration-300"
    >
      <div
        ref={parentRef}
        className="flex-1 min-h-0 overflow-y-auto p-6 bg-zinc-50 dark:bg-[#050505]"
      >
        {isLoadingBefore && (
          <div className="flex justify-center pb-3">
            <span className="text-[10px] uppercase tracking-widest text-zinc-400 dark:text-zinc-600">加载中…</span>
          </div>
        )}
        <div
          style={{
            height: `${virtualizer.getTotalSize()}px`,
            width: '100%',
            position: 'relative',
          }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const msg = messages[virtualRow.index];
            const isHighlighted = msg.local_id === highlightedMessageId;
            const isSend = msg.is_send;
            return (
              <div
                key={msg.local_id}
                ref={(el) => el && virtualizer.measureElement(el)}
                data-index={virtualRow.index}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualRow.start}px)`,
                  paddingBottom: 12,
                }}
              >
                <div
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
              </div>
            );
          })}
        </div>
        {isLoadingAfter && (
          <div className="flex justify-center pt-3">
            <span className="text-[10px] uppercase tracking-widest text-zinc-400 dark:text-zinc-600">加载中…</span>
          </div>
        )}
      </div>
    </motion.div>
  );
}
