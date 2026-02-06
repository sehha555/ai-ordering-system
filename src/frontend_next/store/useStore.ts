// src/frontend_next/store/useStore.ts
import { create } from 'zustand';
import { AppState, AppStatus, CartItem } from '../types';

export const useStore = create<AppState>((set) => ({
  status: 'idle',
  cart: [],
  total: 0,
  transcript: '',

  setStatus: (status: AppStatus) => set({ status }),

  setCart: (cart: CartItem[], total: number) => set({ cart, total }),

  setTranscript: (transcript: string) => set({ transcript }),

  clearCart: () => set({ cart: [], total: 0 }),
}));
