'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';

export default function LiveReceipt() {
  const { cart, total, transcript, checkoutStep, setCheckoutStep } = useStore();

  return (
    <div
      className="w-80 rounded-2xl shadow-lg p-6 flex flex-col h-full max-h-[600px]"
      style={{ backgroundColor: 'white' }}
    >
      {/* 標題 */}
      <div className="flex items-center justify-between mb-4 pb-4" style={{ borderBottom: '1px solid #d0dce0' }}>
        <h2 className="text-xl font-bold" style={{ color: '#2c3e42' }}>購物車</h2>
        {cart.length > 0 && (
          <span
            className="text-sm font-medium px-2.5 py-0.5 rounded-full"
            style={{ backgroundColor: 'rgba(114, 157, 173, 0.15)', color: '#5a8494' }}
          >
            {cart.length} 項
          </span>
        )}
      </div>

      {/* 語音識別結果 */}
      {transcript && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-4 p-3 rounded-lg"
          style={{ backgroundColor: 'rgba(114, 157, 173, 0.1)' }}
        >
          <p className="text-sm mb-1" style={{ color: '#8a9a9f' }}>你說的是：</p>
          <p style={{ color: '#2c3e42' }}>{transcript}</p>
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
              className="flex flex-col items-center justify-center h-full"
              style={{ color: '#8a9a9f' }}
            >
              <svg className="w-16 h-16 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
                  className="rounded-lg p-3"
                  style={{ backgroundColor: '#f4f7f8' }}
                >
                  <div className="flex justify-between items-start">
                    <div className="flex-1">
                      <p className="font-medium" style={{ color: '#2c3e42' }}>{item.name}</p>
                      {item.details && (
                        <p className="text-sm mt-0.5" style={{ color: '#5a6b70' }}>{item.details}</p>
                      )}
                    </div>
                    <div className="text-right ml-3">
                      <p className="font-semibold" style={{ color: '#729DAD' }}>${item.price}</p>
                      {item.quantity > 1 && (
                        <p className="text-sm" style={{ color: '#5a6b70' }}>x{item.quantity}</p>
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
          className="mt-4 pt-4"
          style={{ borderTop: '1px solid #d0dce0' }}
        >
          <div className="flex justify-between items-center">
            <span className="text-lg font-medium" style={{ color: '#5a6b70' }}>總計</span>
            <span className="text-2xl font-bold" style={{ color: '#729DAD' }}>${total}</span>
          </div>
          <button
            onClick={() => setCheckoutStep(1)}
            className="w-full mt-4 font-medium py-3 px-4 rounded-xl transition-all hover:shadow-md"
            style={{
              background: 'linear-gradient(135deg, #4a9d68 0%, #3a8555 100%)',
              color: 'white',
            }}
          >
            結帳
          </button>
        </motion.div>
      )}
    </div>
  );
}
