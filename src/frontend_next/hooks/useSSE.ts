import { useRef, useCallback, RefObject } from 'react';
import { useStore } from '../store/useStore';
import type { AppStatus, CartItem } from '../types';
import { SSE_EVENTS } from '../types';

const SSE_TIMEOUT = 90000; // 90s — 後端 LLM 每步最多 25s，多步 tool call 需更長等待

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
}: UseSSEProps) {
  // ref 存放 handleSSEEvent，讓 sendAudioToServer/sendTextToServer 不受宣告順序限制
  const handleSSEEventRef = useRef<((event: string, dataStr: string) => void) | undefined>(undefined);

  // 共用 SSE stream 讀取邏輯：接受 fetchFn 建立 request，errorLabel 用於 console.error
  const streamSSE = useCallback(async (
    fetchFn: (signal: AbortSignal) => Promise<Response>,
    errorLabel: string,
  ) => {
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), SSE_TIMEOUT);

    try {
      setStatus('processing');
      streamDoneRef.current = false;

      const response = await fetchFn(abortController.signal);

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
      useStore.getState().clearStreamingText();
      if (audioQueueRef.current.length === 0 && !isPlayingRef.current) {
        setStatus('idle');
        if (vadEnabled && isListeningRef.current) {
          startVADLoop();
        }
      }
    } catch (error) {
      clearTimeout(timeoutId);
      console.error(`[${errorLabel}] 傳送失敗:`, error);
      streamDoneRef.current = true;
      useStore.getState().clearStreamingText();
      const isTimeout = (error as Error).name === 'AbortError';
      useStore.getState().setConnectionError(
        isTimeout ? '回應超時，請再試一次' : `${errorLabel} 傳送失敗，請稍後再試`
      );
      // 播放中時讓 playback completion 處理 idle 轉換，避免重複觸發 autoPrompt
      if (!isPlayingRef.current) {
        setStatus('idle');
        if (vadEnabled && isListeningRef.current) {
          startVADLoop();
        }
      }
    }
  }, [setStatus, vadEnabled, startVADLoop, streamDoneRef, audioQueueRef, isPlayingRef, isListeningRef]);

  // 送純文字到後端（/api/text-chat），用於自動追問場景
  const sendTextToServer = useCallback(async (text: string) => {
    await streamSSE(
      (signal) => fetch('/api/text-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, session_id: sessionId }),
        signal,
      }),
      '自動追問',
    );
  }, [streamSSE, sessionId]);

  // 送音訊到後端（/api/voice-chat）
  const sendAudioToServer = useCallback(async (audioBlob: Blob) => {
    await streamSSE(
      (signal) => {
        const formData = new FormData();
        formData.append('file', audioBlob, 'recording.webm');
        formData.append('session_id', sessionId);
        return fetch('/api/voice-chat', {
          method: 'POST',
          body: formData,
          signal,
        });
      },
      'VoiceController',
    );
  }, [streamSSE, sessionId]);

  const handleSSEEvent = useCallback((event: string, dataStr: string) => {
    try {
      switch (event) {
        case SSE_EVENTS.THINKING:
          setStatus('processing');
          break;
        case SSE_EVENTS.TRANSCRIPTION: {
          const transcriptionData = JSON.parse(dataStr);
          const transcriptionText = transcriptionData.text || '';
          setTranscript(transcriptionText);
          if (transcriptionText) useStore.getState().addMessage('user', transcriptionText);
          break;
        }
        case SSE_EVENTS.CART_UPDATE: {
          const cartData = JSON.parse(dataStr);
          setCart(cartData.items || [], cartData.total || 0);
          break;
        }
        case SSE_EVENTS.ORDER_COMPLETE: {
          const result = JSON.parse(dataStr);
          useStore.getState().setOrderResult(result);
          useStore.getState().clearCart();
          break;
        }
        case SSE_EVENTS.CHECKOUT_PREVIEW: {
          const { dine_type, payment_method } = JSON.parse(dataStr) as { dine_type: string; payment_method: string };
          useStore.getState().setCheckoutPreview({
            dineType: dine_type as 'dine-in' | 'take-out',
            paymentMethod: payment_method as 'cash' | 'line_pay',
          });
          break;
        }
        case SSE_EVENTS.STATUS:
          setStatus('processing');
          break;
        case SSE_EVENTS.TEXT_DELTA: {
          const deltaData = JSON.parse(dataStr);
          const chunk = deltaData.text || '';
          if (chunk) useStore.getState().appendStreamingText(chunk);
          break;
        }
        case SSE_EVENTS.TTS_TEXT: {
          const ttsData = JSON.parse(dataStr);
          const ttsText = ttsData.text || '';
          setAiReply(ttsText);
          if (ttsText) useStore.getState().addMessage('assistant', ttsText);
          break;
        }
        case SSE_EVENTS.AUDIO_CHUNK: {
          const audioData = JSON.parse(dataStr);
          audioQueueRef.current.push(audioData);
          if (!isPlayingRef.current) {
            setStatus('speaking');
            playNextAudio();
          }
          break;
        }
        case SSE_EVENTS.ERROR: {
          let msg = '處理失敗，請再試一次';
          try {
            const errData = JSON.parse(dataStr);
            msg = errData.message || msg;
          } catch {
            msg = dataStr || msg;
          }
          useStore.getState().setConnectionError(msg);
          useStore.getState().clearStreamingText();
          setAiReply('');
          break;
        }
      }
    } catch (error) {
      console.error('Error parsing SSE event:', event, error);
    }
  }, [setStatus, setTranscript, setCart, setAiReply, playNextAudio, audioQueueRef, isPlayingRef]);
  handleSSEEventRef.current = handleSSEEvent;

  return {
    sendAudioToServer,
    sendTextToServer,
    handleSSEEvent,
    handleSSEEventRef,
  };
}
