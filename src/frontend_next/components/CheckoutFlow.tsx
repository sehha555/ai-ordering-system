'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { useState, useEffect } from 'react';
import { useStore } from '../store/useStore';
import type { CheckoutPreview, OrderResult } from '../types';

const stepVariants = {
  enter: { opacity: 0, y: 20 },
  center: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -20 },
};

export default function CheckoutFlow() {
  const {
    cart,
    total,
    checkoutStep,
    orderResult,
    checkoutPreview,
    sessionId,
    setCheckoutStep,
    setOrderResult,
    resetSession,
  } = useStore();

  // 手動結帳用的本地狀態（語音預填時讀取 checkoutPreview）
  const [selectedDine, setSelectedDine] = useState<'dine-in' | 'take-out' | null>(
    checkoutPreview?.dineType ?? null
  );
  const [selectedPayment, setSelectedPayment] = useState<'cash' | 'line_pay' | null>(
    checkoutPreview?.paymentMethod ?? null
  );
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(10);

  // checkoutPreview 更新時同步預填本地狀態（語音觸發跳到 step 1）
  useEffect(() => {
    if (checkoutPreview) {
      setSelectedDine(checkoutPreview.dineType);
      setSelectedPayment(checkoutPreview.paymentMethod);
    }
  }, [checkoutPreview]);

  // 結帳完成後自動倒數返回
  useEffect(() => {
    if (checkoutStep !== 2) return;
    setCountdown(10);
    const timer = setInterval(() => {
      setCountdown(prev => prev - 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [checkoutStep]);

  // 倒數歸零時重置（避免在 setState callback 中呼叫 resetSession）
  useEffect(() => {
    if (countdown <= 0 && checkoutStep === 2) {
      resetSession();
    }
  }, [countdown, checkoutStep, resetSession]);

  // 手動結帳 — 送出訂單到後端
  const handleManualSubmit = async () => {
    if (cart.length === 0) {
      setError('購物車是空的，請先點餐');
      return;
    }
    if (!selectedDine || !selectedPayment) {
      setError('請選擇用餐方式和付款方式');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const response = await fetch('/api/checkout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          dine_type: selectedDine,
          payment_method: selectedPayment,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || '結帳失敗');
      }

      const data = await response.json();

      if (data.status === 'ok') {
        // 使用 setOrderResult，它會自動設定 checkoutStep 為 2
        setOrderResult({
          order_number: data.order_number,
          total: data.total_price || total,
          item_count: cart.length,
          items_display: data.items_display || [],
          dine_type: selectedDine,
          payment_method: selectedPayment,
        });
      } else {
        throw new Error('結帳失敗');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '結帳失敗，請稍後重試';
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  // 開始新訂單 — 重置所有狀態
  const handleNewOrder = () => {
    resetSession();
  };

  // 返回 — 返回到主頁面
  const handleBack = () => {
    setCheckoutStep(0);
  };

  return (
    <div className="flex-1 flex flex-col p-6">
      <AnimatePresence mode="wait">
        {/* 手動結帳頁面（一頁式） */}
        {checkoutStep === 1 && (
          <motion.div
            key="manual-checkout"
            variants={stepVariants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: 0.25 }}
            className="flex-1 flex flex-col"
          >
            <h2 className="text-2xl font-semibold text-center mb-8" style={{ color: 'var(--text-color)' }}>
              結帳
            </h2>

            {/* 錯誤訊息 */}
            {error && (
              <div className="rounded-xl p-3 mb-4 text-sm text-white bg-red-500 text-center">
                {error}
              </div>
            )}

            {/* 空購物車提示 */}
            {cart.length === 0 && (
              <div className="rounded-xl p-4 mb-4 text-center" style={{ backgroundColor: '#fff3cd', color: '#856404' }}>
                <p className="font-medium">購物車是空的</p>
                <p className="text-sm mt-1">請先點餐再結帳</p>
              </div>
            )}

            {/* 用餐方式 */}
            <div className="mb-6">
              <p className="text-sm font-medium mb-3" style={{ color: 'var(--text-muted)' }}>用餐方式</p>
              <div className="flex gap-3">
                {([['dine-in', '內用'], ['take-out', '外帶']] as const).map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => setSelectedDine(value)}
                    className="flex-1 py-3 rounded-xl font-medium transition-all"
                    style={{
                      backgroundColor: selectedDine === value ? 'var(--accent)' : 'white',
                      color: selectedDine === value ? 'white' : 'var(--text-color)',
                      border: `2px solid ${selectedDine === value ? 'var(--accent)' : 'var(--border-color)'}`,
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* 付款方式 */}
            <div className="mb-6">
              <p className="text-sm font-medium mb-3" style={{ color: 'var(--text-muted)' }}>付款方式</p>
              <div className="flex gap-3">
                {([['cash', '現金'], ['line_pay', 'Line Pay']] as const).map(([value, label]) => (
                  <button
                    key={value}
                    onClick={() => setSelectedPayment(value)}
                    className="flex-1 py-3 rounded-xl font-medium transition-all"
                    style={{
                      backgroundColor: selectedPayment === value ? 'var(--accent)' : 'white',
                      color: selectedPayment === value ? 'white' : 'var(--text-color)',
                      border: `2px solid ${selectedPayment === value ? 'var(--accent)' : 'var(--border-color)'}`,
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* 訂單摘要 */}
            <div
              className="rounded-xl p-4 mb-4 max-h-40 overflow-y-auto"
              style={{ backgroundColor: 'var(--background)' }}
            >
              {cart.map((item, i) => (
                <div
                  key={i}
                  className="flex justify-between py-2"
                  style={{ borderBottom: i < cart.length - 1 ? '1px solid var(--border-color)' : 'none' }}
                >
                  <span style={{ color: 'var(--text-color)' }}>{item.name} x{item.quantity}</span>
                  <span className="font-medium" style={{ color: 'var(--accent)' }}>${item.price}</span>
                </div>
              ))}
            </div>

            {/* 總計 */}
            <div className="flex justify-between items-center mb-6 px-1">
              <span className="text-lg font-medium" style={{ color: 'var(--text-muted)' }}>總計</span>
              <span className="text-2xl font-bold" style={{ color: 'var(--accent)' }}>${total}</span>
            </div>

            {/* 按鈕區 */}
            <div className="flex flex-col gap-3 mt-auto">
              <button
                onClick={handleManualSubmit}
                disabled={isSubmitting || cart.length === 0 || !selectedDine || !selectedPayment}
                className="w-full py-4 rounded-xl font-semibold text-lg text-white transition-all hover:-translate-y-0.5 hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed"
                style={{
                  background: 'linear-gradient(135deg, var(--accent) 0%, var(--accent-dark) 100%)',
                }}
              >
                {isSubmitting ? '處理中...' : '確認送出'}
              </button>
              <button
                onClick={handleBack}
                className="w-full py-2.5 rounded-lg text-sm text-center transition-colors"
                style={{
                  border: '1px solid var(--border-color)',
                  color: 'var(--text-muted)',
                  backgroundColor: 'transparent',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--accent)';
                  e.currentTarget.style.color = 'var(--accent)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--border-color)';
                  e.currentTarget.style.color = 'var(--text-muted)';
                }}
              >
                返回
              </button>
            </div>
          </motion.div>
        )}

        {/* 完成畫面（AI 和手動結帳都會到這裡） */}
        {checkoutStep === 2 && orderResult && (
          <motion.div
            key="complete"
            variants={stepVariants}
            initial="enter"
            animate="center"
            exit="exit"
            transition={{ duration: 0.25 }}
            className="flex-1 flex flex-col items-center justify-center text-center"
          >
            <div className="text-5xl mb-4">✅</div>
            <h2 className="text-2xl font-semibold mb-6" style={{ color: 'var(--text-color)' }}>
              訂單完成
            </h2>

            {/* 取餐號碼 */}
            <div
              className="rounded-2xl px-12 py-6 mb-6"
              style={{
                backgroundColor: 'var(--background)',
                boxShadow: '0 4px 16px rgba(114, 157, 173, 0.1)',
              }}
            >
              <p className="text-sm mb-2" style={{ color: 'var(--text-muted)' }}>取餐號碼</p>
              <p
                className="text-5xl font-bold"
                style={{
                  color: 'var(--accent)',
                  textShadow: '0 0 30px rgba(114, 157, 173, 0.25)',
                }}
              >
                {orderResult.order_number}
              </p>
            </div>

            {/* 品項明細 */}
            {orderResult.items_display.length > 0 && (
              <div
                className="w-full max-w-sm rounded-xl p-4 mb-4 text-left"
                style={{ backgroundColor: 'var(--background)' }}
              >
                {orderResult.items_display.map((item, i) => (
                  <div
                    key={i}
                    className="flex justify-between py-2"
                    style={{ borderBottom: i < orderResult.items_display.length - 1 ? '1px solid var(--border-color)' : 'none' }}
                  >
                    <span style={{ color: 'var(--text-color)' }}>
                      {item.name} {item.quantity > 1 ? `x${item.quantity}` : ''}
                    </span>
                    <span className="font-medium" style={{ color: 'var(--accent)' }}>${item.subtotal}</span>
                  </div>
                ))}
                <div className="flex justify-between pt-3 mt-2 font-semibold text-lg" style={{ borderTop: '2px solid var(--border-color)' }}>
                  <span style={{ color: 'var(--text-color)' }}>總計</span>
                  <span style={{ color: 'var(--accent)' }}>${orderResult.total}</span>
                </div>
              </div>
            )}

            {/* 用餐/付款資訊 */}
            <p className="mb-4 text-sm" style={{ color: 'var(--text-muted)' }}>
              {orderResult.dine_type === 'dine-in' ? '內用' : '外帶'} / {orderResult.payment_method === 'cash' ? '現金' : 'Line Pay'}
            </p>

            {/* Line Pay QR Code */}
            {(orderResult.payment_method === 'line_pay' || orderResult.payment_method === 'mobile') && (
              <div className="mb-6 flex flex-col items-center">
                <p className="text-sm mb-2" style={{ color: 'var(--text-muted)' }}>Line Pay 掃碼付款</p>
                <div
                  className="w-40 h-40 rounded-xl flex items-center justify-center"
                  style={{ backgroundColor: 'var(--background)', border: '2px dashed var(--border-color)' }}
                >
                  <span className="text-4xl">📱</span>
                </div>
              </div>
            )}

            {/* 開始新訂單按鈕 */}
            <button
              onClick={handleNewOrder}
              className="px-10 py-3 rounded-xl font-semibold text-lg transition-all hover:shadow-md"
              style={{
                border: '2px solid var(--accent)',
                color: 'var(--accent)',
                backgroundColor: 'transparent',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.backgroundColor = 'var(--accent)';
                e.currentTarget.style.color = 'white';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.backgroundColor = 'transparent';
                e.currentTarget.style.color = 'var(--accent)';
              }}
            >
              開始新訂單（{countdown}s）
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
