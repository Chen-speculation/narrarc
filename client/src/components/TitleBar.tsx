import { getCurrentWindow } from '@tauri-apps/api/window';
import { Terminal, Minus, Square, X } from 'lucide-react';

const isTauri = typeof window !== 'undefined' && !! (window as unknown as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;

function handleMinimize() {
  if (!isTauri) return;
  getCurrentWindow().minimize();
}

function handleToggleMaximize() {
  if (!isTauri) return;
  getCurrentWindow().toggleMaximize();
}

function handleClose() {
  if (!isTauri) return;
  getCurrentWindow().close();
}

export function TitleBar() {
  if (!isTauri) return null;

  return (
    <div className="titlebar flex h-10 flex-shrink-0 items-center justify-between border-b border-zinc-200 bg-white dark:border-white/10 dark:bg-[#0a0a0a] select-none">
      {/* 可拖拽区域：Logo + 标题 */}
      <div
        className="flex flex-1 cursor-default items-center gap-2 pl-3"
        data-tauri-drag-region
      >
        <Terminal className="h-4 w-4 text-indigo-600 dark:text-indigo-400" aria-hidden />
        <span className="font-title text-sm font-medium text-zinc-700 dark:text-zinc-300">
          叙事镜鉴
        </span>
      </div>

      {/* 窗口控制按钮：最小化、最大化、关闭（不设为拖拽区，便于点击） */}
      <div className="flex items-center">
        <button
          type="button"
          onClick={handleMinimize}
          className="flex h-8 w-10 items-center justify-center text-zinc-600 hover:bg-zinc-200 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-zinc-100"
          aria-label="最小化"
        >
          <Minus className="h-3.5 w-3.5" strokeWidth={2.5} />
        </button>
        <button
          type="button"
          onClick={handleToggleMaximize}
          className="flex h-8 w-10 items-center justify-center text-zinc-600 hover:bg-zinc-200 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-white/10 dark:hover:text-zinc-100"
          aria-label="最大化"
        >
          <Square className="h-3 w-3" strokeWidth={2} />
        </button>
        <button
          type="button"
          onClick={handleClose}
          className="titlebar-close flex h-8 w-10 items-center justify-center text-zinc-600 hover:bg-[#ff5f57] hover:text-white dark:text-zinc-400 dark:hover:bg-[#ff5f57] dark:hover:text-white"
          aria-label="关闭"
        >
          <X className="h-3.5 w-3.5" strokeWidth={2.5} />
        </button>
      </div>
    </div>
  );
}
