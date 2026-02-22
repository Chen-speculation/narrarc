import React, { useState } from 'react';
import { open } from '@tauri-apps/plugin-dialog';
import { X, Upload, FileText, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { Session } from '../types';
import * as api from '../api';

interface ImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  onImport: (newSession: Session) => void;
}

export function ImportModal({ isOpen, onClose, onImport }: ImportModalProps) {
  const [error, setError] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);

  const handleSubmit = async () => {
    setError(null);
    setIsProcessing(true);

    try {
      const filePath = await open({
        filters: [{ name: 'JSON', extensions: ['json'] }],
      });

      if (filePath === null) {
        setIsProcessing(false);
        return;
      }

      const session = await api.importData(filePath);
      await api.triggerBuild(session.talker_id);
      onImport(session);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="relative w-full max-w-lg bg-white dark:bg-[#0a0a0a] rounded-2xl shadow-2xl border border-zinc-200 dark:border-white/10 overflow-hidden font-mono"
          >
            <div className="p-6 border-b border-zinc-200 dark:border-white/10 flex justify-between items-center">
              <h3 className="font-title text-lg font-bold text-zinc-900 dark:text-white tracking-widest uppercase flex items-center gap-2">
                <Upload className="w-5 h-5 text-indigo-500" />
                导入数据
              </h3>
              <button
                onClick={onClose}
                className="p-2 hover:bg-zinc-100 dark:hover:bg-white/10 rounded-lg transition-colors text-zinc-500"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-6">
              <div
                className="border-2 border-dashed rounded-xl p-8 text-center transition-all border-zinc-300 dark:border-white/10 hover:border-indigo-400 dark:hover:border-indigo-500/50 cursor-pointer"
                onClick={handleSubmit}
              >
                <div className="w-12 h-12 rounded-full bg-zinc-100 dark:bg-white/5 flex items-center justify-center mx-auto mb-3">
                  <FileText className="w-6 h-6 text-zinc-400" />
                </div>
                <p className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  点击选择 JSON 文件
                </p>
                <p className="text-xs text-zinc-500 mt-1">选择微信聊天导出 JSON 文件</p>
              </div>

              {error && (
                <div className="flex items-center gap-2 text-amber-600 dark:text-amber-500 text-sm bg-amber-50 dark:bg-amber-500/10 p-3 rounded-lg border border-amber-200 dark:border-amber-500/20">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  {error}
                </div>
              )}
            </div>

            <div className="p-6 border-t border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-[#050505] flex justify-end gap-3">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors"
              >
                CANCEL
              </button>
              <button
                onClick={handleSubmit}
                disabled={isProcessing}
                className="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg shadow-lg shadow-indigo-500/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {isProcessing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    PROCESSING...
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="w-4 h-4" />
                    选择文件并导入
                  </>
                )}
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
