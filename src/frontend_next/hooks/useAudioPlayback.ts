import { useRef, useCallback } from 'react';

export function useAudioPlayback() {
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef<boolean>(false);

  // 使用 ref 儲存 callback，避免 playNextAudio 因外部函式更新而重建
  const onPlaybackCompleteRef = useRef<(() => void) | null>(null);

  const playNextAudio = useCallback(() => {
    if (audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      onPlaybackCompleteRef.current?.();
      return;
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

      audio.onerror = () => {
        URL.revokeObjectURL(audioUrl);
        playNextAudio();
      };

      audio.play().catch(() => playNextAudio());
    } catch (error) {
      console.error('Error playing audio:', error);
      playNextAudio();
    }
  }, []); // 無外部依賴，playNextAudio 永遠穩定

  return { audioQueueRef, isPlayingRef, playNextAudio, onPlaybackCompleteRef };
}
