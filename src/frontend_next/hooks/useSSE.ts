import { useRef, useCallback, RefObject } from 'react';
import { useStore } from '../store/useStore';
import type { AppStatus, CartItem } from '../types';

const SSE_TIMEOUT = 30000;
const AUTO_PROMPT_DELAY = 3000;
const AUTO_PROMPT_TEXT = '這樣就好嗎？';

// SSE 行解析：回傳 currentEvent 供下次呼叫繼承，避免跨 chunk 時 event 被重置
export function parseSSELines(
  lines: string[],
  onEvent: (event: string, data: string) => void,
  currentEvent = ''
): string {
  for (const line of lines) {
    if (line.startsWith('event: ')) {
      currentEvent = line.slice(7);
    } else if (line.startsWith('data: ')) {
      onEvent(currentEvent, line.slice(6));
    }
  }
  return currentEvent;
}

interface UseSSEProps {
  sessionId: string;
  vadEnabled: boolean;
  isListeningRef: RefObject<boolean>;
  setStatus: (s: AppStatus) => void;
  setTranscript: (t: string) => void;
  setCart: (items: CartItem[], total: number) => void;
  setAiReply: (r: string) => void;
  startVADLoop: () => void;
  playNextAudio: () => void;
  audioQueueRef: RefObject<unknown[]>;
  isPlayingRef: RefObject<boolean>;
  streamDoneRef: RefObject<boolean>;
  autoPromptTimerRef: RefObject<ReturnType<typeof setTimeout> | null>;
}

export function useSSE({
  sessionId,
  vadEnabled,
  isListeningRef,
  setStatus,
  setTranscript,
  setCart,
  setAiReply,
  startVADLoop,
  playNextAudio,
  audioQueueRef,
  isPlayingRef,
  streamDoneRef,
  autoPromptTimerRef,
}: UseSSEProps) {
  // ref 存放 handleSSEEvent，讓 sendAudioToServer/sendTextToServer 不受宣告順序限制
  const handleSSEEventRef = useRef<((event: string, dataStr: string) => void) | undefined>(undefined);
  // ref 存放 sendTextToServer，讓 autoPrompt timer 永遠呼叫最新版本
  const sendTextRef = useRef<((text: string) => Promise<void>) | undefined>(undefined);

  // 送純文字到後端（/api/text-chat），用於自動追問場景
  const sendTextToServer = useCallback(async (text: string) => {
    if (vadEnabled) {
      // 暫停 VAD，避免在處理時誤觸發（需要 vadLoopRef，但由 VAD hook 管理 — 透過 startVADLoop 狀態判斷）
    }

    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), SSE_TIMEOUT);

    try {
      setStatus('processing');
      streamDoneRef.current = false;

      const response = await fetch('/api/text-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, session_id: sessionId }),
        signal: abortController.signal,
      });

      if (!response.ok) throw new Error(`Server error: ${response.status}`);

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      clearTimeout(timeoutId);

      const decoder = new TextDecoder();
      let buffer = '';
      let sseEvent = '';
      const onEvent = (evt: string, data: string) => handleSSEEventRef.current?.(evt, data);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        sseEvent = parseSSELines(lines, onEvent, sseEvent);
      }

      if (buffer.trim()) {
        parseSSELines(buffer.split('\n'), onEvent, sseEvent);
      }

      streamDoneRef.current = true;
      if (audioQueueRef.current.length === 0 && !isPlayingRef.current) {
        setStatus('idle');
        if (vadEnabled && isListeningRef.current) {
          startVADLoop();
        }
      }
    } catch (error) {
      clearTimeout(timeoutId);
      console.error('[自動追問] 文字傳送失敗:', error);
      streamDoneRef.current = true;
      const isTimeout = (error as Error).name === 'AbortError';
      useStore.getState().setConnectionError(
        isTimeout ? '回應超時，請再試一次' : '自動追問傳送失敗，請稍後再試'
      );
      setStatus('idle');
      if (vadEnabled && isListeningRef.current) {
        startVADLoop();
      }
    }
  }, [setStatus, vadEnabled, sessionId, startVADLoop, streamDoneRef, audioQueueRef, isPlayingRef, isListeningRef]);
  sendTextRef.current = sendTextToServer;

  // 送音訊到後端（/api/voice-chat）
  const sendAudioToServer = useCallback(async (audioBlob: Blob) => {
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), SSE_TIMEOUT);

    try {
      setStatus('processing');
      streamDoneRef.current = false;

      const formData = new FormData();
      formData.append('audio', audioBlob, 'recording.webm');
      formData.append('session_id', sessionId);

      const response = await fetch('/api/voice-chat', {
        method: 'POST',
        body: formData,
        signal: abortController.signal,
      });

      if (!response.ok) throw new Error(`Server error: ${response.status}`);

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      clearTimeout(timeoutId);

      const decoder = new TextDecoder();
      let buffer = '';
      let sseEvent = '';
      const onEvent = (evt: string, data: string) => handleSSEEventRef.current?.(evt, data);

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        sseEvent = parseSSELines(lines, onEvent, sseEvent);
      }

      if (buffer.trim()) {
        parseSSELines(buffer.split('\n'), onEvent, sseEvent);
      }

      streamDoneRef.current = true;
      if (audioQueueRef.current.length === 0 && !isPlayingRef.current) {
        setStatus('idle');
        if (vadEnabled && isListeningRef.current) {
          startVADLoop();
        }
      }
    } catch (error) {
      clearTimeout(timeoutId);
      console.error('[VoiceController] 音訊傳送失敗:', error);
      streamDoneRef.current = true;
      const isTimeout = (error as Error).name === 'AbortError';
      useStore.getState().setConnectionError(
        isTimeout ? '回應超時，請再試一次' : '連線失敗，請稍後再試'
      );
      setStatus('idle');
      if (vadEnabled && isListeningRef.current) {
        startVADLoop();
      }
    }
  }, [setStatus, playNextAudio, vadEnabled, startVADLoop, sessionId, streamDoneRef, audioQueueRef, isPlayingRef, isListeningRef]);

  const handleSSEEvent = useCallback((event: string, dataStr: string) => {
    try {
      switch (event) {
        case 'thinking':
          setStatus('processing');
          break;
        case 'transcription': {
          const transcriptionData = JSON.parse(dataStr);
          setTranscript(transcriptionData.text || '');
          break;
        }
        case 'cart_update': {
          const cartData = JSON.parse(dataStr);
          setCart(cartData.items || [], cartData.total || 0);
          break;
        }
        case 'order_complete': {
          const result = JSON.parse(dataStr);
          useStore.getState().setOrderResult(result);
          useStore.getState().clearCart();
          break;
        }
        case 'checkout_preview': {
          const { dine_type, payment_method } = JSON.parse(dataStr) as { dine_type: string; payment_method: string };
          useStore.getState().setCheckoutPreview({
            dineType: dine_type as 'dine-in' | 'take-out',
            paymentMethod: payment_method as 'cash' | 'line_pay',
          });
          break;
        }
        case 'status':
          setStatus('processing');
          break;
        case 'tts_text': {
          const ttsData = JSON.parse(dataStr);
          setAiReply(ttsData.text || '');
          break;
        }
        case 'audio_chunk': {
          const audioData = JSON.parse(dataStr);
          audioQueueRef.current.push(audioData);
          if (!isPlayingRef.current) {
            setStatus('speaking');
            playNextAudio();
          }
          break;
        }
      }
    } catch (error) {
      console.error('Error parsing SSE event:', event, error);
    }
  }, [setStatus, setTranscript, setCart, setAiReply, playNextAudio, audioQueueRef, isPlayingRef]);
  handleSSEEventRef.current = handleSSEEvent;

  // 自動追問：speaking → idle 後，若購物車有品項則觸發
  const triggerAutoPromptIfNeeded = useCallback(() => {
    const { cart: currentCart } = useStore.getState();
    if (currentCart.length > 0) {
      console.log('[自動追問] speaking → idle，購物車有品項，啟動 3 秒計時');
      autoPromptTimerRef.current = setTimeout(() => {
        autoPromptTimerRef.current = null;
        const currentState = useStore.getState();
        if (currentState.status === 'idle' && currentState.cart.length > 0) {
          console.log('[自動追問] 觸發，送出:', AUTO_PROMPT_TEXT);
          sendTextRef.current?.(AUTO_PROMPT_TEXT);
        }
      }, AUTO_PROMPT_DELAY);
    }
  }, [autoPromptTimerRef]);

  return {
    sendAudioToServer,
    sendTextToServer,
    handleSSEEvent,
    handleSSEEventRef,
    triggerAutoPromptIfNeeded,
  };
}
