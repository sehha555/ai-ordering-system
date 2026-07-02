// src/frontend_next/store/useStore.ts
import { create } from 'zustand';
import { AppState, AppStatus, CartItem, CheckoutPreview, CheckoutStep, OrderResult } from '../types';

// 生成唯一的工作階段 ID
const generateSessionId = () => crypto.randomUUID();

export const useStore = create<AppState>((set) => ({
  // 語音和訂購
  status: 'idle',
  cart: [],
  total: 0,
  transcript: '',
  sessionId: generateSessionId(),

  // 結帳
  checkoutStep: 0,
  orderResult: null,
  checkoutPreview: null,

  // VAD
  vadEnabled: false,

  // 網路連線
  connectionError: null,

  // AI 回覆文字
  aiReply: '',

  // 對話歷史
  messages: [],

  // Streaming 文字
  streamingText: '',

  // 麥克風音量
  volume: 0,

  // 當前活躍的 AnalyserNode（null = 無頻譜，fallback 到 volume 模式）
  analyser: null,

  // Actions - 語音和訂購
  setStatus: (status: AppStatus) => set({ status }),
  setCart: (cart: CartItem[], total: number) => set({ cart, total }),
  setTranscript: (transcript: string) => set({ transcript }),
  clearCart: () => set({ cart: [], total: 0 }),

  // Actions - 結帳
  // setOrderResult 會同時更新結帳步驟到第 2 步（完成畫面）
  setCheckoutStep: (checkoutStep: CheckoutStep) => set({ checkoutStep }),
  setOrderResult: (result: OrderResult) => set({ orderResult: result, checkoutStep: 2 }),
  setCheckoutPreview: (checkoutPreview: CheckoutPreview | null) => set({ checkoutPreview, checkoutStep: 1 }),
  resetCheckout: () => set({
    checkoutStep: 0,
    orderResult: null,
    checkoutPreview: null,
  }),

  // Actions - 工作階段
  // resetSession 會重置所有狀態並生成新的工作階段 ID
  resetSession: () => set({
    status: 'idle',
    cart: [],
    total: 0,
    transcript: '',
    sessionId: generateSessionId(),
    checkoutStep: 0,
    orderResult: null,
    checkoutPreview: null,
    connectionError: null,
    aiReply: '',
    messages: [],
    streamingText: '',
    volume: 0,
    analyser: null,
  }),
  setVadEnabled: (vadEnabled: boolean) => set({ vadEnabled }),
  setVolume: (volume: number) => set({ volume }),
  setAnalyser: (analyser: AnalyserNode | null) => set({ analyser }),

  // Actions - AI 回覆文字
  setAiReply: (aiReply: string) => set({ aiReply }),

  // Actions - 對話歷史
  addMessage: (role, content) => set((state) => ({
    messages: [...state.messages, {
      id: crypto.randomUUID(),
      role,
      content,
      timestamp: Date.now(),
    }],
    // assistant 訊息送達即接手顯示，清掉串流氣泡（訊息氣泡會從已打字數接續，不重打）
    ...(role === 'assistant' ? { streamingText: '' } : {}),
  })),

  // Actions - Streaming 文字
  appendStreamingText: (chunk) => set((state) => ({
    streamingText: state.streamingText + chunk,
  })),
  clearStreamingText: () => set({ streamingText: '' }),

  // Actions - 網路連線
  setConnectionError: (error: string | null) => set({ connectionError: error }),
}));
