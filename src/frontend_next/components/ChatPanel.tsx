'use client';

import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';

export default function ChatPanel() {
  const messages = useStore((state) => state.messages);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-4 py-4">
      {messages.length === 0 ? (
        <div className="h-full flex flex-col items-center justify-center text-center">
          <p className="text-4xl mb-3">🍙</p>
          <p className="text-lg font-medium" style={{ color: '#5a6b70' }}>
            歡迎光臨源飯糰
          </p>
          <p className="text-sm mt-1" style={{ color: '#8a9a9f' }}>
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
                          backgroundColor: '#729DAD',
                          color: 'white',
                          borderRadius: '1rem 1rem 0.25rem 1rem',
                        }
                      : {
                          backgroundColor: 'rgba(114, 157, 173, 0.12)',
                          color: '#3a5560',
                          borderRadius: '1rem 1rem 1rem 0.25rem',
                          borderLeft: '3px solid #729DAD',
                        }
                  }
                >
                  {msg.content}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  );
}
