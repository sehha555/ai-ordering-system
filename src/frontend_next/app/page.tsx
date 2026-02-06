'use client';

import VoiceController from '../components/VoiceController';
import LiveReceipt from '../components/LiveReceipt';

export default function Home() {
  return (
    <div className="min-h-screen bg-[#F5F7F8]">
      {/* 頂部導航 */}
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-3xl">🍙</span>
            <h1 className="text-xl font-bold text-gray-800">源飯糰</h1>
          </div>
          <p className="text-sm text-gray-500">語音點餐系統</p>
        </div>
      </header>

      {/* 主內容 */}
      <main className="max-w-7xl mx-auto px-4 py-8">
        <div className="flex flex-col lg:flex-row gap-8 items-start justify-center">
          {/* 左側：語音控制區 */}
          <div className="flex-1 flex flex-col items-center justify-center min-h-[500px]">
            <div className="bg-white rounded-3xl shadow-lg p-8 w-full max-w-md">
              <h2 className="text-center text-lg font-medium text-gray-600 mb-8">
                語音點餐
              </h2>
              <VoiceController />
              <div className="mt-8 text-center">
                <p className="text-sm text-gray-400">
                  試試說：「我要一個紫米傳統飯糰」
                </p>
              </div>
            </div>

            {/* 使用提示 */}
            <div className="mt-6 flex gap-4 text-sm text-gray-500">
              <div className="flex items-center gap-2">
                <kbd className="px-2 py-1 bg-gray-100 rounded text-xs">Space</kbd>
                <span>按住說話</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 bg-green-400 rounded-full"></span>
                <span>聆聽中</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 bg-blue-400 rounded-full"></span>
                <span>回覆中</span>
              </div>
            </div>
          </div>

          {/* 右側：即時收據 */}
          <div className="w-full lg:w-auto">
            <LiveReceipt />
          </div>
        </div>
      </main>

      {/* 底部資訊 */}
      <footer className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-100 py-3">
        <div className="max-w-7xl mx-auto px-4 flex items-center justify-between text-sm text-gray-400">
          <p>Voice Dashboard v1.0</p>
          <p>Powered by Next.js + FastAPI</p>
        </div>
      </footer>
    </div>
  );
}
