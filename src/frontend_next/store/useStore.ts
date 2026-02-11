// src/frontend_next/store/useStore.ts
import { create } from 'zustand';
import { AppState, AppStatus, CartItem, CheckoutStep, OrderResult } from '../types';

// 生成唯一的工作階段 ID
const generateSessionId = () => 'session-' + Date.now();

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

  // VAD
  vadEnabled: true,

  // Actions - 語音和訂購
  setStatus: (status: AppStatus) => set({ status }),
  setCart: (cart: CartItem[], total: number) => set({ cart, total }),
  setTranscript: (transcript: string) => set({ transcript }),
  clearCart: () => set({ cart: [], total: 0 }),

  // Actions - 結帳
  // setOrderResult 會同時更新結帳步驟到第 2 步（完成畫面）
  setCheckoutStep: (checkoutStep: CheckoutStep) => set({ checkoutStep }),
  setOrderResult: (result: OrderResult) => set({ orderResult: result, checkoutStep: 2 }),
  resetCheckout: () => set({
    checkoutStep: 0,
    orderResult: null,
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
  }),
  setVadEnabled: (vadEnabled: boolean) => set({ vadEnabled }),
}));
