import { useRef, useCallback, RefObject } from 'react';

// audioContextRef 保留參數（VoiceController 傳入），但播放改用 <audio> + Blob URL
// 原因：decodeAudioData 對 MP3 格式支援不穩定（W3C 已知限制），<audio> 原生解碼更可靠
export function useAudioPlayback(
  _audioContextRef: RefObject<AudioContext | null>,
  onVolumeUpdate?: (volume: number) => void,
  // 可選：把 TTS AnalyserNode 存入 store，供 AudioVisualizer 頻譜驅動
  setAnalyser?: (a: AnalyserNode | null) => void,
  // 可選：identity guard 清除（只清自己放進 store 的，避免蓋掉 mic 的 analyser）
  clearAnalyser?: (owner: AnalyserNode | null) => void,
) {
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef<boolean>(false);
  // SSE 串流是否已結束（所有 audio_chunk 都已收到）
  const streamDoneRef = useRef<boolean>(true);

  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const currentUrlRef = useRef<string | null>(null);
  // TTS 播放音量監控（Web Audio API）
  const ttsAnalyserRef = useRef<AnalyserNode | null>(null);
  const ttsAudioCtxRef = useRef<AudioContext | null>(null);
  const volumeRafRef = useRef<number>(0);

  const onPlaybackCompleteRef = useRef<(() => void) | null>(null);

  // 停止 TTS 音量監控並重置
  const stopVolumeMonitor = useCallback(() => {
    cancelAnimationFrame(volumeRafRef.current);
    const owner = ttsAnalyserRef.current;
    ttsAnalyserRef.current = null;
    if (ttsAudioCtxRef.current) {
      ttsAudioCtxRef.current.close();
      ttsAudioCtxRef.current = null;
    }
    // 只清自己放進 store 的 analyser：插話時 store 已換成 mic 的，不能蓋掉
    clearAnalyser?.(owner);
    onVolumeUpdate?.(0);
  }, [onVolumeUpdate, clearAnalyser]);

  const playNextAudio = useCallback(() => {
    if (audioQueueRef.current.length === 0) {
      // queue 空 → 標記未播放，讓新 AUDIO_CHUNK 能重啟播放鏈
      isPlayingRef.current = false;
      if (streamDoneRef.current) {
        // SSE 也結束 → 真正完成
        onPlaybackCompleteRef.current?.();
      }
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

    // TTS 音量監控：連接 Web Audio API，讓 AudioVisualizer 在 speaking 時跟著跳動
    if (onVolumeUpdate) {
      try {
        const ctx = new AudioContext();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        // 0.6：保留頻譜動態給聲紋視覺化（0.8 會把起伏抹平）
        analyser.smoothingTimeConstant = 0.6;
        const source = ctx.createMediaElementSource(audio);
        source.connect(analyser);
        analyser.connect(ctx.destination); // 必須接 destination，否則無聲
        ttsAudioCtxRef.current = ctx;
        ttsAnalyserRef.current = analyser;
        // 把 TTS analyser 存入 store，讓 AudioVisualizer 在 speaking 時用頻譜驅動
        setAnalyser?.(analyser);

        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        const updateVolume = () => {
          if (!ttsAnalyserRef.current) return;
          ttsAnalyserRef.current.getByteFrequencyData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
          onVolumeUpdate(sum / dataArray.length / 255);
          volumeRafRef.current = requestAnimationFrame(updateVolume);
        };
        updateVolume();
      } catch (e) {
        // 降級：無音量動畫，但播放不受影響
        console.warn('[AudioPlayback] 無法建立 TTS AudioContext for visualizer:', e);
      }
    }

    const revokeUrl = () => {
      URL.revokeObjectURL(url);
      if (currentUrlRef.current === url) currentUrlRef.current = null;
    };

    audio.onended = () => {
      stopVolumeMonitor();
      revokeUrl();
      if (audioQueueRef.current.length > 0) {
        playNextAudio();
      } else {
        isPlayingRef.current = false;
        if (streamDoneRef.current) {
          onPlaybackCompleteRef.current?.();
        }
      }
    };

    audio.onerror = () => {
      console.warn('[AudioPlayback] <audio> 播放失敗，跳過此 chunk');
      stopVolumeMonitor();
      revokeUrl();
      playNextAudio();
    };

    audio.play().catch((e) => {
      console.warn('[AudioPlayback] play() 被阻擋:', e);
      // play() 被阻擋時 onended 不會觸發，必須手動推進 queue 避免 deadlock
      stopVolumeMonitor();
      revokeUrl();
      playNextAudio();
    });
  }, [onVolumeUpdate, stopVolumeMonitor, setAnalyser]);

  // 清理播放狀態（AudioContext 由 VoiceController 管理，不在此關閉）
  const cleanup = useCallback(() => {
    stopVolumeMonitor();
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
  }, [stopVolumeMonitor]);

  return { audioQueueRef, isPlayingRef, playNextAudio, onPlaybackCompleteRef, streamDoneRef, cleanup };
}
