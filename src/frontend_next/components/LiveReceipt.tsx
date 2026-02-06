'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';

export default function LiveReceipt() {
  const { cart, total, transcript } = useStore();

  return (
    <div className="w-80 bg-white rounded-2xl shadow-lg p-6 flex flex-col h-full max-h-[600px]">
      {/* 標題 */}
      <div className="flex items-center justify-between mb-4 pb-4 border-b border-gray-100">
        <h2 className="text-xl font-bold text-gray-800">購物車</h2>
        {cart.length > 0 && (
          <span className="bg-green-100 text-green-800 text-sm font-medium px-2.5 py-0.5 rounded-full">
            {cart.length} 項
          </span>
        )}
      </div>

      {/* 語音識別結果 */}
      {transcript && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-4 p-3 bg-blue-50 rounded-lg"
        >
          <p className="text-sm text-gray-500 mb-1">你說的是：</p>
          <p className="text-gray-800">{transcript}</p>
        </motion.div>
      )}

      {/* 購物車列表 */}
      <div className="flex-1 overflow-y-auto">
        <AnimatePresence mode="popLayout">
          {cart.length === 0 ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center h-full text-gray-400"
            >
              <svg
                className="w-16 h-16 mb-4"
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
              <p>購物車是空的</p>
              <p className="text-sm mt-1">開始點餐吧！</p>
            </motion.div>
          ) : (
            <ul className="space-y-3">
              {cart.map((item, index) => (
                <motion.li
                  key={`${item.name}-${index}`}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: 0.2 }}
                  className="bg-gray-50 rounded-lg p-3"
                >
                  <div className="flex justify-between items-start">
                    <div className="flex-1">
                      <p className="font-medium text-gray-800">{item.name}</p>
                      {item.details && (
                        <p className="text-sm text-gray-500 mt-0.5">{item.details}</p>
                      )}
                    </div>
                    <div className="text-right ml-3">
                      <p className="font-semibold text-gray-800">${item.price}</p>
                      {item.quantity > 1 && (
                        <p className="text-sm text-gray-500">x{item.quantity}</p>
                      )}
                    </div>
                  </div>
                </motion.li>
              ))}
            </ul>
          )}
        </AnimatePresence>
      </div>

      {/* 總計 */}
      {cart.length > 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="mt-4 pt-4 border-t border-gray-200"
        >
          <div className="flex justify-between items-center">
            <span className="text-lg font-medium text-gray-600">總計</span>
            <span className="text-2xl font-bold text-green-600">${total}</span>
          </div>
          <button className="w-full mt-4 bg-green-500 hover:bg-green-600 text-white font-medium py-3 px-4 rounded-xl transition-colors">
            說「結帳」完成訂單
          </button>
        </motion.div>
      )}
    </div>
  );
}
