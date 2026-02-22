import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { invoke } from '@tauri-apps/api/core';
import App from './App.tsx';
import './index.css';

/** Forward uncaught frontend errors to Tauri terminal (stderr) so they appear in `tauri dev` output. */
function setupErrorForwarding() {
  const sendToTerminal = (msg: string) => {
    invoke('log_frontend_error', { message: msg }).catch(() => {});
  };

  window.onerror = (message, source, lineno, colno, error) => {
    const detail = error?.stack ?? `${source}:${lineno}:${colno}`;
    sendToTerminal(`Uncaught: ${message}\n  at ${detail}`);
  };

  window.addEventListener('unhandledrejection', (ev) => {
    const msg = ev.reason instanceof Error ? ev.reason.stack ?? ev.reason.message : String(ev.reason);
    sendToTerminal(`Unhandled rejection: ${msg}`);
  });
}

setupErrorForwarding();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
