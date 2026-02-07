'use client';

import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';

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
    dineType,
    paymentMethod,
    orderNumber,
    setCheckoutStep,
    setDineType,
    setPaymentMethod,
    setOrderNumber,
    resetSession,
  } = useStore();

  // Step 1: Select dine type
  const handleDineType = (type: 'dine-in' | 'take-out') => {
    setDineType(type);
    setCheckoutStep(2);
  };

  // Step 2: Select payment method
  const handlePayment = (method: 'cash' | 'mobile') => {
    setPaymentMethod(method);
    setCheckoutStep(3);
  };

  // Step 3: Confirm order
  const handleConfirm = async () => {
    const num = String(Math.floor(Math.random() * 100) + 1).padStart(2, '0');
    setOrderNumber(num);
    setCheckoutStep(4);
  };

  // Step 4: New order
  const handleNewOrder = () => {
    resetSession();
  };

  // Go back
  const handleBack = () => {
    if (checkoutStep > 1) {
      setCheckoutStep((checkoutStep - 1) as 1 | 2 | 3);
    } else {
      setCheckoutStep(0);
    }
  };

  return (
    <div className="flex-1 flex flex-col p-6 relative">
      {/* Step progress */}
      <div className="flex items-center justify-center gap-2 mb-8">
        {[1, 2, 3, 4].map((step) => (
          <div key={step} className="flex items-center gap-2">
            <div
              className="w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium"
              style={{
                backgroundColor: checkoutStep >= step ? '#729DAD' : '#e8eef0',
                color: checkoutStep >= step ? 'white' : '#8a9a9f',
              }}
            >
              {step}
            </div>
            {step < 4 && (
              <div
                className="w-8 h-0.5"
                style={{ backgroundColor: checkoutStep > step ? '#729DAD' : '#d0dce0' }}
              />
            )}
          </div>
        ))}
      </div>

      {/* Steps content */}
      <div className="flex-1 flex flex-col">
        <AnimatePresence mode="wait">
          {/* Step 1: Dine type */}
          {checkoutStep === 1 && (
            <motion.div
              key="step1"
              variants={stepVariants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.25 }}
              className="flex-1 flex flex-col"
            >
              <h2 className="text-2xl font-semibold text-center mb-8" style={{ color: '#2c3e42' }}>
                用餐方式
              </h2>
              <div className="flex-1 flex items-center justify-center gap-6">
                <button
                  onClick={() => handleDineType('dine-in')}
                  className="w-44 h-44 flex flex-col items-center justify-center gap-4 rounded-2xl transition-all hover:-translate-y-1"
                  style={{
                    backgroundColor: 'white',
                    border: '2px solid #d0dce0',
                    boxShadow: '0 4px 12px rgba(114, 157, 173, 0.1)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = '#729DAD';
                    e.currentTarget.style.backgroundColor = 'rgba(114, 157, 173, 0.15)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = '#d0dce0';
                    e.currentTarget.style.backgroundColor = 'white';
                  }}
                >
                  <span className="text-5xl">🍽️</span>
                  <span className="text-lg font-semibold" style={{ color: '#2c3e42' }}>內用</span>
                </button>
                <button
                  onClick={() => handleDineType('take-out')}
                  className="w-44 h-44 flex flex-col items-center justify-center gap-4 rounded-2xl transition-all hover:-translate-y-1"
                  style={{
                    backgroundColor: 'white',
                    border: '2px solid #d0dce0',
                    boxShadow: '0 4px 12px rgba(114, 157, 173, 0.1)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = '#729DAD';
                    e.currentTarget.style.backgroundColor = 'rgba(114, 157, 173, 0.15)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = '#d0dce0';
                    e.currentTarget.style.backgroundColor = 'white';
                  }}
                >
                  <span className="text-5xl">🥡</span>
                  <span className="text-lg font-semibold" style={{ color: '#2c3e42' }}>外帶</span>
                </button>
              </div>
            </motion.div>
          )}

          {/* Step 2: Payment */}
          {checkoutStep === 2 && (
            <motion.div
              key="step2"
              variants={stepVariants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.25 }}
              className="flex-1 flex flex-col"
            >
              <h2 className="text-2xl font-semibold text-center mb-8" style={{ color: '#2c3e42' }}>
                付款方式
              </h2>
              <div className="flex-1 flex items-center justify-center gap-6">
                <button
                  onClick={() => handlePayment('cash')}
                  className="w-44 h-44 flex flex-col items-center justify-center gap-4 rounded-2xl transition-all hover:-translate-y-1"
                  style={{
                    backgroundColor: 'white',
                    border: '2px solid #d0dce0',
                    boxShadow: '0 4px 12px rgba(114, 157, 173, 0.1)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = '#729DAD';
                    e.currentTarget.style.backgroundColor = 'rgba(114, 157, 173, 0.15)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = '#d0dce0';
                    e.currentTarget.style.backgroundColor = 'white';
                  }}
                >
                  <span className="text-5xl">💵</span>
                  <span className="text-lg font-semibold" style={{ color: '#2c3e42' }}>現金</span>
                </button>
                <button
                  onClick={() => handlePayment('mobile')}
                  className="w-44 h-44 flex flex-col items-center justify-center gap-4 rounded-2xl transition-all hover:-translate-y-1"
                  style={{
                    backgroundColor: 'white',
                    border: '2px solid #d0dce0',
                    boxShadow: '0 4px 12px rgba(114, 157, 173, 0.1)',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = '#729DAD';
                    e.currentTarget.style.backgroundColor = 'rgba(114, 157, 173, 0.15)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = '#d0dce0';
                    e.currentTarget.style.backgroundColor = 'white';
                  }}
                >
                  <span className="text-5xl">📱</span>
                  <span className="text-lg font-semibold" style={{ color: '#2c3e42' }}>行動支付</span>
                </button>
              </div>
            </motion.div>
          )}

          {/* Step 3: Confirm */}
          {checkoutStep === 3 && (
            <motion.div
              key="step3"
              variants={stepVariants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.25 }}
              className="flex-1 flex flex-col"
            >
              <h2 className="text-2xl font-semibold text-center mb-6" style={{ color: '#2c3e42' }}>
                確認訂單
              </h2>

              {/* Order summary */}
              <div
                className="rounded-xl p-4 mb-4 max-h-48 overflow-y-auto"
                style={{ backgroundColor: '#f4f7f8' }}
              >
                {cart.map((item, i) => (
                  <div
                    key={i}
                    className="flex justify-between py-2"
                    style={{ borderBottom: i < cart.length - 1 ? '1px solid #d0dce0' : 'none' }}
                  >
                    <span style={{ color: '#2c3e42' }}>{item.name} x{item.quantity}</span>
                    <span className="font-medium" style={{ color: '#729DAD' }}>${item.price}</span>
                  </div>
                ))}
              </div>

              {/* Order details */}
              <div
                className="rounded-xl p-4 mb-6"
                style={{ backgroundColor: '#f4f7f8' }}
              >
                <div className="flex justify-between py-2" style={{ borderBottom: '1px solid #d0dce0' }}>
                  <span style={{ color: '#5a6b70' }}>用餐方式</span>
                  <span style={{ color: '#2c3e42' }}>{dineType === 'dine-in' ? '內用' : '外帶'}</span>
                </div>
                <div className="flex justify-between py-2" style={{ borderBottom: '1px solid #d0dce0' }}>
                  <span style={{ color: '#5a6b70' }}>付款方式</span>
                  <span style={{ color: '#2c3e42' }}>{paymentMethod === 'cash' ? '現金' : '行動支付'}</span>
                </div>
                <div className="flex justify-between py-3 font-semibold text-lg">
                  <span style={{ color: '#2c3e42' }}>總計</span>
                  <span style={{ color: '#729DAD', fontSize: '1.3rem' }}>${total}</span>
                </div>
              </div>

              <button
                onClick={handleConfirm}
                className="w-full py-4 rounded-xl font-semibold text-lg text-white transition-all hover:-translate-y-0.5 hover:shadow-lg"
                style={{
                  background: 'linear-gradient(135deg, #729DAD 0%, #5a8494 100%)',
                }}
              >
                確認送出
              </button>
            </motion.div>
          )}

          {/* Step 4: Complete */}
          {checkoutStep === 4 && (
            <motion.div
              key="step4"
              variants={stepVariants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{ duration: 0.25 }}
              className="flex-1 flex flex-col items-center justify-center text-center"
            >
              <div className="text-6xl mb-5">✅</div>
              <h2 className="text-2xl font-semibold mb-8" style={{ color: '#2c3e42' }}>
                訂單完成
              </h2>

              <div
                className="rounded-2xl px-12 py-6 mb-6"
                style={{
                  backgroundColor: '#f4f7f8',
                  boxShadow: '0 4px 16px rgba(114, 157, 173, 0.1)',
                }}
              >
                <p className="text-sm mb-2" style={{ color: '#5a6b70' }}>取餐號碼</p>
                <p
                  className="text-5xl font-bold"
                  style={{
                    color: '#729DAD',
                    textShadow: '0 0 30px rgba(114, 157, 173, 0.25)',
                  }}
                >
                  {orderNumber}
                </p>
              </div>

              <p className="mb-8" style={{ color: '#5a6b70' }}>
                請保留此畫面，稍後取餐
              </p>

              <button
                onClick={handleNewOrder}
                className="px-10 py-3 rounded-xl font-semibold text-lg transition-all hover:shadow-md"
                style={{
                  border: '2px solid #729DAD',
                  color: '#729DAD',
                  backgroundColor: 'transparent',
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = '#729DAD';
                  e.currentTarget.style.color = 'white';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent';
                  e.currentTarget.style.color = '#729DAD';
                }}
              >
                開始新訂單
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Back button */}
      {checkoutStep > 0 && checkoutStep < 4 && (
        <button
          onClick={handleBack}
          className="absolute bottom-6 left-6 px-6 py-2.5 rounded-lg text-sm transition-colors"
          style={{
            border: '1px solid #d0dce0',
            color: '#5a6b70',
            backgroundColor: 'transparent',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = '#729DAD';
            e.currentTarget.style.color = '#729DAD';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = '#d0dce0';
            e.currentTarget.style.color = '#5a6b70';
          }}
        >
          返回
        </button>
      )}
    </div>
  );
}
