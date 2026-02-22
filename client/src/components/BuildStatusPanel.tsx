import React from 'react';
import { Session } from '../types';
import { Loader2, Clock, CheckCircle2, Circle } from 'lucide-react';

const PIPELINE_STAGES = [
  { id: 'layer1', label: 'Layer 1', desc: '消息聚合与话题分类' },
  { id: 'layer1.5', label: 'Layer 1.5', desc: '元数据与异常锚点' },
  { id: 'layer2', label: 'Layer 2', desc: '语义链路' },
] as const;

/** Parse "已分类 8/27 个 burst" -> { current: 8, total: 27 }, or "已嵌入 39 个节点" -> { current: 39, total: null } */
function parseProgressDetail(detail: string): { current: number; total: number | null; label?: string } | null {
  const burstMatch = detail.match(/已分类\s*(\d+)\s*\/\s*(\d+)\s*个\s*burst/i)
    || detail.match(/已分类\s*(\d+)\s*\/\s*(\d+)/);
  if (burstMatch) {
    return { current: parseInt(burstMatch[1], 10), total: parseInt(burstMatch[2], 10), label: 'burst' };
  }
  const singleMatch = detail.match(/(?:已)?(?:获取|聚合为|嵌入|找到|重排后保留|创建)\s*(\d+)/)
    || detail.match(/(\d+)\s*个?(?:节点|候选对|对|条)/);
  if (singleMatch) {
    return { current: parseInt(singleMatch[1], 10), total: null };
  }
  return null;
}

interface BuildStatusPanelProps {
  session: Session;
}

export function BuildStatusPanel({ session }: BuildStatusPanelProps) {
  const isPending = session.build_status === 'pending';
  const isInProgress = session.build_status === 'in_progress';
  const progress = session.build_progress;

  const currentStageId = progress?.stage ?? null;
  const progressParsed = progress?.detail ? parseProgressDetail(progress.detail) : null;

  if (isPending) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center min-h-[280px] px-6">
        <div className="flex flex-col items-center text-center max-w-sm">
          <div className="w-14 h-14 rounded-full bg-zinc-100 dark:bg-zinc-800/80 flex items-center justify-center mb-5 border border-zinc-200 dark:border-white/10">
            <Clock className="w-7 h-7 text-zinc-500 dark:text-zinc-400" />
          </div>
          <p className="font-title text-sm font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-widest mb-2">
            等待构建
          </p>
          <p className="text-[11px] text-zinc-500 dark:text-zinc-500 leading-relaxed">
            该会话尚未开始初始化。导入数据后，构建将自动开始，届时此处会显示进度。
          </p>
        </div>
      </div>
    );
  }

  if (isInProgress) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center min-h-[280px] px-6">
        <div className="flex flex-col items-center w-full max-w-md">
          {/* 转圈动画 */}
          <div className="w-16 h-16 rounded-full border-2 border-indigo-200 dark:border-indigo-500/30 border-t-indigo-500 dark:border-t-indigo-400 flex items-center justify-center mb-6 animate-spin">
            <span className="sr-only">加载中</span>
          </div>
          <p className="font-title text-sm font-bold text-zinc-800 dark:text-zinc-200 uppercase tracking-widest mb-1">
            正在构建索引
          </p>
          <p className="text-[10px] text-zinc-500 dark:text-zinc-500 mb-6">
            初始化完成后将在此展示原始对话数据
          </p>

          {/* 流程步骤 */}
          <div className="w-full space-y-0 rounded-lg border border-zinc-200 dark:border-white/10 bg-zinc-50/50 dark:bg-black/20 overflow-hidden">
            {PIPELINE_STAGES.map((stage, index) => {
              const isActive = currentStageId === stage.id;
              const isDone = currentStageId
                ? PIPELINE_STAGES.findIndex((s) => s.id === currentStageId) > index
                : false;

              return (
                <div
                  key={stage.id}
                  className={`flex items-start gap-3 px-4 py-3 border-b border-zinc-200/80 dark:border-white/5 last:border-b-0 transition-colors duration-200 ${
                    isActive ? 'bg-indigo-50/80 dark:bg-indigo-500/10' : isDone ? 'bg-emerald-50/50 dark:bg-emerald-500/5' : ''
                  }`}
                >
                  <div className="flex-shrink-0 mt-0.5">
                    {isDone ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-500 dark:text-emerald-400" />
                    ) : isActive ? (
                      <Loader2 className="w-4 h-4 text-indigo-500 dark:text-indigo-400 animate-spin" />
                    ) : (
                      <Circle className="w-4 h-4 text-zinc-300 dark:text-zinc-600" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-xs font-medium ${isActive ? 'text-indigo-700 dark:text-indigo-300' : isDone ? 'text-zinc-600 dark:text-zinc-400' : 'text-zinc-500 dark:text-zinc-500'}`}>
                      {stage.label}：{stage.desc}
                    </p>
                    {isActive && progress?.detail && (
                      <p className="mt-1 text-[11px] text-zinc-600 dark:text-zinc-400 truncate" title={progress.detail}>
                        {progressParsed?.total != null ? (
                          <>
                            <span className="font-medium text-indigo-600 dark:text-indigo-400">
                              {progressParsed.current} / {progressParsed.total}
                            </span>
                            <span className="text-zinc-500 dark:text-zinc-500 ml-1">
                              {progressParsed.label === 'burst' ? ' 个 burst 已处理' : ''}
                            </span>
                          </>
                        ) : (
                          progress.detail
                        )}
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* 底部实时文案 */}
          {progress?.detail && (
            <p className="mt-4 text-[10px] text-zinc-500 dark:text-zinc-500 text-center max-w-sm truncate w-full" title={progress.detail}>
              {progress.detail}
            </p>
          )}
        </div>
      </div>
    );
  }

  return null;
}
