import { useRef, useCallback, RefObject } from 'react';
import { getPreferredMicStream } from '../components/MicSelector';
import { useStore } from '../store/useStore';
import type { AppStatus } from '../types';

const MAX_RECORDING_DURATION = 30000;

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
  return undefined;
}

interface UseRecordingProps {
  audioContextRef: RefObject<AudioContext | null>;
  setStatus: (s: AppStatus) => void;
  setVolume: (v: number) => void;
  setVadEnabled: (v: boolean) => void;
  sendAudioRef: RefObject<((blob: Blob) => Promise<void>) | undefined>;
  cleanupPlayback: () => void;
  // 可選：把活躍的 AnalyserNode 存入 store，供 AudioVisualizer 頻譜驅動
  setAnalyser?: (a: AnalyserNode | null) => void;
  // 可選：identity guard 清除（只清自己放進 store 的，避免蓋掉 TTS 的 analyser）
  clearAnalyser?: (owner: AnalyserNode | null) => void;
}

export function useRecording({
  audioContextRef,
  setStatus,
  setVolume,
  setVadEnabled,
  sendAudioRef,
  cleanupPlayback,
  setAnalyser,
  clearAnalyser,
}: UseRecordingProps) {
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const isRecordingRef = useRef<boolean>(false);
  const isListeningRef = useRef<boolean>(false);
  const recordingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recordingStartTimeRef = useRef<number>(0);

  const cleanupAudio = useCallback((vadLoopRef: RefObject<number>) => {
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
    cleanupPlayback();
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    clearAnalyser?.(analyserRef.current);
    analyserRef.current = null;
  }, [cleanupPlayback, clearAnalyser]);

  const initMicrophone = useCallback(async () => {
    try {
      const stream = await getPreferredMicStream();
      streamRef.current = stream;

      audioContextRef.current = new AudioContext();
      analyserRef.current = audioContextRef.current.createAnalyser();
      analyserRef.current.fftSize = 256;
      // 0.6：保留頻譜動態給聲紋視覺化（0.8 會把起伏抹平）
      analyserRef.current.smoothingTimeConstant = 0.6;

      const source = audioContextRef.current.createMediaStreamSource(stream);
      source.connect(analyserRef.current);

      isListeningRef.current = true;
    } catch (error) {
      console.error('Failed to access microphone:', error);
      useStore.getState().setConnectionError('無法存取麥克風，請確認瀏覽器權限');
      setVadEnabled(false);
    }
  }, [setVadEnabled]);

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
  }, [setStatus, sendAudioRef]);

  const startRecordingVAD = useCallback(() => {
    if (isRecordingRef.current || !streamRef.current) return;
    isRecordingRef.current = true;
    setStatus('listening');
    // 把 mic analyser 存入 store，讓 AudioVisualizer 用真實頻譜驅動動畫
    setAnalyser?.(analyserRef.current);

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

    recordingTimerRef.current = setTimeout(() => {
      console.log('[VAD] 達到最大錄音時長，自動停止');
      stopRecordingVAD();
    }, MAX_RECORDING_DURATION);
  }, [setStatus, makeOnStopHandler]); // eslint-disable-line react-hooks/exhaustive-deps

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
      // 停止錄音後清除 analyser（identity guard），processing 狀態用固定動畫
      clearAnalyser?.(analyserRef.current);
    }
  }, [setStatus, setVolume, clearAnalyser]);

  const startRecording = useCallback(async () => {
    try {
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
        analyserRef.current.smoothingTimeConstant = 0.6;
      }
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
      // PTT 模式：錄音開始時把 mic analyser 存入 store
      setAnalyser?.(analyserRef.current ?? null);

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
  }, [setStatus, setVolume, makeOnStopHandler, setAnalyser]);

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
      setStatus('processing');
      setVolume(0);
      // PTT 停止錄音後清除 analyser（identity guard），processing 狀態用固定動畫
      clearAnalyser?.(analyserRef.current);
    }
  }, [setStatus, setVolume, clearAnalyser]);

  return {
    mediaRecorderRef,
    analyserRef,
    isRecordingRef,
    isListeningRef,
    cleanupAudio,
    initMicrophone,
    startRecordingVAD,
    stopRecordingVAD,
    startRecording,
    stopRecording,
  };
}
