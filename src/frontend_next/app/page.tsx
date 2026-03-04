'use client';

import { useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';
import VoiceController from '../components/VoiceController';
import AudioVisualizer from '../components/AudioVisualizer';
import CheckoutFlow from '../components/CheckoutFlow';
import Toast from '../components/Toast';
import MicSelector from '../components/MicSelector';

export default function Home() {
  const { checkoutStep, cart, total, status, vadEnabled, setVadEnabled, volume, setCheckoutStep } = useStore();
  const hasItems = cart.length > 0;

  const triggerRef = useRef<(() => void) | null>(null);
  const handleVisualizerClick = () => { triggerRef.current?.(); };

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden" style={{ backgroundColor: '#f0f5f7' }}>
      <Toast />

      {/* Header */}
      <header
        className="flex items-center justify-between px-5 py-3 shrink-0"
        style={{ backgroundColor: '#ffffff', borderBottom: '1px solid #d0dce0' }}
      >
        <div className="flex items-center gap-2">
          <span className="text-2xl leading-none">🍙</span>
          <h1
            className="text-xl font-bold leading-none"
            style={{
              background: 'linear-gradient(90deg, #729DAD, #8fb3c0)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}
          >
            源飯糰
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <MicSelector />
          <p className="text-sm" style={{ color: '#5a6b70' }}>語音點餐系統</p>
        </div>
      </header>

      {/* 主內容區 */}
      <div className="flex-1 overflow-hidden relative">
        {checkoutStep > 0 ? (
          <CheckoutFlow />
        ) : (
          <div className="h-full flex flex-col">
            {/* 上方：有品項時顯示點餐單 */}
            <AnimatePresence>
              {hasItems && (
                <motion.div
                  key="order-view"
                  className="flex-1 min-h-0 flex flex-col overflow-hidden"
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.4, ease: [0.4, 0, 0.2, 1] }}
                >
                  <AiReplyBanner />

                  <div className="flex-1 overflow-y-auto px-4 py-4">
                    <OrderTicket
                      items={cart}
                      total={total}
                      onCheckout={() => setCheckoutStep(1)}
                    />
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* 球體（始終存在，單一實例）：無品項時 flex-1 置中，有品項時 shrink 到底部 */}
            <motion.div
              className={`shrink-0 flex flex-col items-center justify-center cursor-pointer select-none ${
                hasItems ? '' : 'flex-1'
              }`}
              onClick={handleVisualizerClick}
              whileTap={{ scale: 0.92 }}
              layout
              transition={{ duration: 0.5, ease: [0.4, 0, 0.2, 1] }}
              style={{ paddingTop: hasItems ? 8 : 0, paddingBottom: hasItems ? 16 : 0 }}
            >
              <motion.div
                animate={{
                  width: hasItems ? 120 : 256,
                  height: hasItems ? 120 : 256,
                }}
                transition={{ duration: 0.5, ease: [0.4, 0, 0.2, 1] }}
              >
                <AudioVisualizer
                  status={status}
                  volume={volume}
                  size={hasItems ? 'medium' : 'large'}
                />
              </motion.div>
              <VoiceHint status={status} hasItems={hasItems} vadEnabled={vadEnabled} />
              <button
                onClick={(e) => { e.stopPropagation(); setVadEnabled(!vadEnabled); }}
                className="mt-2 px-4 py-1.5 rounded-full text-xs font-medium transition-colors"
                style={{
                  backgroundColor: vadEnabled ? '#729DAD' : '#e8eef0',
                  color: vadEnabled ? 'white' : '#5a6b70',
                  border: `1px solid ${vadEnabled ? '#5a8494' : '#d0dce0'}`,
                }}
              >
                {vadEnabled ? '自動偵測模式' : '按鍵說話模式'}
              </button>
            </motion.div>
          </div>
        )}
      </div>

      {/* 隱藏的 VoiceController */}
      <div className="hidden">
        <VoiceController triggerRef={triggerRef} />
      </div>
    </div>
  );
}

/* ─── AI 回覆 Banner ─── */
function AiReplyBanner() {
  const { aiReply, status } = useStore();
  const isVisible = Boolean(aiReply) && (status === 'speaking' || status === 'processing');

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          key="ai-reply"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25 }}
          className="mx-4 mt-3 px-5 py-3 rounded-2xl text-base"
          style={{
            backgroundColor: 'rgba(114, 157, 173, 0.12)',
            color: '#3a5560',
            borderLeft: '3px solid #729DAD',
          }}
        >
          「{aiReply}」
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ─── 球體下方狀態提示 ─── */
const STATUS_HINTS: Record<string, string> = {
  idle: '點擊或按空白鍵開始說話',
  listening: '聆聽中...',
  processing: '處理中...',
  speaking: '回覆中...',
};

function VoiceHint({ status, hasItems, vadEnabled }: { status: string; hasItems: boolean; vadEnabled: boolean }) {
  let text: string;
  if (status === 'idle') {
    text = hasItems
      ? '繼續說話點餐，或按結帳完成'
      : vadEnabled ? '語音自動偵測已啟用，請直接說話' : '點擊或按空白鍵開始說話';
  } else {
    text = STATUS_HINTS[status] ?? '';
  }

  return (
    <AnimatePresence mode="wait">
      <motion.p
        key={text}
        className="text-sm mt-2"
        style={{ color: status === 'listening' ? '#4a9d68' : status === 'processing' ? '#c49a30' : '#8a9a9f' }}
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

/* ─── 點餐單（後台風格）─── */
interface CartItem {
  name: string;
  details: string;
  price: number;
  quantity: number;
}

function OrderTicket({
  items,
  total,
  onCheckout,
}: {
  items: CartItem[];
  total: number;
  onCheckout: () => void;
}) {
  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        backgroundColor: 'white',
        border: '1px solid #d0dce0',
        borderLeft: '5px solid #729DAD',
        boxShadow: '0 2px 16px rgba(114, 157, 173, 0.12)',
      }}
    >
      {/* 標題 */}
      <div
        className="px-6 py-5 flex items-center justify-between"
        style={{ borderBottom: '1px solid #e8eef0' }}
      >
        <div className="flex items-center gap-3">
          <span className="text-3xl font-black" style={{ color: '#2c3e42' }}>
            點餐中
          </span>
          <span
            className="text-sm font-semibold px-3 py-1 rounded-full"
            style={{ backgroundColor: '#e8f7ee', color: '#4a9d68' }}
          >
            {items.reduce((sum, i) => sum + i.quantity, 0)} 品項
          </span>
        </div>
      </div>

      {/* 品項列表 */}
      <div className="px-6 py-2">
        {/* 新品項：fade in + slide up；移除時：fade out + slide down */}
        <AnimatePresence mode="popLayout">
          {items.map((item, index) => (
            <motion.div
              key={`${item.name}-${index}`}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 8 }}
              transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
            >
              <div className="flex justify-between items-center py-4">
                <div className="flex-1 pr-4">
                  <p className="text-xl font-semibold" style={{ color: '#2c3e42' }}>
                    {item.name}
                  </p>
                  {item.details && (
                    <p className="text-base mt-1" style={{ color: '#5a6b70' }}>
                      {item.details}
                    </p>
                  )}
                </div>
                <div className="text-right shrink-0 flex items-center gap-4">
                  <span className="text-base font-medium" style={{ color: '#8a9a9f' }}>
                    ×{item.quantity}
                  </span>
                  <span className="text-xl font-bold" style={{ color: '#2c3e42' }}>
                    ${item.price}
                  </span>
                </div>
              </div>
              {index < items.length - 1 && (
                <div style={{ borderBottom: '1px solid #e8eef0' }} />
              )}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* 總計 + 結帳 */}
      <div
        className="px-6 py-5"
        style={{ borderTop: '1px solid #d0dce0', background: 'linear-gradient(180deg, #f8fafb 0%, #f0f5f7 100%)' }}
      >
        <div className="flex justify-between items-center mb-5">
          <span className="text-lg font-semibold" style={{ color: '#5a6b70' }}>合計</span>
          <span className="font-black" style={{ fontSize: '2rem', color: '#729DAD' }}>${total}</span>
        </div>
        <button
          onClick={onCheckout}
          className="w-full py-4 rounded-xl text-lg font-semibold text-white transition-opacity hover:opacity-90 active:opacity-80"
          style={{ backgroundColor: '#729DAD' }}
        >
          結帳
        </button>
      </div>
    </div>
  );
}
