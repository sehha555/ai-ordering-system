// src/frontend_next/store/useStore.ts
import { create } from 'zustand';
import { AppState, AppStatus, CartItem, CheckoutStep, DineType, PaymentMethod } from '../types';

const generateSessionId = () => 'session-' + Date.now();

export const useStore = create<AppState>((set) => ({
  // Voice & ordering
  status: 'idle',
  cart: [],
  total: 0,
  transcript: '',
  sessionId: generateSessionId(),

  // Checkout
  checkoutStep: 0,
  dineType: null,
  paymentMethod: null,
  orderNumber: null,

  // VAD
  vadEnabled: true,

  // Actions - voice & ordering
  setStatus: (status: AppStatus) => set({ status }),
  setCart: (cart: CartItem[], total: number) => set({ cart, total }),
  setTranscript: (transcript: string) => set({ transcript }),
  clearCart: () => set({ cart: [], total: 0 }),

  // Actions - checkout
  setCheckoutStep: (checkoutStep: CheckoutStep) => set({ checkoutStep }),
  setDineType: (dineType: DineType) => set({ dineType }),
  setPaymentMethod: (paymentMethod: PaymentMethod) => set({ paymentMethod }),
  setOrderNumber: (orderNumber: string) => set({ orderNumber }),
  resetCheckout: () => set({
    checkoutStep: 0,
    dineType: null,
    paymentMethod: null,
    orderNumber: null,
  }),

  // Actions - session
  resetSession: () => set({
    status: 'idle',
    cart: [],
    total: 0,
    transcript: '',
    sessionId: generateSessionId(),
    checkoutStep: 0,
    dineType: null,
    paymentMethod: null,
    orderNumber: null,
  }),
  setVadEnabled: (vadEnabled: boolean) => set({ vadEnabled }),
}));
