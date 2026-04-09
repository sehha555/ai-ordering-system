'use client';

import { useRef, useCallback, useEffect, RefObject } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useStore } from '../store/useStore';
import { useTypewriter } from '../hooks/useTypewriter';
import AudioVisualizer from './AudioVisualizer';
import { useAudioPlayback } from '../hooks/useAudioPlayback';
import { useVAD } from '../hooks/useVAD';
import { useRecording } from '../hooks/useRecording';
import { useSSE } from '../hooks/useSSE';

interface VoiceControllerProps {
  triggerRef?: RefObject<(() => void) | null>;
}

export default function VoiceController({ triggerRef }: VoiceControllerProps = {}) {
  const {
    status, setStatus, setCart, setTranscript, transcript,
    vadEnabled, setVadEnabled, sessionId, setAiReply, setVolume,
  } = useStore();

  // Bridge refs（跨 hook 的循環依賴橋接）
  const sendAudioRef = useRef<((blob: Blob) => Promise<void>) | undefined>(undefined);
  // audioContextRef 在 component 宣告，同時傳給 useAudioPlayback 與 useRecording
  const audioContextRef = useRef<AudioContext | null>(null);

  const {
    audioQueueRef, isPlayingRef, playNextAudio,
    onPlaybackCompleteRef, streamDoneRef, cleanup: cleanupPlayback,
  } = useAudioPlayback(audioContextRef, setVolume);

  const {
    analyserRef, isRecordingRef, isListeningRef,
    cleanupAudio, initMicrophone,
    startRecordingVAD, stopRecordingVAD,
    startRecording, stopRecording,
  } = useRecording({
    audioContextRef, setStatus, setVolume, setVadEnabled,
    sendAudioRef, cleanupPlayback,
  });

  const { startVADLoop, calibrateVAD, vadLoopRef } = useVAD({
    analyserRef, isListeningRef, isRecordingRef,
    setVolume,
    onVoiceDetected: startRecordingVAD,
    onSilenceDetected: stopRecordingVAD,
  });

  const {
    sendAudioToServer,
    handleSSEEventRef,
  } = useSSE({
    sessionId, vadEnabled, isListeningRef,
    setStatus, setTranscript, setCart, setAiReply,
    startVADLoop, playNextAudio,
    audioQueueRef, isPlayingRef, streamDoneRef,
  });

  // ASR 辨識結果逐字顯示
  const displayedTranscript = useTypewriter(transcript, 25);

  // 接上 bridge refs
  sendAudioRef.current = sendAudioToServer;

  // 播放結束回調：恢復 idle，VAD 模式下重啟監聽
  const handlePlaybackComplete = useCallback(() => {
    setStatus('idle');
    setAiReply('');
    if (vadEnabled && isListeningRef.current) {
      startVADLoop();
    }
  }, [setStatus, setAiReply, vadEnabled, isListeningRef, startVADLoop]);
  onPlaybackCompleteRef.current = handlePlaybackComplete;

  // 點擊處理
  const handleClick = useCallback(() => {
    if (vadEnabled) return;
    if (status === 'idle') {
      startRecording();
    } else if (status === 'listening') {
      stopRecording();
    }
  }, [status, vadEnabled, startRecording, stopRecording]);

  useEffect(() => {
    if (triggerRef) triggerRef.current = handleClick;
  }, [triggerRef, handleClick]);

  // VAD 初始化 / 模式切換時重建音訊資源
  useEffect(() => {
    if (vadEnabled) {
      initMicrophone().then(() => {
        calibrateVAD();
      });
    }
    return () => {
      cleanupAudio(vadLoopRef);
    };
  }, [vadEnabled, initMicrophone, calibrateVAD, cleanupAudio, vadLoopRef]);

  // 鍵盤快捷鍵（push-to-talk 模式）
  const statusRef = useRef(status);
  useEffect(() => { statusRef.current = status; }, [status]);

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

      <p className="mt-4 text-sm" style={{ color: 'var(--text-muted)' }}>
        {vadEnabled
          ? status === 'idle'
            ? '語音自動偵測已啟用，請直接說話'
            : ''
          : status === 'idle'
            ? '按住空白鍵或點擊開始說話'
            : ''
        }
      </p>

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
              style={{ color: 'var(--accent)' }}
            >
              「{displayedTranscript}」
            </motion.p>
          )}
        </AnimatePresence>
      </div>

      {/* VAD 切換按鈕位於 page.tsx，此處不重複渲染 */}
    </div>
  );
}
