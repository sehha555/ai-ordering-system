'use client';

import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';

/** 逐字顯示 hook — 新 chunk 到達時從已顯示位置繼續打字 */
function useTypewriter(text: string, speed = 35): string {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!text) { setIndex(0); return; }
    if (index >= text.length) return;

    const timer = setTimeout(() => setIndex((i) => i + 1), speed);
    return () => clearTimeout(timer);
  }, [text, index, speed]);

  return text.slice(0, index);
}

const ASSISTANT_BUBBLE_STYLE = {
  backgroundColor: 'rgba(114, 157, 173, 0.12)',
  color: '#3a5560',
  borderRadius: '1rem 1rem 1rem 0.25rem',
  borderLeft: '3px solid var(--accent)',
} as const;

export default function ChatPanel() {
  const messages = useStore((state) => state.messages);
  const streamingText = useStore((state) => state.streamingText);
  const displayedText = useTypewriter(streamingText);
  const bottomRef = useRef<HTMLDivElement>(null);

  // 新訊息或 streaming 開始/結束時滾動（!!streamingText 避免每 token 觸發）
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, !!streamingText]);

  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4">
      {messages.length === 0 ? (
        <div className="h-full flex flex-col items-center justify-center text-center">
          <img src="/logo.png" alt="源飯糰" className="w-16 h-16 mb-3" />
          <p className="text-2xl font-bold" style={{ color: '#3a5560' }}>
            歡迎光臨源飯糰
          </p>
          <p className="text-base mt-2" style={{ color: '#6a8a90' }}>
            按空白鍵或點擊球體開始點餐
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {messages.map((msg) => (
              <motion.div
                key={msg.id}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25 }}
                className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div
                  className="max-w-[80%] px-4 py-3 text-base"
                  style={
                    msg.role === 'user'
                      ? {
                          backgroundColor: 'var(--accent)',
                          color: 'white',
                          borderRadius: '1rem 1rem 0.25rem 1rem',
                        }
                      : ASSISTANT_BUBBLE_STYLE
                  }
                >
                  {msg.content}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          {streamingText && (
            <motion.div
              key="streaming"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className="flex justify-start"
            >
              <div
                className="max-w-[80%] px-4 py-3 text-base"
                style={ASSISTANT_BUBBLE_STYLE}
              >
                {displayedText}
                <span
                  className="inline-block w-[2px] h-[1em] ml-0.5 align-middle animate-pulse"
                  style={{ backgroundColor: 'var(--accent)' }}
                />
              </div>
            </motion.div>
          )}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
