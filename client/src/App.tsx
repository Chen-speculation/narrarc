import { useState, useEffect, useCallback } from 'react';
import { motion } from 'motion/react';
import { Sidebar } from './components/Sidebar';
import { MainArea } from './components/MainArea';
import { ImportModal } from './components/ImportModal';
import { TitleBar } from './components/TitleBar';
import { Session, QueryResponse, Message } from './types';
import * as api from './api';

export default function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);
  const [sessionMessages, setSessionMessages] = useState<Message[]>([]);
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null);
  const [highlightedMessageId, setHighlightedMessageId] = useState<number | null>(null);
  const [isDarkMode, setIsDarkMode] = useState(true);
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);

  useEffect(() => {
    api.listSessions().then(setSessions).catch(console.error);
  }, []);

  const pollBuildStatus = useCallback((talkerId: string): (() => void) => {
    const intervalId = setInterval(async () => {
      try {
        const list = await api.listSessions();
        setSessions(list);
        const found = list.find((s) => s.talker_id === talkerId);
        // #region agent log
        fetch('http://127.0.0.1:7251/ingest/6d4754d5-f830-4574-ae7e-cc5bdfa1e60f',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'75fb2f'},body:JSON.stringify({sessionId:'75fb2f',location:'App.tsx:pollBuildStatus',message:'poll tick',data:{listLen:list.length,talkerId,found:!!found,foundStatus:found?.build_status,foundProgress:!!found?.build_progress},timestamp:Date.now(),hypothesisId:'H2'})}).catch(()=>{});
        // #endregion
        if (found) {
          setActiveSession((prev) => (prev?.talker_id === talkerId ? found : prev));
        }
        if (found?.build_status === 'complete') {
          clearInterval(intervalId);
          const messages = await api.getMessages(talkerId);
          setSessionMessages(messages);
        }
      } catch (e) {
        console.error(e);
      }
    }, 3000);
    return () => clearInterval(intervalId);
  }, []);

  // 当当前选中的会话尚未构建完成时，持续轮询会话列表并更新 build_status，避免后端已完成但前端未刷新
  useEffect(() => {
    if (!activeSession || activeSession.build_status === 'complete') return;
    // #region agent log
    fetch('http://127.0.0.1:7251/ingest/6d4754d5-f830-4574-ae7e-cc5bdfa1e60f',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'75fb2f'},body:JSON.stringify({sessionId:'75fb2f',location:'App.tsx:useEffect poll',message:'starting poll',data:{talkerId:activeSession.talker_id,status:activeSession.build_status},timestamp:Date.now(),hypothesisId:'H2'})}).catch(()=>{});
    // #endregion
    const cleanup = pollBuildStatus(activeSession.talker_id);
    return cleanup;
  }, [activeSession?.talker_id, activeSession?.build_status, pollBuildStatus]);

  const handleSelectSession = (session: Session) => {
    setActiveSession(session);
    setQueryResult(null);
    setSessionMessages([]);
    if (session.build_status === 'complete') {
      api.getMessages(session.talker_id).then(setSessionMessages).catch(console.error);
    }
  };

  const handleQueryComplete = (result: QueryResponse) => {
    setQueryResult(result);
  };

  const handleImport = (newSession: Session) => {
    setSessions((prev) => [newSession, ...prev]);
    setActiveSession(newSession);
    setSessionMessages([]);
    pollBuildStatus(newSession.talker_id);
  };

  const handleDeleteSession = async (session: Session) => {
    if (!window.confirm(`确定要删除会话「${session.display_name}」吗？此操作不可恢复。`)) return;
    try {
      await api.deleteSession(session.talker_id);
      setSessions((prev) => prev.filter((s) => s.talker_id !== session.talker_id));
      if (activeSession?.talker_id === session.talker_id) {
        setActiveSession(null);
        setSessionMessages([]);
        setQueryResult(null);
      }
    } catch (e) {
      console.error(e);
      window.alert('删除失败：' + (e instanceof Error ? e.message : String(e)));
    }
  };

  return (
    <div className={`${isDarkMode ? 'dark' : ''}`}>
      <motion.div
        className="flex h-screen flex-col bg-zinc-50 dark:bg-[#050505] text-zinc-900 dark:text-zinc-300 font-sans selection:bg-indigo-500/30 transition-colors duration-300"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.25, 0.1, 0.25, 1] }}
      >
        <TitleBar />
        <div className="flex min-h-0 flex-1">
          <Sidebar
            sessions={sessions}
            activeSession={activeSession}
            onSelectSession={handleSelectSession}
            onDeleteSession={handleDeleteSession}
            isDarkMode={isDarkMode}
            toggleTheme={() => setIsDarkMode(!isDarkMode)}
            onOpenImport={() => setIsImportModalOpen(true)}
          />
          <MainArea
            activeSession={activeSession}
            sessionMessages={sessionMessages}
            queryResult={queryResult}
            onQueryComplete={handleQueryComplete}
            highlightedMessageId={highlightedMessageId}
            onHighlightMessage={setHighlightedMessageId}
          />
          <ImportModal
            isOpen={isImportModalOpen}
            onClose={() => setIsImportModalOpen(false)}
            onImport={handleImport}
          />
        </div>
      </motion.div>
    </div>
  );
}
