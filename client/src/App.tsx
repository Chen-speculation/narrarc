import { useState, useEffect, useCallback } from 'react';
import { Sidebar } from './components/Sidebar';
import { MainArea } from './components/MainArea';
import { ImportModal } from './components/ImportModal';
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

  const pollBuildStatus = useCallback((talkerId: string) => {
    const interval = setInterval(async () => {
      try {
        const list = await api.listSessions();
        setSessions(list);
        const found = list.find((s) => s.talker_id === talkerId);
        if (found) {
          setActiveSession((prev) => (prev?.talker_id === talkerId ? found : prev));
        }
        if (found?.build_status === 'complete') {
          clearInterval(interval);
          const messages = await api.getMessages(talkerId);
          setSessionMessages(messages);
        }
      } catch (e) {
        console.error(e);
      }
    }, 3000);
  }, []);

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
      <div className="flex h-screen bg-zinc-50 dark:bg-[#050505] text-zinc-900 dark:text-zinc-300 font-sans selection:bg-indigo-500/30 transition-colors duration-300">
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
    </div>
  );
}
