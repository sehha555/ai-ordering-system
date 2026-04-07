'use client';

import { useCallback, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';
import { AppStatus } from '../types';
import VoiceController from '../components/VoiceController';
import AudioVisualizer from '../components/AudioVisualizer';
import ChatPanel from '../components/ChatPanel';
import OrderPanel from '../components/OrderPanel';
import Toast from '../components/Toast';
import MicSelector from '../components/MicSelector';

export default function Home() {
  const { status, vadEnabled, setVadEnabled } = useStore();

  const triggerRef = useRef<(() => void) | null>(null);
  const handleVisualizerClick = () => { triggerRef.current?.(); };

  // 拖曳分隔條調整右側面板寬度
  const [rightWidth, setRightWidth] = useState(380);
  const dragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const onDragStart = useCallback((e: React.PointerEvent) => {
    e.preventDefault();
    dragging.current = true;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const onDragMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const newRight = rect.right - e.clientX;
    setRightWidth(Math.max(260, Math.min(600, newRight)));
  }, []);

  const onDragEnd = useCallback(() => { dragging.current = false; }, []);

  return (
    <div className="h-screen w-screen flex items-center justify-center" style={{ backgroundColor: '#e4ecef' }}>
    <div className="flex flex-col overflow-hidden" style={{ backgroundColor: '#f0f5f7', width: '85vw', height: '90vh', maxWidth: '98vw', maxHeight: '98vh', minWidth: '600px', minHeight: '500px', borderRadius: '1.5rem', boxShadow: '0 8px 40px rgba(114, 157, 173, 0.18)', resize: 'both' }}>
      <Toast />

      {/* Header */}
      <header
        className="flex items-center justify-between px-5 py-3 shrink-0"
        style={{ backgroundColor: '#ffffff', borderBottom: '1px solid var(--border-color)' }}
      >
        <div className="flex items-center gap-3">
          <img src="/logo.png" alt="源飯糰" style={{ width: 36, height: 36 }} />
          <h1 className="text-2xl font-black tracking-wide" style={{ color: 'var(--text-color)' }}>
            源飯糰
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <MicSelector />
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>語音點餐系統</p>
        </div>
      </header>

      {/* 主內容區：左右分欄 */}
      <div
        ref={containerRef}
        className="flex-1 overflow-hidden flex p-4"
        onPointerMove={onDragMove}
        onPointerUp={onDragEnd}
      >
        {/* 左邊：對話記錄 + 球體 */}
        <div
          className="flex-1 min-w-0 flex flex-col rounded-2xl overflow-hidden"
          style={{ backgroundColor: '#ffffff' }}
        >
          <ChatPanel />

          {/* 球體區域 */}
          <motion.div
            className="shrink-0 flex flex-col items-center justify-center cursor-pointer select-none py-4"
            onClick={handleVisualizerClick}
            whileTap={{ scale: 0.92 }}
            style={{ borderTop: '1px solid var(--background-tertiary)' }}
          >
            <div style={{ width: 160, height: 160 }}>
              <BallVisualizer status={status} />
            </div>
            <VoiceHint status={status} vadEnabled={vadEnabled} />
            <button
              onClick={(e) => { e.stopPropagation(); setVadEnabled(!vadEnabled); }}
              className="mt-2 px-4 py-1.5 rounded-full text-xs font-medium transition-colors"
              style={{
                backgroundColor: vadEnabled ? 'var(--accent)' : 'var(--background-tertiary)',
                color: vadEnabled ? 'white' : 'var(--text-muted)',
                border: `1px solid ${vadEnabled ? 'var(--accent-dark)' : 'var(--border-color)'}`,
              }}
            >
              {vadEnabled ? '自動偵測模式' : '按鍵說話模式'}
            </button>
          </motion.div>
        </div>

        {/* 拖曳分隔條 */}
        <div
          onPointerDown={onDragStart}
          className="shrink-0 flex items-center justify-center cursor-col-resize select-none"
          style={{ width: 12 }}
        >
          <div
            className="rounded-full transition-colors"
            style={{ width: 4, height: 40, backgroundColor: 'var(--border-color)' }}
          />
        </div>

        {/* 右邊：點餐單 */}
        <div
          className="shrink-0 flex flex-col rounded-2xl overflow-hidden"
          style={{ backgroundColor: '#ffffff', width: rightWidth }}
        >
          <OrderPanel />
        </div>
      </div>

      {/* 隱藏的 VoiceController */}
      <div className="hidden">
        <VoiceController triggerRef={triggerRef} />
      </div>
    </div>
    </div>
  );
}

/* ─── 球體視覺化（volume 高頻更新，隔離避免 Home re-render）─── */
function BallVisualizer({ status }: { status: AppStatus }) {
  const volume = useStore(state => state.volume);
  return <AudioVisualizer status={status} volume={volume} size="medium" />;
}

/* ─── 球體下方狀態提示 ─── */
const STATUS_HINTS: Record<string, string> = {
  idle: '點擊或按空白鍵開始說話',
  listening: '聆聽中...',
  processing: '處理中...',
  speaking: '回覆中...',
};

function VoiceHint({ status, vadEnabled }: { status: string; vadEnabled: boolean }) {
  const text = status === 'idle'
    ? (vadEnabled ? '語音自動偵測已啟用，請直接說話' : '點擊或按空白鍵開始說話')
    : (STATUS_HINTS[status] ?? '');

  return (
    <AnimatePresence mode="wait">
      <motion.p
        key={text}
        className="text-sm mt-2"
        style={{ color: status === 'listening' ? 'var(--success)' : status === 'processing' ? 'var(--warning)' : '#8a9a9f' }}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -4 }}
        transition={{ duration: 0.2 }}
      >
        {text}
      </motion.p>
    </AnimatePresence>
  );
}
