import React, { useState, useEffect } from 'react';
import { X, Settings, Save, RotateCcw } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import type { BackendConfig, ConfigOverrides } from '../types';
import * as api from '../api';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

function mergeForForm(base: BackendConfig, overrides: ConfigOverrides | null): BackendConfig {
  if (!overrides) return base;
  return {
    llm: { ...base.llm, ...(overrides.llm || {}) },
    embedding: { ...base.embedding, ...(overrides.embedding || {}) },
    reranker: { ...base.reranker, ...(overrides.reranker || {}) },
  };
}

function toOverrides(form: BackendConfig, base: BackendConfig): ConfigOverrides | null {
  const o: ConfigOverrides = {};
  const diff = (a: Record<string, unknown>, b: Record<string, unknown>) => {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(a)) {
      const av = a[k];
      const bv = b[k];
      if (av !== bv) out[k] = av;
    }
    return Object.keys(out).length ? out : undefined;
  };
  const llmDiff = diff(form.llm as Record<string, unknown>, base.llm as Record<string, unknown>);
  if (llmDiff) o.llm = llmDiff as BackendConfig['llm'];
  const embDiff = diff(form.embedding as Record<string, unknown>, base.embedding as Record<string, unknown>);
  if (embDiff) o.embedding = embDiff as BackendConfig['embedding'];
  const rerDiff = diff(form.reranker as Record<string, unknown>, base.reranker as Record<string, unknown>);
  if (rerDiff) o.reranker = rerDiff as BackendConfig['reranker'];
  return Object.keys(o).length ? o : null;
}

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const [baseConfig, setBaseConfig] = useState<BackendConfig | null>(null);
  const [form, setForm] = useState<BackendConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    setError(null);
    setLoading(true);
    api
      .getConfig()
      .then((cfg) => {
        setBaseConfig(cfg);
        const overrides = api.getConfigOverrides();
        setForm(mergeForForm(cfg, overrides));
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [isOpen]);

  const handleSave = () => {
    if (!form || !baseConfig) return;
    setSaving(true);
    setError(null);
    try {
      const overrides = toOverrides(form, baseConfig);
      const hasAny = overrides.llm || overrides.embedding || overrides.reranker;
      api.setConfigOverrides(hasAny ? overrides : null);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (!baseConfig) return;
    setForm({ ...baseConfig });
    api.setConfigOverrides(null);
  };

  const update = (section: keyof BackendConfig, key: string, value: string | number) => {
    setForm((prev) => {
      if (!prev) return prev;
      const next = { ...prev, [section]: { ...prev[section], [key]: value } };
      return next;
    });
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
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
          className="relative w-full max-w-2xl max-h-[90vh] overflow-hidden bg-white dark:bg-[#0a0a0a] rounded-2xl shadow-2xl border border-zinc-200 dark:border-white/10 font-mono flex flex-col"
        >
          <div className="p-6 border-b border-zinc-200 dark:border-white/10 flex justify-between items-center flex-shrink-0">
            <h3 className="font-title text-lg font-bold text-zinc-900 dark:text-white tracking-widest uppercase flex items-center gap-2">
              <Settings className="w-5 h-5 text-indigo-500" />
              后端配置
            </h3>
            <button
              onClick={onClose}
              className="p-2 hover:bg-zinc-100 dark:hover:bg-white/10 rounded-lg transition-colors text-zinc-500"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            {loading && (
              <p className="text-sm text-zinc-500">加载配置中…</p>
            )}
            {error && (
              <div className="text-amber-600 dark:text-amber-500 text-sm bg-amber-50 dark:bg-amber-500/10 p-3 rounded-lg border border-amber-200 dark:border-amber-500/20">
                {error}
              </div>
            )}
            {form && (
              <>
                <section>
                  <h4 className="text-xs font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-widest mb-3">LLM（对话/推理）</h4>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">provider</label>
                      <input
                        value={form.llm.provider}
                        onChange={(e) => update('llm', 'provider', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">model</label>
                      <input
                        value={form.llm.model}
                        onChange={(e) => update('llm', 'model', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">api_key</label>
                      <input
                        type="password"
                        value={form.llm.api_key}
                        onChange={(e) => update('llm', 'api_key', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                        placeholder="sk-..."
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">base_url</label>
                      <input
                        value={form.llm.base_url}
                        onChange={(e) => update('llm', 'base_url', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                        placeholder="https://api.example.com/v1"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">max_workers</label>
                      <input
                        type="number"
                        value={form.llm.max_workers}
                        onChange={(e) => update('llm', 'max_workers', parseInt(e.target.value, 10) || 8)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                      />
                    </div>
                  </div>
                </section>

                <section>
                  <h4 className="text-xs font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-widest mb-3">Embedding（向量）</h4>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">provider</label>
                      <input
                        value={form.embedding.provider}
                        onChange={(e) => update('embedding', 'provider', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">model</label>
                      <input
                        value={form.embedding.model}
                        onChange={(e) => update('embedding', 'model', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">api_key</label>
                      <input
                        type="password"
                        value={form.embedding.api_key}
                        onChange={(e) => update('embedding', 'api_key', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">base_url</label>
                      <input
                        value={form.embedding.base_url}
                        onChange={(e) => update('embedding', 'base_url', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                      />
                    </div>
                  </div>
                </section>

                <section>
                  <h4 className="text-xs font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-widest mb-3">Reranker（重排序）</h4>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">model</label>
                      <input
                        value={form.reranker.model}
                        onChange={(e) => update('reranker', 'model', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">api_key</label>
                      <input
                        type="password"
                        value={form.reranker.api_key}
                        onChange={(e) => update('reranker', 'api_key', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                      />
                    </div>
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">base_url</label>
                      <input
                        value={form.reranker.base_url}
                        onChange={(e) => update('reranker', 'base_url', e.target.value)}
                        className="w-full px-3 py-2 text-sm bg-zinc-50 dark:bg-white/5 border border-zinc-200 dark:border-white/10 rounded-lg focus:ring-2 focus:ring-indigo-500/50"
                      />
                    </div>
                  </div>
                </section>

                <p className="text-xs text-zinc-500">
                  此处配置会覆盖 backend/config.yml 中的对应项，用于查询与构建。保存后立即生效。
                </p>
              </>
            )}
          </div>

          <div className="p-6 border-t border-zinc-200 dark:border-white/10 bg-zinc-50 dark:bg-[#050505] flex justify-between gap-3 flex-shrink-0">
            <button
              onClick={handleReset}
              disabled={!form || loading}
              className="px-4 py-2 text-sm font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors flex items-center gap-2 disabled:opacity-50"
            >
              <RotateCcw className="w-4 h-4" />
              恢复文件默认
            </button>
            <div className="flex gap-3">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm font-medium text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={!form || loading || saving}
                className="px-6 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg shadow-lg shadow-indigo-500/20 transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                <Save className="w-4 h-4" />
                {saving ? '保存中…' : '保存并覆盖'}
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
}
