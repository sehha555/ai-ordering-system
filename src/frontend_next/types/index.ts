// src/frontend_next/types/index.ts

export interface CartItem {
  name: string;
  details: string; // e.g. "大杯, 半糖"
  price: number;
  quantity: number;
}

export type AppStatus = 'idle' | 'listening' | 'processing' | 'speaking';

export interface AppState {
  status: AppStatus;
  cart: CartItem[];
  total: number;
  transcript: string;
  setStatus: (s: AppStatus) => void;
  setCart: (items: CartItem[], total: number) => void;
  setTranscript: (t: string) => void;
  clearCart: () => void;
}
