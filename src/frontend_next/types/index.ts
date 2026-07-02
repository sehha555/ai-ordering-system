// src/frontend_next/types/index.ts

export const SSE_EVENTS = {
  THINKING: 'thinking',
  TRANSCRIPTION: 'transcription',
  CART_UPDATE: 'cart_update',
  ORDER_COMPLETE: 'order_complete',
  CHECKOUT_PREVIEW: 'checkout_preview',
  STATUS: 'status',
  TEXT_DELTA: 'text_delta',
  TTS_TEXT: 'tts_text',
  AUDIO_CHUNK: 'audio_chunk',
  ERROR: 'error',
  DONE: 'done',
} as const;

export interface CartItem {
  name: string;
  details: string;
  price: number;
  quantity: number;
  price_pending?: boolean; // 客製化無對應價格，待店員確認
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
  payment_status?: string; // PAID（已付）/ UNPAID（待店員結算）
  price_pending?: boolean; // 含客製待確認品項：未收款，待店員補價
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

  // 當前活躍的 AnalyserNode（麥克風或 TTS），供 AudioVisualizer 頻譜驅動
  // 不寫進 React state，避免每幀重渲染；AudioVisualizer 透過 ref 同步讀取
  analyser: AnalyserNode | null;

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

  // Actions - 頻譜分析器
  setAnalyser: (a: AnalyserNode | null) => void;
  // 只在 store 中的 analyser 是 owner 時才清除（防 mic/TTS 兩來源互相蓋掉）
  clearAnalyser: (owner: AnalyserNode | null) => void;

  // Actions - 網路連線
  setConnectionError: (error: string | null) => void;
}
