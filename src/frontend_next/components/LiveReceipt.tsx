'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';

export default function LiveReceipt() {
  const { cart, total, checkoutStep, setCheckoutStep } = useStore();

  return (
    <div className="w-full flex flex-col">
      {/* 標題列 */}
      <div
        className="flex items-center justify-between mb-6 pb-4"
        style={{ borderBottom: '1px solid #d0dce0' }}
      >
        <h2 className="text-2xl font-bold" style={{ color: '#1a2e35' }}>
          購物車
        </h2>
        {cart.length > 0 && (
          <span
            className="text-sm font-medium px-3 py-1 rounded-full"
            style={{ backgroundColor: 'rgba(114, 157, 173, 0.15)', color: '#5a8494' }}
          >
            {cart.length} 項
          </span>
        )}
      </div>

      {/* 品項列表 */}
      <div className="flex-1">
        <AnimatePresence mode="popLayout">
          {cart.length === 0 ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center py-16"
              style={{ color: '#8a9a9f' }}
            >
              <svg
                className="w-20 h-20 mb-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z"
                />
              </svg>
              <p className="text-xl font-medium">購物車是空的</p>
              <p className="text-base mt-2" style={{ color: '#a0adb0' }}>
                開始點餐吧！
              </p>
            </motion.div>
          ) : (
            <ul className="space-y-4">
              {cart.map((item, index) => (
                <motion.li
                  key={`${item.name}-${index}`}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: 0.2 }}
                >
                  <div className="flex justify-between items-start">
                    {/* 左側：名稱 + 細節 */}
                    <div className="flex-1 pr-4">
                      <p className="text-xl font-medium" style={{ color: '#1a2e35' }}>
                        {item.name}
                      </p>
                      {item.details && (
                        <p className="text-base mt-0.5" style={{ color: '#5a6b70' }}>
                          {item.details}
                        </p>
                      )}
                    </div>
                    {/* 右側：數量 × 價格 */}
                    <div className="text-right shrink-0">
                      <p className="text-xl font-semibold" style={{ color: '#729DAD' }}>
                        {item.quantity} × ${item.price}
                      </p>
                    </div>
                  </div>
                  {/* 分隔線（最後一項不顯示） */}
                  {index < cart.length - 1 && (
                    <div
                      className="mt-4"
                      style={{ borderBottom: '1px solid #d0dce0' }}
                    />
                  )}
                </motion.li>
              ))}
            </ul>
          )}
        </AnimatePresence>
      </div>

      {/* 總計 + 結帳按鈕 */}
      {cart.length > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="mt-8 pt-6"
          style={{ borderTop: '1px solid #d0dce0' }}
        >
          <div className="flex justify-between items-center mb-5">
            <span className="text-lg" style={{ color: '#5a6b70' }}>
              總計
            </span>
            <span className="text-3xl font-bold" style={{ color: '#729DAD' }}>
              ${total}
            </span>
          </div>
          <button
            onClick={() => setCheckoutStep(1)}
            className="w-full py-4 rounded-2xl text-lg font-semibold text-white transition-opacity hover:opacity-90 active:opacity-80"
            style={{ backgroundColor: '#729DAD' }}
          >
            結帳
          </button>
        </motion.div>
      )}
    </div>
  );
}
