'use client';

import { useEffect, useState } from 'react';

interface ServiceState {
  asr: 'loading' | 'ok' | 'fail';
  llm: 'loading' | 'ok' | 'fail';
  tts: 'loading' | 'ok' | 'fail';
}

const LABELS: Record<keyof ServiceState, string> = {
  asr: 'ASR',
  llm: 'LLM',
  tts: 'TTS',
};

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="6.5" stroke="var(--success)" strokeWidth="1" />
      <path d="M4 7.2L6 9.2L10 5" stroke="var(--success)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function CrossIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="6.5" stroke="var(--error)" strokeWidth="1" />
      <path d="M5 5L9 9M9 5L5 9" stroke="var(--error)" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function SpinnerIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="animate-spin">
      <circle cx="7" cy="7" r="6" stroke="var(--border-color)" strokeWidth="1.2" />
      <path d="M7 1A6 6 0 0 1 13 7" stroke="var(--accent)" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

export default function ServiceStatus() {
  const [services, setServices] = useState<ServiceState>({
    asr: 'loading',
    llm: 'loading',
    tts: 'loading',
  });

  useEffect(() => {
    let mounted = true;

    async function check() {
      try {
        const resp = await fetch('/readyz');
        if (!mounted) return;
        if (!resp.ok) {
          setServices({ asr: 'fail', llm: 'fail', tts: 'fail' });
          return;
        }
        const data = await resp.json();
        const checks = data.checks || {};
        setServices({
          asr: checks.asr === 'ok' ? 'ok' : 'fail',
          llm: checks.llm === 'ok' ? 'ok' : 'fail',
          tts: checks.tts === 'ok' ? 'ok' : 'fail',
        });
      } catch {
        if (mounted) setServices({ asr: 'fail', llm: 'fail', tts: 'fail' });
      }
    }

    check();
    const interval = setInterval(check, 30_000);
    return () => { mounted = false; clearInterval(interval); };
  }, []);

  const allOk = services.asr === 'ok' && services.llm === 'ok' && services.tts === 'ok';
  const anyLoading = services.asr === 'loading' || services.llm === 'loading' || services.tts === 'loading';

  return (
    <div
      className="flex items-center gap-3 px-3 py-1.5 rounded-lg text-xs"
      style={{
        backgroundColor: 'var(--background-tertiary)',
        border: '1px solid var(--border-color)',
      }}
    >
      {(Object.keys(LABELS) as (keyof ServiceState)[]).map((key) => (
        <div key={key} className="flex items-center gap-1">
          {services[key] === 'loading' ? <SpinnerIcon /> : services[key] === 'ok' ? <CheckIcon /> : <CrossIcon />}
          <span style={{ color: services[key] === 'fail' ? 'var(--error)' : 'var(--text-muted)' }}>
            {LABELS[key]}
          </span>
        </div>
      ))}
      {!anyLoading && (
        <span style={{ color: allOk ? 'var(--success)' : 'var(--error)', marginLeft: 2 }}>
          {allOk ? 'Ready' : 'Error'}
        </span>
      )}
    </div>
  );
}
