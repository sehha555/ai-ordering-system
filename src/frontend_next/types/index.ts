// src/frontend_next/types/index.ts

export interface CartItem {
  name: string;
  details: string;
  price: number;
  quantity: number;
}

export type AppStatus = 'idle' | 'listening' | 'processing' | 'speaking';

export type CheckoutStep = 0 | 1 | 2 | 3 | 4;
// 0 = not in checkout, 1 = dine type, 2 = payment, 3 = confirm, 4 = complete

export type DineType = 'dine-in' | 'take-out' | null;
export type PaymentMethod = 'cash' | 'mobile' | null;

export interface MenuItem {
  name: string;
  price: number;
}

export interface MenuCategory {
  name: string;
  icon: string;
  items: MenuItem[];
}

export interface AppState {
  // Voice & ordering
  status: AppStatus;
  cart: CartItem[];
  total: number;
  transcript: string;
  sessionId: string;

  // Checkout
  checkoutStep: CheckoutStep;
  dineType: DineType;
  paymentMethod: PaymentMethod;
  orderNumber: string | null;

  // VAD mode
  vadEnabled: boolean;

  // Actions - voice & ordering
  setStatus: (s: AppStatus) => void;
  setCart: (items: CartItem[], total: number) => void;
  setTranscript: (t: string) => void;
  clearCart: () => void;

  // Actions - checkout
  setCheckoutStep: (step: CheckoutStep) => void;
  setDineType: (type: DineType) => void;
  setPaymentMethod: (method: PaymentMethod) => void;
  setOrderNumber: (num: string) => void;
  resetCheckout: () => void;

  // Actions - session
  resetSession: () => void;
  setVadEnabled: (enabled: boolean) => void;
}
