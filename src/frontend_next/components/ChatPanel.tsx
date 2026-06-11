'use client';

import { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';
import { useTypewriter } from '../hooks/useTypewriter';
import type { ChatMessage } from '../types';
import storeConfig from '../../config/store_config.json';

const ASSISTANT_BUBBLE_STYLE = {
  backgroundColor: 'rgba(114, 157, 173, 0.12)',
  color: '#3a5560',
  borderRadius: '1rem 1rem 1rem 0.25rem',
  borderLeft: '3px solid var(--accent)',
} as const;

// 訊息氣泡：掛載時逐字打出內容；assistant 氣泡從串流氣泡已顯示的字數接續，不重打
function MessageBubble({ msg, streamTypedCount }: { msg: ChatMessage; streamTypedCount: number }) {
  const [initialIndex] = useState(() => (msg.role === 'assistant' ? streamTypedCount : 0));
  const displayed = useTypewriter(msg.content, 35, initialIndex);

  return (
    <motion.div
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
        {displayed}
      </div>
    </motion.div>
  );
}

export default function ChatPanel() {
  const messages = useStore((state) => state.messages);
  const streamingText = useStore((state) => state.streamingText);
  const displayedText = useTypewriter(streamingText);
  // 串流氣泡已打出的字數：完整訊息接手時從這裡接續（換手 render 讀到的是前一次的值）
  const streamTypedCountRef = useRef(0);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    streamTypedCountRef.current = streamingText ? displayedText.length : 0;
  }, [streamingText, displayedText]);

  // 新訊息或 streaming 開始/結束時滾動（!!streamingText 避免每 token 觸發）
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, !!streamingText]);

  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4">
      {messages.length === 0 ? (
        <div className="h-full flex flex-col items-center justify-center text-center">
          <img src="/logo.png" alt={storeConfig.store.name} className="w-16 h-16 mb-3" />
          <p className="text-2xl font-bold" style={{ color: '#3a5560' }}>
            {storeConfig.messages.welcome_title}
          </p>
          <p className="text-base mt-2" style={{ color: '#6a8a90' }}>
            {storeConfig.messages.welcome_subtitle}
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <AnimatePresence initial={false}>
            {messages.map((msg) => (
              <MessageBubble key={msg.id} msg={msg} streamTypedCount={streamTypedCountRef.current} />
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
