'use client';

import { motion, AnimatePresence } from 'framer-motion';
import type { CartItem } from '../types';

interface OrderTicketProps {
  items: CartItem[];
  total: number;
  onCheckout: () => void;
}

export default function OrderTicket({ items, total, onCheckout }: OrderTicketProps) {
  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        backgroundColor: 'white',
        border: '1px solid var(--border-color)',
        borderLeft: '5px solid var(--accent)',
        boxShadow: '0 2px 16px rgba(114, 157, 173, 0.12)',
      }}
    >
      {/* 標題 */}
      <div
        className="px-6 py-5 flex items-center justify-between"
        style={{ borderBottom: '1px solid var(--background-tertiary)' }}
      >
        <div className="flex items-center gap-3">
          <span className="text-3xl font-black" style={{ color: 'var(--text-color)' }}>
            點餐中
          </span>
          <span
            className="text-sm font-semibold px-3 py-1 rounded-full"
            style={{ backgroundColor: '#e8f7ee', color: 'var(--success)' }}
          >
            {items.reduce((sum, i) => sum + i.quantity, 0)} 品項
          </span>
        </div>
      </div>

      {/* 品項列表 */}
      <div className="px-6 py-2">
        <AnimatePresence mode="popLayout">
          {items.map((item, index) => (
            <motion.div
              key={`${item.name}-${item.details}`}
              initial={{ opacity: 0, y: -14 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 6, scale: 0.97 }}
              transition={{ duration: 0.3, delay: Math.min(index * 0.06, 0.18), ease: [0.4, 0, 0.2, 1] }}
            >
              <div className="flex justify-between items-center py-4">
                <div className="flex-1 pr-4">
                  <p className="text-xl font-semibold" style={{ color: 'var(--text-color)' }}>
                    {item.name}
                  </p>
                  {item.details && (
                    <p className="text-base mt-1" style={{ color: 'var(--text-muted)' }}>
                      {item.details}
                    </p>
                  )}
                </div>
                <div className="text-right shrink-0 flex items-center gap-4">
                  <span className="text-base font-medium" style={{ color: '#8a9a9f' }}>
                    x{item.quantity}
                  </span>
                  <span className="text-xl font-bold" style={{ color: 'var(--text-color)' }}>
                    ${item.price}
                  </span>
                </div>
              </div>
              {index < items.length - 1 && (
                <div style={{ borderBottom: '1px solid var(--background-tertiary)' }} />
              )}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* 總計 + 結帳 */}
      <div
        className="px-6 py-5"
        style={{ borderTop: '1px solid var(--border-color)', background: 'linear-gradient(180deg, #f8fafb 0%, #f0f5f7 100%)' }}
      >
        <div className="flex justify-between items-center mb-5">
          <span className="text-lg font-semibold" style={{ color: 'var(--text-muted)' }}>合計</span>
          <span className="font-black" style={{ fontSize: '2rem', color: 'var(--accent)' }}>${total}</span>
        </div>
        <button
          onClick={onCheckout}
          className="w-full py-4 rounded-xl text-lg font-semibold text-white transition-opacity hover:opacity-90 active:opacity-80"
          style={{ backgroundColor: 'var(--accent)' }}
        >
          結帳
        </button>
      </div>
    </div>
  );
}
