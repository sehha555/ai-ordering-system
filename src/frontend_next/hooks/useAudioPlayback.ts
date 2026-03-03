import { useRef, useCallback } from 'react';

export function useAudioPlayback() {
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef<boolean>(false);
  // SSE 串流是否已結束（所有 audio_chunk 都已收到）
  const streamDoneRef = useRef<boolean>(true);
  const drainTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 使用 ref 儲存 callback，避免 playNextAudio 因外部函式更新而重建
  const onPlaybackCompleteRef = useRef<(() => void) | null>(null);

  const playNextAudio = useCallback(() => {
    if (audioQueueRef.current.length === 0) {
      if (streamDoneRef.current) {
        // SSE 已結束且 queue 空 → 真正完成
        isPlayingRef.current = false;
        onPlaybackCompleteRef.current?.();
      } else {
        // SSE 還在送 → 持續等待新 chunk（500ms 間隔輪詢，直到 streamDone）
        drainTimerRef.current = setTimeout(() => {
          if (audioQueueRef.current.length > 0) {
            playNextAudio();
          } else if (streamDoneRef.current) {
            isPlayingRef.current = false;
            onPlaybackCompleteRef.current?.();
          } else {
            // 仍在等待，繼續輪詢
            playNextAudio();
          }
        }, 500);
      }
      return;
    }

    // 有新 chunk 到達時取消等待 timer
    if (drainTimerRef.current) {
      clearTimeout(drainTimerRef.current);
      drainTimerRef.current = null;
    }

    isPlayingRef.current = true;
    const base64Audio = audioQueueRef.current.shift()!;

    try {
      const binaryString = atob(base64Audio);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      const audioBlob = new Blob([bytes], { type: 'audio/mpeg' });
      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);

      audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        playNextAudio();
      };

      audio.onerror = (e) => {
        console.warn('[AudioPlayback] 播放錯誤:', e);
        URL.revokeObjectURL(audioUrl);
        playNextAudio();
      };

      audio.play().catch((err) => {
        console.warn('[AudioPlayback] play() 失敗:', err.name, err.message);
        // autoplay 失敗時重設 isPlayingRef，避免播放鏈卡住
        isPlayingRef.current = false;
        playNextAudio();
      });
    } catch (error) {
      console.error('Error playing audio:', error);
      isPlayingRef.current = false;
      playNextAudio();
    }
  }, []); // 無外部依賴，playNextAudio 永遠穩定

  // 清理 drain timer（供外部 cleanup 使用）
  const cleanup = useCallback(() => {
    if (drainTimerRef.current) {
      clearTimeout(drainTimerRef.current);
      drainTimerRef.current = null;
    }
    isPlayingRef.current = false;
    audioQueueRef.current = [];
  }, []);

  return { audioQueueRef, isPlayingRef, playNextAudio, onPlaybackCompleteRef, streamDoneRef, cleanup };
}
