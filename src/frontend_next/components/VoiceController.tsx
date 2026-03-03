'use client';

import { useRef, useState, useCallback, useEffect, RefObject } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';
import AudioVisualizer from './AudioVisualizer';
import { useAudioPlayback } from '../hooks/useAudioPlayback';

// VAD 設定
const VAD_DEFAULT_THRESHOLD = 15;
const SILENCE_DURATION = 1500;
const VAD_CALIBRATION_FRAMES = 60; // 約 1 秒的校準幀數
const VAD_THRESHOLD_MULTIPLIER = 2; // 閾值 = 環境噪音平均值 × 倍數
const VAD_MIN_THRESHOLD = 20; // 最低閾值（原 10 過低，環境雜訊易誤觸）
const MIN_AUDIO_BLOB_SIZE = 4000; // 最小音訊大小（bytes），過濾 VAD 誤觸的超短錄音
const MAX_RECORDING_DURATION = 30000; // 最大錄音時長 30 秒

interface VoiceControllerProps {
  // 外部觸發點擊的 ref（push-to-talk 模式，供 page.tsx 的大波形 onClick 使用）
  triggerRef?: RefObject<(() => void) | null>;
}

export default function VoiceController({ triggerRef }: VoiceControllerProps = {}) {
  const { status, setStatus, setCart, setTranscript, transcript, vadEnabled, setVadEnabled, sessionId, setAiReply } = useStore();

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const { audioQueueRef, isPlayingRef, playNextAudio, onPlaybackCompleteRef } = useAudioPlayback();

  // VAD refs
  const isListeningRef = useRef<boolean>(false);
  const isRecordingRef = useRef<boolean>(false);
  const silenceStartRef = useRef<number | null>(null);
  const vadLoopRef = useRef<number>(0);
  const vadThresholdRef = useRef<number>(VAD_DEFAULT_THRESHOLD);
  const recordingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [volume, setVolume] = useState(0);

  // 完整清理所有音訊資源（stream tracks + AudioContext + VAD loop + recorder）
  const cleanupAudio = useCallback(() => {
    cancelAnimationFrame(vadLoopRef.current);
    isListeningRef.current = false;
    isRecordingRef.current = false;

    if (recordingTimerRef.current) {
      clearTimeout(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    analyserRef.current = null;
  }, []);

  // 初始化麥克風 + VAD
  const initMicrophone = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
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
    }
  }, []);

  // VAD loop - monitors volume and auto-triggers recording
  const startVADLoop = useCallback(() => {
    if (!analyserRef.current) return;

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);

    const loop = () => {
      if (!isListeningRef.current || !analyserRef.current) return;

      analyserRef.current.getByteFrequencyData(dataArray);
      const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
      setVolume(avg / 255);

      if (avg > vadThresholdRef.current) {
        silenceStartRef.current = null;
        if (!isRecordingRef.current) {
          startRecordingVAD();
        }
      } else if (isRecordingRef.current) {
        if (!silenceStartRef.current) {
          silenceStartRef.current = Date.now();
        } else if (Date.now() - silenceStartRef.current > SILENCE_DURATION) {
          stopRecordingVAD();
          silenceStartRef.current = null;
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
      const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
      totalAvg += avg;
      frameCount++;

      requestAnimationFrame(calibrationLoop);
    };

    calibrationLoop();
  }, [startVADLoop]);

  // Start recording in VAD mode
  const startRecordingVAD = useCallback(() => {
    if (isRecordingRef.current || !streamRef.current) return;
    isRecordingRef.current = true;
    setStatus('listening');

    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus'
      : 'audio/webm';

    const recorder = new MediaRecorder(streamRef.current, { mimeType });
    audioChunksRef.current = [];

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) audioChunksRef.current.push(e.data);
    };

    recorder.onstop = async () => {
      const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
      isRecordingRef.current = false;

      if (audioBlob.size > MIN_AUDIO_BLOB_SIZE) {
        await sendAudioToServer(audioBlob);
      } else {
        setStatus('idle');
      }
    };

    mediaRecorderRef.current = recorder;
    recorder.start(200);

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
  }, [setStatus]);

  // Manual recording (push-to-talk)
  const startRecording = useCallback(async () => {
    try {
      if (!streamRef.current) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamRef.current = stream;
      }

      const stream = streamRef.current;

      if (!audioContextRef.current) {
        audioContextRef.current = new AudioContext();
        analyserRef.current = audioContextRef.current.createAnalyser();
        analyserRef.current.fftSize = 256;
        const source = audioContextRef.current.createMediaStreamSource(stream);
        source.connect(analyserRef.current);
      }

      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

      mediaRecorderRef.current = new MediaRecorder(stream, { mimeType });
      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      mediaRecorderRef.current.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
        if (audioBlob.size > MIN_AUDIO_BLOB_SIZE) {
          await sendAudioToServer(audioBlob);
        } else {
          setStatus('idle');
        }
      };

      mediaRecorderRef.current.start();
      setStatus('listening');

      // Volume monitoring for visualizer
      const dataArray = new Uint8Array(analyserRef.current!.frequencyBinCount);
      const updateVolume = () => {
        if (analyserRef.current && status === 'listening') {
          analyserRef.current.getByteFrequencyData(dataArray);
          const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
          setVolume(avg / 255);
          requestAnimationFrame(updateVolume);
        }
      };
      updateVolume();
    } catch (error) {
      console.error('Failed to start recording:', error);
      setStatus('idle');
    }
  }, [setStatus, status]);

  // Stop manual recording
  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
      setStatus('processing');
      setVolume(0);
    }
  }, [setStatus]);

  // 佇列清空時的 callback：恢復 idle 狀態，並在 VAD 模式下重啟監聽
  // 用 useCallback 穩定參照後寫入 ref，讓 playNextAudio 永遠讀取最新版本
  const handlePlaybackComplete = useCallback(() => {
    setStatus('idle');
    if (vadEnabled && isListeningRef.current) {
      startVADLoop();
    }
  }, [setStatus, vadEnabled, startVADLoop]);
  onPlaybackCompleteRef.current = handlePlaybackComplete;

  // Send audio to server and handle SSE
  const sendAudioToServer = useCallback(async (audioBlob: Blob) => {
    // Pause VAD during processing
    if (vadEnabled) {
      cancelAnimationFrame(vadLoopRef.current);
    }

    let formData = new FormData();
    formData.append('file', audioBlob, 'recording.webm');
    formData.append('session_id', sessionId);

    try {
      setStatus('processing');

      // 離線檢查
      if (!navigator.onLine) {
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
          });
          if (response.ok) break;
          throw new Error(`Server error: ${response.status}`);
        } catch (fetchError) {
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

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let currentEvent = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7);
          } else if (line.startsWith('data: ')) {
            const data = line.slice(6);
            handleSSEEvent(currentEvent, data);
          }
        }
      }

      // Process remaining buffer
      if (buffer.trim()) {
        const lines = buffer.split('\n');
        let currentEvent = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7);
          } else if (line.startsWith('data: ')) {
            const data = line.slice(6);
            handleSSEEvent(currentEvent, data);
          }
        }
      }

      // Start playing audio
      if (audioQueueRef.current.length > 0 && !isPlayingRef.current) {
        setStatus('speaking');
        playNextAudio();
      } else if (audioQueueRef.current.length === 0) {
        setStatus('idle');
        // Resume VAD
        if (vadEnabled && isListeningRef.current) {
          startVADLoop();
        }
      }
    } catch (error) {
      console.error('Error sending audio:', error);
      useStore.getState().setConnectionError('語音傳送失敗，請稍後再試');
      setStatus('idle');
      // Resume VAD on error
      if (vadEnabled && isListeningRef.current) {
        startVADLoop();
      }
    }
  }, [setStatus, playNextAudio, vadEnabled, startVADLoop, sessionId]);

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
          // 當 AI 完成訂單流程時，設定訂單結果
          const result = JSON.parse(dataStr);
          useStore.getState().setOrderResult(result);
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
          break;
        }
      }
    } catch (error) {
      console.error('Error parsing SSE event:', event, error);
    }
  }, [setStatus, setTranscript, setCart, setAiReply]);

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

  // Keyboard shortcuts (only in push-to-talk mode)
  useEffect(() => {
    if (vadEnabled) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === 'Space' && status === 'idle') {
        e.preventDefault();
        startRecording();
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space' && status === 'listening') {
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
  }, [status, vadEnabled, startRecording, stopRecording]);

  return (
    <div className="flex flex-col items-center">
      <div
        className={`${vadEnabled ? '' : 'cursor-pointer'} select-none`}
        onClick={handleClick}
      >
        <AudioVisualizer status={status} volume={volume} />
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
