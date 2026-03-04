import { useRef, useCallback, RefObject } from 'react';

export function useAudioPlayback(audioContextRef: RefObject<AudioContext | null>) {
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef<boolean>(false);
  // SSE 串流是否已結束（所有 audio_chunk 都已收到）
  const streamDoneRef = useRef<boolean>(true);
  // 下一個音訊排程的絕對時間（AudioContext.currentTime 單位，秒）
  const nextStartTimeRef = useRef<number>(0);

  // 使用 ref 儲存 callback，避免 playNextAudio 因外部函式更新而重建
  const onPlaybackCompleteRef = useRef<(() => void) | null>(null);

  const playNextAudio = useCallback(() => {
    const audioCtx = audioContextRef.current;

    // AudioContext 尚未初始化（PTT 模式尚未開始錄音）→ 等外部初始化後再呼叫
    if (!audioCtx) {
      return;
    }

    if (audioQueueRef.current.length === 0) {
      if (streamDoneRef.current) {
        // SSE 已結束且 queue 空 → 真正完成
        isPlayingRef.current = false;
        nextStartTimeRef.current = 0;
        onPlaybackCompleteRef.current?.();
      }
      // SSE 還在送 → 不輪詢，等外部 push 新 chunk 後再呼叫 playNextAudio
      return;
    }

    isPlayingRef.current = true;
    const base64Audio = audioQueueRef.current.shift()!;

    // base64 → ArrayBuffer
    const binaryString = atob(base64Audio);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }

    audioCtx.decodeAudioData(
      bytes.buffer,
      (buffer) => {
        const source = audioCtx.createBufferSource();
        source.buffer = buffer;
        source.connect(audioCtx.destination);

        // 精準無縫排程：接在上一段結束後立即開始
        const startTime = Math.max(audioCtx.currentTime, nextStartTimeRef.current);
        source.start(startTime);
        nextStartTimeRef.current = startTime + buffer.duration;

        source.onended = () => {
          source.disconnect();
          if (audioQueueRef.current.length > 0) {
            // queue 還有資料，繼續排程下一段
            playNextAudio();
          } else if (streamDoneRef.current) {
            // stream 結束且 queue 清空 → 播放完成
            isPlayingRef.current = false;
            nextStartTimeRef.current = 0;
            onPlaybackCompleteRef.current?.();
          }
          // else: SSE 還在送，等外部 push 新 chunk 後呼叫 playNextAudio
        };
      },
      (err) => {
        console.warn('[AudioPlayback] decodeAudioData 失敗:', err);
        // 跳過壞掉的 chunk，繼續播下一個
        playNextAudio();
      }
    );
  }, []); // audioContextRef 是 ref，不需要列為 dep

  // 清理播放狀態（AudioContext 由 VoiceController 管理，不在此關閉）
  const cleanup = useCallback(() => {
    isPlayingRef.current = false;
    audioQueueRef.current = [];
    nextStartTimeRef.current = 0;
  }, []);

  return { audioQueueRef, isPlayingRef, playNextAudio, onPlaybackCompleteRef, streamDoneRef, cleanup };
}
