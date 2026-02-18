'use client';

import { useEffect } from 'react';
import { useStore } from '../store/useStore';

const AUTO_DISMISS_MS = 5000;

export default function Toast() {
  const { connectionError, setConnectionError } = useStore();

  useEffect(() => {
    if (!connectionError) return;
    const timer = setTimeout(() => setConnectionError(null), AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [connectionError, setConnectionError]);

  if (!connectionError) return null;

  return (
    <div
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 rounded-xl px-5 py-3 shadow-lg text-white text-sm"
      style={{ backgroundColor: '#c45c5c', maxWidth: '90vw' }}
      role="alert"
    >
      <span>⚠️ {connectionError}</span>
      <button
        onClick={() => setConnectionError(null)}
        className="ml-1 opacity-80 hover:opacity-100 transition-opacity font-bold"
        aria-label="關閉通知"
      >
        ✕
      </button>
    </div>
  );
}
