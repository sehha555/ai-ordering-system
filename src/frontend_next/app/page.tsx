'use client';

import { useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';
import VoiceController from '../components/VoiceController';
import AudioVisualizer from '../components/AudioVisualizer';
import LiveReceipt from '../components/LiveReceipt';
import CheckoutFlow from '../components/CheckoutFlow';
import Toast from '../components/Toast';

export default function Home() {
  const { checkoutStep, cart, status, vadEnabled } = useStore();
  const hasItems = cart.length > 0;

  // VoiceController 暴露的 handleClick ref（push-to-talk 模式）
  const triggerRef = useRef<(() => void) | null>(null);

  const handleLargeVisualizerClick = () => {
    triggerRef.current?.();
  };

  return (
    <div className="h-screen w-screen flex flex-col overflow-hidden" style={{ backgroundColor: '#f0f5f7' }}>
      <Toast />

      {/* Header */}
      <header
        className="flex items-center justify-between px-6 py-3 shrink-0"
        style={{
          backgroundColor: '#ffffff',
          borderBottom: '1px solid #d0dce0',
        }}
      >
        <div className="flex items-center gap-2">
          {/* 小波形：只在 active（有購物車品項）時顯示 */}
          <AnimatePresence>
            {hasItems && (
              <motion.div
                key="header-viz"
                layoutId="voice-viz"
                initial={{ opacity: 0, width: 0 }}
                animate={{ opacity: 1, width: 40 }}
                exit={{ opacity: 0, width: 0 }}
                transition={{ duration: 0.4, ease: 'easeInOut' }}
                className="shrink-0 overflow-hidden"
              >
                <AudioVisualizer status={status} size="small" />
              </motion.div>
            )}
          </AnimatePresence>

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

        <p className="text-sm" style={{ color: '#5a6b70' }}>語音點餐系統</p>
      </header>

      {/* 主內容區 */}
      <div className="flex-1 overflow-hidden">
        {checkoutStep > 0 ? (
          <CheckoutFlow />
        ) : (
          <AnimatePresence mode="wait">
            {!hasItems ? (
              /* Idle 畫面：大波形置中 */
              <motion.div
                key="idle-view"
                className="h-full flex flex-col items-center justify-center gap-4"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
              >
                <motion.div
                  layoutId="voice-viz"
                  className="cursor-pointer"
                  onClick={handleLargeVisualizerClick}
                  transition={{ duration: 0.4, ease: 'easeInOut' }}
                >
                  <AudioVisualizer status={status} size="large" />
                </motion.div>

                <p
                  className="text-sm"
                  style={{ color: '#8a9a9f' }}
                >
                  {vadEnabled ? '語音自動偵測已啟用，請直接說話' : '點擊或按空白鍵開始說話'}
                </p>
              </motion.div>
            ) : (
              /* Active 畫面：AI 回覆 Banner + 購物車 */
              <motion.div
                key="active-view"
                className="h-full flex flex-col overflow-hidden"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
              >
                <AiReplyBanner />

                <div className="flex-1 overflow-y-auto px-6 py-4">
                  <LiveReceipt />
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        )}
      </div>

      {/* 隱藏的 VoiceController：保留所有邏輯，triggerRef 暴露 handleClick */}
      <div className="hidden">
        <VoiceController triggerRef={triggerRef} />
      </div>
    </div>
  );
}

/* AI 回覆 Banner */
function AiReplyBanner() {
  const { aiReply, status } = useStore();

  const isVisible = Boolean(aiReply) && (status === 'speaking' || status === 'processing');

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          key={aiReply}
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25 }}
          className="mx-6 mt-4 px-5 py-3 rounded-2xl text-base"
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
