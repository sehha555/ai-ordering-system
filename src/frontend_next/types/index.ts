// src/frontend_next/types/index.ts

export interface CartItem {
  name: string;
  details: string;
  price: number;
  quantity: number;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

export type AppStatus = 'idle' | 'listening' | 'processing' | 'speaking';

export type CheckoutStep = 0 | 1 | 2;
// 0 = 正常（未結帳）, 1 = 手動結帳頁面（一頁式 fallback）, 2 = 完成畫面

export type DineType = 'dine-in' | 'take-out' | null;
export type PaymentMethod = 'cash' | 'line_pay' | 'mobile' | null;

export interface CheckoutPreview {
  dineType: 'dine-in' | 'take-out';
  paymentMethod: 'cash' | 'line_pay';
}

export interface OrderResult {
  order_number: string;
  total: number;
  item_count: number;
  items_display: Array<{
    name: string;
    quantity: number;
    unit_price: number;
    subtotal: number;
  }>;
  dine_type: string;
  payment_method: string;
}

export interface AppState {
  // 語音和訂購
  status: AppStatus;
  cart: CartItem[];
  total: number;
  transcript: string;
  sessionId: string;

  // 結帳
  checkoutStep: CheckoutStep;
  orderResult: OrderResult | null;
  checkoutPreview: CheckoutPreview | null;
  setCheckoutPreview: (preview: CheckoutPreview | null) => void;

  // VAD 模式
  vadEnabled: boolean;

  // 網路連線
  connectionError: string | null;

  // AI 回覆文字（用於橫幅顯示）
  aiReply: string;

  // 對話歷史
  messages: ChatMessage[];

  // Streaming 文字（LLM 逐 token 累積中）
  streamingText: string;

  // 麥克風音量（0-1，供 AudioVisualizer 使用）
  volume: number;

  // Actions - 語音和訂購
  setStatus: (s: AppStatus) => void;
  setCart: (items: CartItem[], total: number) => void;
  setTranscript: (t: string) => void;
  clearCart: () => void;
  setAiReply: (reply: string) => void;

  // Actions - 結帳
  setCheckoutStep: (step: CheckoutStep) => void;
  setOrderResult: (result: OrderResult) => void;
  resetCheckout: () => void;

  // Actions - 工作階段
  resetSession: () => void;
  setVadEnabled: (enabled: boolean) => void;
  setVolume: (volume: number) => void;

  // Actions - 對話歷史
  addMessage: (role: 'user' | 'assistant', content: string) => void;

  // Actions - Streaming 文字
  appendStreamingText: (chunk: string) => void;
  clearStreamingText: () => void;

  // Actions - 網路連線
  setConnectionError: (error: string | null) => void;
}
