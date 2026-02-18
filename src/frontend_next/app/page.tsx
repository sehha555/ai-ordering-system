'use client';

import { useStore } from '../store/useStore';
import VoiceController from '../components/VoiceController';
import LiveReceipt from '../components/LiveReceipt';
import MenuDisplay from '../components/MenuDisplay';
import CheckoutFlow from '../components/CheckoutFlow';
import Toast from '../components/Toast';

export default function Home() {
  const { checkoutStep } = useStore();

  return (
    <div className="h-screen w-screen flex overflow-hidden" style={{ backgroundColor: '#f4f7f8' }}>
      <Toast />
      {/* 左側：菜單區域 (50%) */}
      <div
        className="w-1/2 flex flex-col"
        style={{ borderRight: '1px solid #d0dce0', backgroundColor: '#f4f7f8' }}
      >
        {/* 標題 */}
        <header
          className="flex items-center justify-between px-6 py-4"
          style={{
            background: 'linear-gradient(135deg, #ffffff 0%, #e8eef0 100%)',
            borderBottom: '1px solid #d0dce0',
          }}
        >
          <div className="flex items-center gap-3">
            <span className="text-3xl">🍙</span>
            <h1
              className="text-2xl font-bold"
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

        {/* 菜單內容 */}
        <div className="flex-1 overflow-hidden">
          <MenuDisplay />
        </div>
      </div>

      {/* 右側：點餐互動區 (50%) */}
      <div className="w-1/2 flex flex-col" style={{ backgroundColor: '#e8eef0' }}>
        {checkoutStep > 0 ? (
          <CheckoutFlow />
        ) : (
          <>
            {/* 語音控制區 */}
            <div className="flex-1 flex flex-col items-center justify-center px-8">
              <div
                className="rounded-3xl shadow-lg p-8 w-full max-w-md"
                style={{ backgroundColor: 'white' }}
              >
                <h2
                  className="text-center text-lg font-medium mb-6"
                  style={{ color: '#5a6b70' }}
                >
                  語音點餐
                </h2>
                <VoiceController />
              </div>

              {/* 使用提示 */}
              <div className="mt-5 flex gap-4 text-sm" style={{ color: '#8a9a9f' }}>
                <div className="flex items-center gap-2">
                  <span
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: '#4a9d68' }}
                  />
                  <span>聆聽中</span>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: '#c49a30' }}
                  />
                  <span>處理中</span>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className="w-3 h-3 rounded-full"
                    style={{ backgroundColor: '#5a8494' }}
                  />
                  <span>回覆中</span>
                </div>
              </div>
            </div>

            {/* 購物車 */}
            <div className="px-8 pb-6">
              <LiveReceipt />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
