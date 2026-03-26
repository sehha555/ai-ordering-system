'use client';

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { BarChart3, RefreshCw } from 'lucide-react';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

// ───────────────────────────── 型別 ─────────────────────────────

interface PerfEntry {
  timestamp: number;
  asr_s: number | null;
  dm_s: number | null;
  ttfa_s: number | null;
  tts_s: number | null;
  total_s: number | null;
}

interface PerfStats {
  recent: PerfEntry[];
  averages: {
    asr_s: number | null;
    dm_s: number | null;
    ttfa_s: number | null;
    tts_s: number | null;
    total_s: number | null;
  };
  count: number;
}

// ───────────────────────────── 常數 ─────────────────────────────

// 時間範圍選項
const TIME_RANGES = [
  { label: '1h', hours: 1 },
  { label: '6h', hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d', hours: 168 },
] as const;

// 品牌色
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

const METRIC_LABELS: Record<string, string> = {
  total: '總延遲',
  asr: 'ASR',
  dm: 'DM',
  tts: 'TTS',
};

// ───────────────────────────── 工具函式 ─────────────────────────

/** 格式化時間戳為 HH:MM */
function formatTime(ts: number): string {
  const d = new Date(ts * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** 計算 P95（前端做，對已排序陣列） */
function calcP95(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const idx = Math.ceil(sorted.length * 0.95) - 1;
  return Math.round(sorted[Math.max(0, idx)] * 1000) / 1000;
}

/** 從 entry 陣列提取非 null 的欄位值 */
function extractValues(entries: PerfEntry[], field: keyof Omit<PerfEntry, 'timestamp'>): number[] {
  return entries.map((e) => e[field]).filter((v): v is number => v !== null);
}

/** 平均，保留 3 位小數 */
function avg(values: number[]): number | null {
  if (values.length === 0) return null;
  return Math.round((values.reduce((s, v) => s + v, 0) / values.length) * 1000) / 1000;
}

// ───────────────────────────── 子元件 ─────────────────────────────

/** 統計卡片 */
function StatCard({
  label,
  value,
  unit = 's',
  sub,
  color = BRAND.primary,
}: {
  label: string;
  value: number | null;
  unit?: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div
      className="rounded-2xl p-4 flex flex-col gap-1"
      style={{
        backgroundColor: BRAND.cardBg,
        border: `1px solid ${BRAND.border}`,
        boxShadow: '0 2px 8px rgba(114,157,173,0.10)',
      }}
    >
      <span className="text-xs font-medium" style={{ color: BRAND.textSub }}>{label}</span>
      <span className="text-2xl font-black" style={{ color, lineHeight: 1.1 }}>
        {value !== null ? (Number.isInteger(value) ? value : value.toFixed(3)) : '—'}
        {value !== null && <span className="text-sm font-semibold ml-1">{unit}</span>}
      </span>
      {sub && <span className="text-xs" style={{ color: BRAND.textSub }}>{sub}</span>}
    </div>
  );
}

// ───────────────────────────── 主元件 ─────────────────────────────

export default function AdminDashboardPage() {
  const [timeRange, setTimeRange] = useState<typeof TIME_RANGES[number]>(TIME_RANGES[2]); // 預設 24h
  const [entries, setEntries] = useState<PerfEntry[]>([]);
  const [stats, setStats] = useState<PerfStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── 資料獲取 ──────────────────────────────────────────────────

  const fetchData = useCallback(async (hours: number) => {
    try {
      const [histRes, statsRes] = await Promise.all([
        fetch(`/api/perf-history?hours=${hours}&limit=500`),
        fetch('/api/perf-stats'),
      ]);

      if (histRes.ok) {
        const histData = await histRes.json();
        // API 回傳 DESC，翻轉為 ASC 供圖表使用
        setEntries((histData.entries as PerfEntry[]).reverse());
      }

      if (statsRes.ok) {
        setStats(await statsRes.json());
      }

      setLastUpdated(new Date());
    } catch (e) {
      console.error('載入效能數據失敗:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  // 時間範圍變更時重新載入
  useEffect(() => {
    setLoading(true);
    fetchData(timeRange.hours);

    // 每 30 秒自動刷新
    if (intervalRef.current) clearInterval(intervalRef.current);
    intervalRef.current = setInterval(() => fetchData(timeRange.hours), 30000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [timeRange, fetchData]);

  // ── 衍生統計（memoize 避免每次 render 重算） ──────────────────

  const { p95Total, avgTotal, avgAsr, avgDm, avgTts, count, lineData, barData } = useMemo(() => {
    const totalVals = extractValues(entries, 'total_s');
    const asrVals   = extractValues(entries, 'asr_s');
    const dmVals    = extractValues(entries, 'dm_s');
    const ttsVals   = extractValues(entries, 'tts_s');

    const _avgTotal = avg(totalVals);
    const _avgAsr   = avg(asrVals);
    const _avgDm    = avg(dmVals);
    const _avgTts   = avg(ttsVals);

    return {
      p95Total: calcP95(totalVals),
      avgTotal: _avgTotal,
      avgAsr:   _avgAsr,
      avgDm:    _avgDm,
      avgTts:   _avgTts,
      count:    entries.length,
      lineData: entries.map((e) => ({
        time:  formatTime(e.timestamp),
        total: e.total_s,
        asr:   e.asr_s,
        dm:    e.dm_s,
        tts:   e.tts_s,
      })),
      barData: [
        { name: 'ASR',   value: _avgAsr,   fill: BRAND.warning },
        { name: 'DM',    value: _avgDm,    fill: BRAND.dark },
        { name: 'TTS',   value: _avgTts,   fill: BRAND.success },
        { name: '總延遲', value: _avgTotal, fill: BRAND.primary },
      ].filter((d) => d.value !== null),
    };
  }, [entries]);

  // ───────────────────────────── 渲染 ─────────────────────────────

  return (
    <div className="min-h-screen" style={{ backgroundColor: BRAND.bg }}>

      {/* ─── Sticky Header ─── */}
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
          {/* 標題列 */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <BarChart3 size={18} color={BRAND.primary} />
              <h1 className="text-lg font-bold" style={{ color: BRAND.textMain }}>效能監控</h1>
            </div>
            <div className="flex items-center gap-2">
              {lastUpdated && (
                <span className="text-xs" style={{ color: BRAND.textSub }}>
                  更新 {lastUpdated.toLocaleTimeString('zh-TW')}
                </span>
              )}
              <button
                onClick={() => fetchData(timeRange.hours)}
                className="flex items-center justify-center rounded-lg transition-transform active:scale-95"
                style={{ width: 28, height: 28, color: BRAND.primary }}
                aria-label="手動刷新"
              >
                <RefreshCw size={14} />
              </button>
            </div>
          </div>

          {/* 時間範圍切換 */}
          <div
            className="flex rounded-xl p-0.5 gap-0.5"
            style={{ backgroundColor: '#e8eef0' }}
          >
            {TIME_RANGES.map((range) => {
              const isActive = timeRange.hours === range.hours;
              return (
                <button
                  key={range.label}
                  onClick={() => setTimeRange(range)}
                  className="flex-1 py-1.5 rounded-[10px] text-xs font-medium transition-all"
                  style={{
                    backgroundColor: isActive ? 'white' : 'transparent',
                    color: isActive ? BRAND.textMain : '#5a6b70',
                    boxShadow: isActive ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                  }}
                >
                  {range.label}
                </button>
              );
            })}
          </div>
        </div>
      </header>

      {/* ─── 主體 ─── */}
      <main className="max-w-2xl mx-auto px-4 pb-10 pt-3">

        {loading ? (
          <p className="text-center py-12" style={{ color: BRAND.textSub }}>載入中...</p>
        ) : count === 0 ? (
          /* 空狀態 */
          <div
            className="rounded-2xl p-10 text-center mt-4"
            style={{ backgroundColor: BRAND.cardBg, border: `1px solid ${BRAND.border}` }}
          >
            <BarChart3 size={36} color={BRAND.border} className="mx-auto mb-3" />
            <p style={{ color: BRAND.textSub }}>
              尚無效能數據，送出語音或文字請求後將自動記錄。
            </p>
          </div>
        ) : (
          <>
            {/* ── 統計卡片 ── */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-4">
              <StatCard
                label="平均總延遲"
                value={avgTotal}
                color={BRAND.primary}
                sub={p95Total !== null ? `P95: ${p95Total}s` : undefined}
              />
              <StatCard label="平均 ASR" value={avgAsr} color={BRAND.warning} />
              <StatCard label="平均 DM"  value={avgDm}  color={BRAND.dark} />
              <StatCard label="平均 TTS" value={avgTts} color={BRAND.success} />
              <StatCard label="請求數" value={count} unit="筆" color={BRAND.textMain} sub={`${timeRange.label} 內`} />
              {stats && stats.averages.total_s !== null && (
                <StatCard
                  label="In-memory 平均"
                  value={stats.averages.total_s}
                  color="#8a9a9f"
                  sub={`最近 ${stats.count} 筆`}
                />
              )}
            </div>

            {/* ── 延遲趨勢折線圖 ── */}
            <div
              className="rounded-2xl p-4 mb-4"
              style={{
                backgroundColor: BRAND.cardBg,
                border: `1px solid ${BRAND.border}`,
                boxShadow: '0 2px 8px rgba(114,157,173,0.08)',
              }}
            >
              <h2 className="text-sm font-semibold mb-3" style={{ color: BRAND.textMain }}>
                延遲趨勢
              </h2>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={lineData} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e8eef0" />
                  <XAxis
                    dataKey="time"
                    tick={{ fontSize: 10, fill: BRAND.textSub }}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    tick={{ fontSize: 10, fill: BRAND.textSub }}
                    tickFormatter={(v) => `${v}s`}
                  />
                  <Tooltip
                    contentStyle={{
                      borderRadius: 12,
                      border: `1px solid ${BRAND.border}`,
                      fontSize: 12,
                    }}
                    formatter={(value, name) => [
                      typeof value === 'number' ? `${value.toFixed(3)}s` : String(value),
                      METRIC_LABELS[name as string] ?? name,
                    ]}
                  />
                  <Legend
                    formatter={(value: string) => METRIC_LABELS[value] ?? value}
                    wrapperStyle={{ fontSize: 11 }}
                  />
                  <Line
                    type="monotone"
                    dataKey="total"
                    stroke={BRAND.primary}
                    strokeWidth={2}
                    dot={false}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="asr"
                    stroke={BRAND.warning}
                    strokeWidth={1.5}
                    dot={false}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="dm"
                    stroke={BRAND.dark}
                    strokeWidth={1.5}
                    dot={false}
                    connectNulls
                  />
                  <Line
                    type="monotone"
                    dataKey="tts"
                    stroke={BRAND.success}
                    strokeWidth={1.5}
                    dot={false}
                    connectNulls
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* ── 各階段平均占比長條圖 ── */}
            {barData.length > 0 && (
              <div
                className="rounded-2xl p-4"
                style={{
                  backgroundColor: BRAND.cardBg,
                  border: `1px solid ${BRAND.border}`,
                  boxShadow: '0 2px 8px rgba(114,157,173,0.08)',
                }}
              >
                <h2 className="text-sm font-semibold mb-3" style={{ color: BRAND.textMain }}>
                  各階段平均耗時
                </h2>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={barData} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e8eef0" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: BRAND.textSub }} />
                    <YAxis
                      tick={{ fontSize: 10, fill: BRAND.textSub }}
                      tickFormatter={(v) => `${v}s`}
                    />
                    <Tooltip
                      contentStyle={{
                        borderRadius: 12,
                        border: `1px solid ${BRAND.border}`,
                        fontSize: 12,
                      }}
                      formatter={(value) => [
                        typeof value === 'number' ? `${value.toFixed(3)}s` : String(value),
                        '平均耗時',
                      ]}
                    />
                    <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                      {barData.map((entry, index) => (
                        <Cell key={index} fill={entry.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
