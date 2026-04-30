'use client';

import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Activity, Pause, Play, Trash2, Copy, AlertCircle, CheckCircle2, Mic, Brain, Wrench, ShoppingCart } from 'lucide-react';

// ───────────────────────────── 型別 ─────────────────────────────

type EventType = 'asr_done' | 'llm_raw' | 'tool_exec' | 'session_done';

interface PipelineEvent {
  type: EventType;
  session_id: string;
  timestamp: number;
  data: Record<string, unknown>;
}

// ───────────────────────────── 常數 ─────────────────────────────

const BRAND = {
  primary:  '#729DAD',
  light:    '#8fb3c0',
  dark:     '#5a8494',
  success:  '#4a9d68',
  warning:  '#c49a30',
  error:    '#c45c5c',
  bg:       '#f4f7f8',
  cardBg:   '#ffffff',
  border:   '#d0dce0',
  textMain: '#2c3e42',
  textSub:  '#8a9a9f',
} as const;

const EVENT_META: Record<EventType, { label: string; icon: typeof Mic; color: string }> = {
  asr_done:     { label: 'ASR',  icon: Mic,          color: BRAND.warning },
  llm_raw:      { label: 'LLM',  icon: Brain,        color: BRAND.dark },
  tool_exec:    { label: 'Tool', icon: Wrench,       color: BRAND.primary },
  session_done: { label: 'Cart', icon: ShoppingCart, color: BRAND.success },
};

const MAX_EVENTS = 500; // ring buffer 上限，避免長時間累積爆記憶體

// ───────────────────────────── 工具函式 ─────────────────────────

function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}

function shortSessionId(sid: string): string {
  return sid ? sid.slice(0, 8) : '(unknown)';
}

/** 把 session 的事件序列轉成 benchmark scenario JSON 模板（expected 留空人工填）。 */
function eventsToScenario(events: PipelineEvent[]): Record<string, unknown> {
  const messages: { role: string; content: string }[] = [];
  for (const evt of events) {
    if (evt.type === 'asr_done') {
      const text = (evt.data.text as string) || '';
      if (text) messages.push({ role: 'user', content: text });
    } else if (evt.type === 'session_done') {
      const text = (evt.data.assistant_text as string) || '';
      if (text) messages.push({ role: 'assistant', content: text });
    }
  }
  return {
    id: `replay_${events[0]?.session_id?.slice(0, 8) || 'unknown'}`,
    description: '從 monitor 即時 session 轉換（請補 description）',
    category: 'replay',
    messages,
    expected_tools: [],
    expected_args: [],
    expected_response_contains: [],
    expected_behavior: '請補 expected behavior 描述',
  };
}

// ───────────────────────────── 子元件 ─────────────────────────────

function EventRow({ event }: { event: PipelineEvent }) {
  const meta = EVENT_META[event.type];
  const Icon = meta.icon;

  // highlight：tool_exec ok:false 紅底
  const isFailedTool = event.type === 'tool_exec' && event.data.ok === false;
  const bgColor = isFailedTool ? '#fcebeb' : 'transparent';
  const borderLeft = isFailedTool ? `3px solid ${BRAND.error}` : `3px solid ${meta.color}`;

  // 渲染主要訊息
  let summary: string;
  if (event.type === 'asr_done') {
    const text = (event.data.text as string) || '(空)';
    const latency = event.data.latency_ms as number | undefined;
    summary = `${text}${latency ? `  (${latency}ms)` : ''}`;
  } else if (event.type === 'llm_raw') {
    const raw = (event.data.raw_text as string) || '';
    summary = raw.length > 120 ? raw.slice(0, 120) + '…' : raw;
  } else if (event.type === 'tool_exec') {
    const tool = event.data.tool as string;
    const input = event.data.input as Record<string, unknown>;
    const ok = event.data.ok as boolean;
    const message = event.data.message as string | undefined;
    const inputStr = Object.entries(input).map(([k, v]) => `${k}=${v}`).join(' ');
    summary = `${ok ? '✓' : '✗'} ${tool}(${inputStr})${message ? ` → ${message}` : ''}`;
  } else if (event.type === 'session_done') {
    const cart = (event.data.cart_summary as string[]) || [];
    const total = event.data.total_price as number;
    summary = `${cart.length} 項，$${total} — "${event.data.assistant_text || ''}"`;
  } else {
    summary = JSON.stringify(event.data);
  }

  return (
    <div
      className="flex items-start gap-2 px-3 py-2 rounded-lg text-sm"
      style={{ backgroundColor: bgColor, borderLeft }}
    >
      <Icon size={14} color={isFailedTool ? BRAND.error : meta.color} className="mt-0.5 shrink-0" />
      <span className="font-mono text-xs shrink-0" style={{ color: BRAND.textSub, minWidth: 70 }}>
        {formatTime(event.timestamp)}
      </span>
      <span className="font-semibold shrink-0" style={{ color: meta.color, minWidth: 36 }}>
        {meta.label}
      </span>
      <span className="break-all" style={{ color: BRAND.textMain }}>
        {summary}
      </span>
    </div>
  );
}

function SessionCard({
  sessionId,
  events,
  onCopy,
}: {
  sessionId: string;
  events: PipelineEvent[];
  onCopy: () => void;
}) {
  const hasFailedTool = events.some((e) => e.type === 'tool_exec' && e.data.ok === false);

  return (
    <div
      className="rounded-2xl p-4 mb-3"
      style={{
        backgroundColor: BRAND.cardBg,
        border: `1px solid ${hasFailedTool ? BRAND.error : BRAND.border}`,
        boxShadow: '0 2px 8px rgba(114,157,173,0.08)',
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          {hasFailedTool ? (
            <AlertCircle size={16} color={BRAND.error} />
          ) : (
            <CheckCircle2 size={16} color={BRAND.success} />
          )}
          <span className="font-mono text-sm font-semibold" style={{ color: BRAND.textMain }}>
            {shortSessionId(sessionId)}
          </span>
          <span className="text-xs" style={{ color: BRAND.textSub }}>
            {events.length} 事件
          </span>
        </div>
        <button
          onClick={onCopy}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded-md transition-colors hover:bg-gray-100"
          style={{ color: BRAND.primary }}
          title="複製成 benchmark scenario JSON"
        >
          <Copy size={12} />
          <span>scenario</span>
        </button>
      </div>
      <div className="flex flex-col gap-1">
        {events.map((evt, i) => (
          <EventRow key={`${evt.timestamp}-${i}`} event={evt} />
        ))}
      </div>
    </div>
  );
}

// ───────────────────────────── 主元件 ─────────────────────────────

export default function AdminMonitorPage() {
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const [connected, setConnected] = useState(false);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  // 訂閱 SSE
  useEffect(() => {
    const eventSource = new EventSource('/admin/monitor/stream');

    eventSource.addEventListener('open', () => setConnected(true));
    eventSource.addEventListener('error', () => setConnected(false));
    eventSource.addEventListener('pipeline', (e: MessageEvent<string>) => {
      if (pausedRef.current) return;
      try {
        const evt = JSON.parse(e.data) as PipelineEvent;
        setEvents((prev) => {
          const next = [...prev, evt];
          // ring buffer：超過 MAX_EVENTS 時砍最舊 20%（避免每次都 slice）
          if (next.length > MAX_EVENTS) {
            return next.slice(next.length - Math.floor(MAX_EVENTS * 0.8));
          }
          return next;
        });
      } catch (err) {
        console.error('parse pipeline event failed:', err);
      }
    });

    return () => {
      eventSource.close();
      setConnected(false);
    };
  }, []);

  // 按 session 分組（保持事件時序）
  const grouped = useMemo(() => {
    const map = new Map<string, PipelineEvent[]>();
    for (const evt of events) {
      const list = map.get(evt.session_id) ?? [];
      list.push(evt);
      map.set(evt.session_id, list);
    }
    // 反向排序：最新 session 在最上
    return Array.from(map.entries()).reverse();
  }, [events]);

  const handleCopyScenario = useCallback((sessionEvents: PipelineEvent[]) => {
    const scenario = eventsToScenario(sessionEvents);
    navigator.clipboard.writeText(JSON.stringify(scenario, null, 2));
  }, []);

  return (
    <div className="min-h-screen" style={{ backgroundColor: BRAND.bg }}>
      <header
        className="sticky z-20 px-4 pt-4 pb-3"
        style={{ top: '52px', backgroundColor: BRAND.bg }}
      >
        <div
          className="rounded-2xl p-4"
          style={{
            background: 'linear-gradient(135deg, #ffffff 0%, #edf3f5 100%)',
            border: `1px solid ${BRAND.border}`,
            boxShadow: '0 2px 12px rgba(114, 157, 173, 0.12)',
          }}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity size={18} color={BRAND.primary} />
              <h1 className="text-lg font-bold" style={{ color: BRAND.textMain }}>
                Pipeline Monitor
              </h1>
              <span
                className="inline-block w-2 h-2 rounded-full ml-1"
                style={{
                  backgroundColor: connected ? BRAND.success : BRAND.textSub,
                  boxShadow: connected ? `0 0 6px ${BRAND.success}` : 'none',
                }}
                title={connected ? '已連線' : '未連線'}
              />
              <span className="text-xs" style={{ color: BRAND.textSub }}>
                {events.length} 事件 / {grouped.length} session
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPaused((p) => !p)}
                className="flex items-center justify-center rounded-lg transition-transform active:scale-95"
                style={{ width: 28, height: 28, color: paused ? BRAND.warning : BRAND.primary }}
                aria-label={paused ? '恢復' : '暫停'}
                title={paused ? '恢復接收' : '暫停接收'}
              >
                {paused ? <Play size={14} /> : <Pause size={14} />}
              </button>
              <button
                onClick={() => setEvents([])}
                className="flex items-center justify-center rounded-lg transition-transform active:scale-95"
                style={{ width: 28, height: 28, color: BRAND.error }}
                aria-label="清除"
                title="清除所有事件"
              >
                <Trash2 size={14} />
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-4 pb-10 pt-3">
        {grouped.length === 0 ? (
          <div
            className="rounded-2xl p-10 text-center mt-4"
            style={{ backgroundColor: BRAND.cardBg, border: `1px solid ${BRAND.border}` }}
          >
            <Activity size={36} color={BRAND.border} className="mx-auto mb-3" />
            <p style={{ color: BRAND.textSub }}>
              {connected ? '等待 pipeline 事件… 在前端跑一次點餐就會出現' : 'SSE 未連線'}
            </p>
          </div>
        ) : (
          grouped.map(([sid, evts]) => (
            <SessionCard
              key={sid}
              sessionId={sid}
              events={evts}
              onCopy={() => handleCopyScenario(evts)}
            />
          ))
        )}
      </main>
    </div>
  );
}
