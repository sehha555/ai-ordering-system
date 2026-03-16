'use client';

import { useRef, useCallback, useEffect, RefObject } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';
import AudioVisualizer from './AudioVisualizer';
import { useAudioPlayback } from '../hooks/useAudioPlayback';
import { getPreferredMicStream } from './MicSelector';

// VAD 設定
const VAD_DEFAULT_THRESHOLD = 15;
// 自動追問設定（speaking → idle 後，若購物車有品項則觸發）
const AUTO_PROMPT_DELAY = 3000; // 3 秒無語音後自動追問
const AUTO_PROMPT_TEXT = '這樣就好嗎？'; // 自動追問文字
const SILENCE_DURATION = 1500;
const VAD_CALIBRATION_FRAMES = 60; // 約 1 秒的校準幀數
const VAD_THRESHOLD_MULTIPLIER = 2; // 閾值 = 環境噪音平均值 × 倍數
const VAD_MIN_THRESHOLD = 20; // 最低閾值（原 10 過低，環境雜訊易誤觸）
const MAX_RECORDING_DURATION = 30000; // 最大錄音時長 30 秒
const VOICE_FRAMES_REQUIRED = 3; // 連續 ~50ms 超閾值才觸發（防噪音尖峰）
const SSE_TIMEOUT = 30000; // SSE 回應超時 30 秒（LLM 冷啟動 + tool call 可能很慢）

// 依序嘗試支援的 mimeType，找不到就讓瀏覽器自選
const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/ogg;codecs=opus',
  'audio/mp4',
];
function getSupportedMimeType(): string | undefined {
  for (const mime of MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(mime)) return mime;
  }
  return undefined; // 讓 MediaRecorder 自動選擇
}

// SSE 行解析：回傳 currentEvent 供下次呼叫繼承，避免 event: 和 data: 跨 read chunk 時 event 被重置
function parseSSELines(lines: string[], onEvent: (event: string, data: string) => void, currentEvent = ''): string {
  for (const line of lines) {
    if (line.startsWith('event: ')) {
      currentEvent = line.slice(7);
    } else if (line.startsWith('data: ')) {
      onEvent(currentEvent, line.slice(6));
    }
  }
  return currentEvent;
}

interface VoiceControllerProps {
  // 外部觸發點擊的 ref（push-to-talk 模式，供 page.tsx 的大波形 onClick 使用）
  triggerRef?: RefObject<(() => void) | null>;
}

export default function VoiceController({ triggerRef }: VoiceControllerProps = {}) {
  const { status, setStatus, setCart, setTranscript, transcript, vadEnabled, setVadEnabled, sessionId, setAiReply, setVolume } = useStore();

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const { audioQueueRef, isPlayingRef, playNextAudio, onPlaybackCompleteRef, streamDoneRef, cleanup: cleanupPlayback } = useAudioPlayback(audioContextRef);

  // 自動追問計時器 ref
  const autoPromptTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 上一個 status（用於偵測 speaking → idle 轉換）
  const prevStatusRef = useRef<string>('idle');

  // VAD refs
  const isListeningRef = useRef<boolean>(false);
  const isRecordingRef = useRef<boolean>(false);
  const silenceStartRef = useRef<number | null>(null);
  const vadLoopRef = useRef<number>(0);
  const vadThresholdRef = useRef<number>(VAD_DEFAULT_THRESHOLD);
  const recordingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const voiceFrameCountRef = useRef<number>(0); // 連續超閾值幀數（防噪音假觸發）

  const recordingStartTimeRef = useRef<number>(0);

  // ref 存放 sendAudioToServer，讓 makeOnStopHandler 不受宣告順序限制
  const sendAudioRef = useRef<((blob: Blob) => Promise<void>) | undefined>(undefined);
  // ref 存放 handleSSEEvent，讓 sendTextToServer/autoPrompt 不受宣告順序限制
  const handleSSEEventRef = useRef<((event: string, dataStr: string) => void) | undefined>(undefined);
  // ref 存放 sendTextToServer，讓 autoPrompt timer 永遠呼叫最新版本
  const sendTextRef = useRef<((text: string) => Promise<void>) | undefined>(undefined);

  // 完整清理所有音訊資源（stream tracks + AudioContext + VAD loop + recorder）
  const cleanupAudio = useCallback(() => {
    cancelAnimationFrame(vadLoopRef.current);
    isListeningRef.current = false;
    isRecordingRef.current = false;

    if (recordingTimerRef.current) {
      clearTimeout(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }

    // 清除自動追問計時器
    if (autoPromptTimerRef.current) {
      clearTimeout(autoPromptTimerRef.current);
      autoPromptTimerRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    // 先重置播放佇列（nextStartTimeRef 歸零），再 close AudioContext
    cleanupPlayback();
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    analyserRef.current = null;
  }, [cleanupPlayback]);

  // 初始化麥克風 + VAD
  const initMicrophone = useCallback(async () => {
    try {
      const stream = await getPreferredMicStream();
      streamRef.current = stream;

      audioContextRef.current = new AudioContext();
      analyserRef.current = audioContextRef.current.createAnalyser();
      analyserRef.current.fftSize = 256;
      analyserRef.current.smoothingTimeConstant = 0.8;

      const source = audioContextRef.current.createMediaStreamSource(stream);
      source.connect(analyserRef.current);

      isListeningRef.current = true;
    } catch (error) {
      console.error('Failed to access microphone:', error);
      useStore.getState().setConnectionError('無法存取麥克風，請確認瀏覽器權限');
      setVadEnabled(false);
    }
  }, [setVadEnabled]);

  // VAD loop - monitors volume and auto-triggers recording
  const startVADLoop = useCallback(() => {
    if (!analyserRef.current) return;

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
    let frameCount = 0;

    const loop = () => {
      if (!isListeningRef.current || !analyserRef.current) return;

      analyserRef.current.getByteFrequencyData(dataArray);
      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
      const avg = sum / dataArray.length;
      // throttle：每 4 幀寫一次 store（~15Hz），減少 Zustand subscriber 通知
      if (++frameCount % 4 === 0) setVolume(avg / 255);

      if (avg > vadThresholdRef.current) {
        voiceFrameCountRef.current++;
        silenceStartRef.current = null;
        if (!isRecordingRef.current && voiceFrameCountRef.current >= VOICE_FRAMES_REQUIRED) {
          startRecordingVAD();
        }
      } else {
        voiceFrameCountRef.current = 0;
        if (isRecordingRef.current) {
          if (!silenceStartRef.current) {
            silenceStartRef.current = Date.now();
          } else if (Date.now() - silenceStartRef.current > SILENCE_DURATION) {
            stopRecordingVAD();
            silenceStartRef.current = null;
          }
        }
      }

      vadLoopRef.current = requestAnimationFrame(loop);
    };

    loop();
  }, []);

  // VAD 校準 — 採樣環境噪音並計算自適應閾值
  const calibrateVAD = useCallback(() => {
    if (!analyserRef.current) return;

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
    let totalAvg = 0;
    let frameCount = 0;

    const calibrationLoop = () => {
      if (!analyserRef.current || frameCount >= VAD_CALIBRATION_FRAMES) {
        // 校準完成，計算閾值
        const ambientNoise = frameCount > 0 ? totalAvg / frameCount : 0;
        vadThresholdRef.current = Math.max(
          ambientNoise * VAD_THRESHOLD_MULTIPLIER,
          VAD_MIN_THRESHOLD
        );
        console.log(`[VAD] 校準完成：環境噪音 ${ambientNoise.toFixed(1)}，閾值 ${vadThresholdRef.current.toFixed(1)}`);
        // 校準完成後開始 VAD loop
        startVADLoop();
        return;
      }

      analyserRef.current.getByteFrequencyData(dataArray);
      let calSum = 0;
      for (let i = 0; i < dataArray.length; i++) calSum += dataArray[i];
      const avg = calSum / dataArray.length;
      totalAvg += avg;
      frameCount++;

      requestAnimationFrame(calibrationLoop);
    };

    calibrationLoop();
  }, [startVADLoop]);

  // 共用 onstop handler — VAD/PTT 共用，只差 label
  const makeOnStopHandler = useCallback((label: string, mime: string) => async () => {
    isRecordingRef.current = false;
    try {
      const audioBlob = new Blob(audioChunksRef.current, { type: mime });
      const duration = Date.now() - recordingStartTimeRef.current;
      if (duration >= 300 && audioBlob.size > 1000) {
        await sendAudioRef.current?.(audioBlob);
      } else {
        console.log(`[${label}] 錄音過短（${duration}ms / ${audioBlob.size}bytes），略過`);
        setStatus('idle');
      }
    } catch (error) {
      console.error(`[${label}] onstop 處理失敗:`, error);
      setStatus('idle');
    }
  }, [setStatus]);

  // Start recording in VAD mode
  const startRecordingVAD = useCallback(() => {
    if (isRecordingRef.current || !streamRef.current) return;
    isRecordingRef.current = true;
    setStatus('listening');

    // 用戶開始說話，取消自動追問計時器
    if (autoPromptTimerRef.current) {
      console.log('[自動追問] 偵測到語音輸入，取消計時器');
      clearTimeout(autoPromptTimerRef.current);
      autoPromptTimerRef.current = null;
    }

    const mimeType = getSupportedMimeType();
    const recorderOpts = mimeType ? { mimeType } : undefined;
    const recorder = new MediaRecorder(streamRef.current, recorderOpts);
    audioChunksRef.current = [];

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunksRef.current.push(e.data);
    };

    recorder.onstop = makeOnStopHandler('VAD', recorder.mimeType);

    mediaRecorderRef.current = recorder;
    recordingStartTimeRef.current = Date.now();
    recorder.start(100);

    // 最大錄音時長保護
    recordingTimerRef.current = setTimeout(() => {
      console.log('[VAD] 達到最大錄音時長，自動停止');
      stopRecordingVAD();
    }, MAX_RECORDING_DURATION);
  }, [setStatus]);

  // Stop recording in VAD mode
  const stopRecordingVAD = useCallback(() => {
    if (recordingTimerRef.current) {
      clearTimeout(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.requestData();
      mediaRecorderRef.current.stop();
      setStatus('processing');
      setVolume(0);
    }
  }, [setStatus, makeOnStopHandler]);

  // Manual recording (push-to-talk)
  const startRecording = useCallback(async () => {
    // 用戶開始說話，取消自動追問計時器
    if (autoPromptTimerRef.current) {
      console.log('[自動追問] 偵測到語音輸入（PTT），取消計時器');
      clearTimeout(autoPromptTimerRef.current);
      autoPromptTimerRef.current = null;
    }

    try {
      // 每次重新取得 stream，避免裝置切換後殘留舊 stream
      if (streamRef.current) {
        streamRef.current.getTracks().forEach(t => t.stop());
        streamRef.current = null;
      }
      const stream = await getPreferredMicStream();
      streamRef.current = stream;

      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext();
        analyserRef.current = audioContextRef.current.createAnalyser();
        analyserRef.current.fftSize = 256;
      }
      // 每次新 stream 都重新連接到 analyser（避免第二次 PTT 後音量監控失效）
      const source = audioContextRef.current.createMediaStreamSource(stream);
      source.connect(analyserRef.current!);

      const mimeType = getSupportedMimeType();
      const recorderOpts = mimeType ? { mimeType } : undefined;
      mediaRecorderRef.current = new MediaRecorder(stream, recorderOpts);
      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      mediaRecorderRef.current.onstop = makeOnStopHandler('PTT', mediaRecorderRef.current.mimeType);

      recordingStartTimeRef.current = Date.now();
      mediaRecorderRef.current.start();
      setStatus('listening');

      // Volume monitoring：用 mediaRecorderRef 狀態判斷，避免 stale closure
      const dataArray = new Uint8Array(analyserRef.current!.frequencyBinCount);
      let pttFrameCount = 0;
      const updateVolume = () => {
        if (analyserRef.current && mediaRecorderRef.current?.state === 'recording') {
          analyserRef.current.getByteFrequencyData(dataArray);
          let volSum = 0;
          for (let i = 0; i < dataArray.length; i++) volSum += dataArray[i];
          if (++pttFrameCount % 4 === 0) setVolume(volSum / dataArray.length / 255);
          requestAnimationFrame(updateVolume);
        }
      };
      updateVolume();
    } catch (error) {
      console.error('Failed to start recording:', error);
      setStatus('idle');
    }
  }, [setStatus, makeOnStopHandler]);

  // Stop manual recording
  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
      setStatus('processing');
      setVolume(0);
    }
  }, [setStatus]);

  // 送純文字到後端（/api/text-chat），用於自動追問場景
  const sendTextToServer = useCallback(async (text: string) => {
    // 暫停 VAD，避免在處理時誤觸發
    if (vadEnabled) {
      cancelAnimationFrame(vadLoopRef.current);
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
  }, [setStatus, vadEnabled, sessionId, startVADLoop, streamDoneRef, audioQueueRef, isPlayingRef]);
  sendTextRef.current = sendTextToServer;

  // 佇列清空時的 callback：恢復 idle 狀態，並在 VAD 模式下重啟監聽
  // 用 useCallback 穩定參照後寫入 ref，讓 playNextAudio 永遠讀取最新版本
  const handlePlaybackComplete = useCallback(() => {
    setStatus('idle');
    setAiReply(''); // 播放結束清除 AI 回覆，避免資料殘留
    if (vadEnabled && isListeningRef.current) {
      startVADLoop();
    }
  }, [setStatus, setAiReply, vadEnabled, startVADLoop]);
  onPlaybackCompleteRef.current = handlePlaybackComplete;

  // 偵測 speaking → idle 狀態轉換，啟動自動追問計時器
  useEffect(() => {
    if (prevStatusRef.current === 'speaking' && status === 'idle') {
      // 購物車有品項才觸發（從 store 即時讀取，不需加入依賴）
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
    }
    prevStatusRef.current = status;
  }, [status]);

  // Send audio to server and handle SSE
  const sendAudioToServer = useCallback(async (audioBlob: Blob) => {
    // Pause VAD during processing
    if (vadEnabled) {
      cancelAnimationFrame(vadLoopRef.current);
    }

    let formData = new FormData();
    formData.append('file', audioBlob, 'recording.webm');
    formData.append('session_id', sessionId);

    const onEvent = (evt: string, data: string) => handleSSEEvent(evt, data);

    // AbortController：SSE 超時自動取消，防止 LLM 卡住時前端掛死
    const abortController = new AbortController();
    const timeoutId = setTimeout(() => abortController.abort(), SSE_TIMEOUT);

    try {
      setStatus('processing');
      streamDoneRef.current = false; // SSE 串流開始

      // 離線檢查
      if (!navigator.onLine) {
        clearTimeout(timeoutId);
        useStore.getState().setConnectionError('網路已斷線，請檢查連線後再試');
        setStatus('idle');
        if (vadEnabled && isListeningRef.current) startVADLoop();
        return;
      }

      // 帶重試的 fetch
      let response: Response | null = null;
      const maxRetries = 2;
      for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
          response = await fetch('/api/voice-chat', {
            method: 'POST',
            body: formData,
            signal: abortController.signal,
          });
          if (response.ok) break;
          throw new Error(`Server error: ${response.status}`);
        } catch (fetchError) {
          if ((fetchError as Error).name === 'AbortError') throw fetchError;
          if (attempt < maxRetries) {
            const delay = Math.pow(2, attempt) * 1000; // 1s, 2s
            await new Promise(resolve => setTimeout(resolve, delay));
            // 重新建立 FormData（因為 body 被消費）
            formData = new FormData();
            formData.append('file', audioBlob, 'recording.webm');
            formData.append('session_id', sessionId);
          } else {
            throw fetchError;
          }
        }
      }

      if (!response || !response.ok) throw new Error('Server error after retries');

      const reader = response.body?.getReader();
      if (!reader) throw new Error('No response body');

      // 收到第一個 event 後取消初始 timeout（後續靠 SSE 串流自己結束）
      clearTimeout(timeoutId);

      const decoder = new TextDecoder();
      let buffer = '';
      let sseEvent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        sseEvent = parseSSELines(lines, onEvent, sseEvent);
      }

      // Process remaining buffer
      if (buffer.trim()) {
        parseSSELines(buffer.split('\n'), onEvent, sseEvent);
      }

      // SSE 結束：標記串流完成，讓 playNextAudio 知道不會再有新 chunk
      streamDoneRef.current = true;
      if (audioQueueRef.current.length === 0 && !isPlayingRef.current) {
        setStatus('idle');
        if (vadEnabled && isListeningRef.current) {
          startVADLoop();
        }
      }
    } catch (error) {
      clearTimeout(timeoutId);
      console.error('Error sending audio:', error);
      streamDoneRef.current = true;
      const isTimeout = (error as Error).name === 'AbortError';
      useStore.getState().setConnectionError(
        isTimeout ? '回應超時，請再試一次' : '語音傳送失敗，請稍後再試'
      );
      setStatus('idle');
      // Resume VAD on error
      if (vadEnabled && isListeningRef.current) {
        startVADLoop();
      }
    }
  }, [setStatus, playNextAudio, vadEnabled, startVADLoop, sessionId]);
  sendAudioRef.current = sendAudioToServer;

  // Handle SSE events
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
          // 當 AI 完成訂單流程時，設定訂單結果並清空前端購物車
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
        case 'status': {
          setStatus('processing');
          break;
        }
        case 'tts_text': {
          const ttsData = JSON.parse(dataStr);
          setAiReply(ttsData.text || '');
          break;
        }
        case 'audio_chunk': {
          const audioData = JSON.parse(dataStr);
          audioQueueRef.current.push(audioData);
          // 收到即播放：不等 SSE 結束，立即啟動播放鏈
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
  }, [setStatus, setTranscript, setCart, setAiReply, playNextAudio]);
  handleSSEEventRef.current = handleSSEEvent;

  // Click handler
  const handleClick = useCallback(() => {
    if (vadEnabled) return; // In VAD mode, clicking does nothing
    if (status === 'idle') {
      startRecording();
    } else if (status === 'listening') {
      stopRecording();
    }
  }, [status, vadEnabled, startRecording, stopRecording]);

  // 將 handleClick 掛到 triggerRef，供外部（page.tsx 大波形）直接呼叫
  useEffect(() => {
    if (triggerRef) triggerRef.current = handleClick;
  }, [triggerRef, handleClick]);

  // Initialize VAD on mount / 模式切換時完整重建音訊資源
  useEffect(() => {
    if (vadEnabled) {
      initMicrophone().then(() => {
        calibrateVAD();
      });
    }

    return () => {
      cleanupAudio();
    };
  }, [vadEnabled, initMicrophone, calibrateVAD, cleanupAudio]);

  // 用 ref 追蹤 status，避免 keyboard handler 因 status 變更重新註冊
  const statusRef = useRef(status);
  useEffect(() => { statusRef.current = status; }, [status]);

  // Keyboard shortcuts (only in push-to-talk mode)
  useEffect(() => {
    if (vadEnabled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space' && statusRef.current === 'idle') {
        e.preventDefault();
        startRecording();
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space' && statusRef.current === 'listening') {
        e.preventDefault();
        stopRecording();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
  }, [vadEnabled, startRecording, stopRecording]);

  return (
    <div className="flex flex-col items-center">
      <div
        className={`${vadEnabled ? '' : 'cursor-pointer'} select-none`}
        onClick={handleClick}
      >
        <AudioVisualizer status={status} />
      </div>

      <p className="mt-4 text-sm" style={{ color: '#5a6b70' }}>
        {vadEnabled
          ? status === 'idle'
            ? '語音自動偵測已啟用，請直接說話'
            : ''
          : status === 'idle'
            ? '按住空白鍵或點擊開始說話'
            : ''
        }
      </p>

      {/* 識別結果顯示 */}
      <div className="h-6 flex items-center justify-center overflow-hidden">
        <AnimatePresence mode="wait">
          {transcript && (
            <motion.p
              key={transcript}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="text-xs text-center px-2"
              style={{ color: '#729DAD' }}
            >
              「{transcript}」
            </motion.p>
          )}
        </AnimatePresence>
      </div>

      {/* VAD 模式切換 */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          // useEffect cleanup（cleanupAudio）會在 vadEnabled 改變時自動執行完整資源清理
          setVadEnabled(!vadEnabled);
        }}
        className="mt-3 px-4 py-1.5 rounded-full text-xs font-medium transition-colors"
        style={{
          backgroundColor: vadEnabled ? '#729DAD' : '#e8eef0',
          color: vadEnabled ? 'white' : '#5a6b70',
          border: `1px solid ${vadEnabled ? '#5a8494' : '#d0dce0'}`,
        }}
      >
        {vadEnabled ? '自動偵測模式' : '按鍵說話模式'}
      </button>
    </div>
  );
}
