import { useRef, useCallback, RefObject } from 'react';

// audioContextRef 保留參數（VoiceController 傳入），但播放改用 <audio> + Blob URL
// 原因：decodeAudioData 對 MP3 格式支援不穩定（W3C 已知限制），<audio> 原生解碼更可靠
export function useAudioPlayback(_audioContextRef: RefObject<AudioContext | null>) {
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef<boolean>(false);
  // SSE 串流是否已結束（所有 audio_chunk 都已收到）
  const streamDoneRef = useRef<boolean>(true);

  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const currentUrlRef = useRef<string | null>(null);

  const onPlaybackCompleteRef = useRef<(() => void) | null>(null);

  const playNextAudio = useCallback(() => {
    if (audioQueueRef.current.length === 0) {
      if (streamDoneRef.current) {
        // SSE 已結束且 queue 空 → 真正完成
        isPlayingRef.current = false;
        onPlaybackCompleteRef.current?.();
      }
      // SSE 還在送 → 等外部 push 新 chunk 後再呼叫 playNextAudio
      return;
    }

    isPlayingRef.current = true;
    const base64Audio = audioQueueRef.current.shift()!;

    // base64 → Uint8Array → Blob → Object URL
    const binaryString = atob(base64Audio);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    const blob = new Blob([bytes], { type: 'audio/mpeg' });
    const url = URL.createObjectURL(blob);

    // 清理上一個 URL（避免記憶體洩漏）
    if (currentUrlRef.current) {
      URL.revokeObjectURL(currentUrlRef.current);
    }
    currentUrlRef.current = url;

    const audio = new Audio(url);
    currentAudioRef.current = audio;

    audio.onended = () => {
      URL.revokeObjectURL(url);
      if (currentUrlRef.current === url) currentUrlRef.current = null;

      if (audioQueueRef.current.length > 0) {
        playNextAudio();
      } else if (streamDoneRef.current) {
        isPlayingRef.current = false;
        onPlaybackCompleteRef.current?.();
      }
    };

    audio.onerror = () => {
      console.warn('[AudioPlayback] <audio> 播放失敗，跳過此 chunk');
      URL.revokeObjectURL(url);
      if (currentUrlRef.current === url) currentUrlRef.current = null;
      playNextAudio();
    };

    audio.play().catch((e) => {
      console.warn('[AudioPlayback] play() 被阻擋:', e);
    });
  }, []);

  // 清理播放狀態（AudioContext 由 VoiceController 管理，不在此關閉）
  const cleanup = useCallback(() => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current.onended = null;
      currentAudioRef.current.onerror = null;
      currentAudioRef.current = null;
    }
    if (currentUrlRef.current) {
      URL.revokeObjectURL(currentUrlRef.current);
      currentUrlRef.current = null;
    }
    isPlayingRef.current = false;
    audioQueueRef.current = [];
  }, []);

  return { audioQueueRef, isPlayingRef, playNextAudio, onPlaybackCompleteRef, streamDoneRef, cleanup };
}
