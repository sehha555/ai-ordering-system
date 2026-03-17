import { useRef, useCallback, RefObject } from 'react';

const VAD_DEFAULT_THRESHOLD = 15;
const SILENCE_DURATION = 1500;
const VAD_CALIBRATION_FRAMES = 60;
const VAD_THRESHOLD_MULTIPLIER = 2;
const VAD_MIN_THRESHOLD = 20;
const VOICE_FRAMES_REQUIRED = 3;

interface UseVADProps {
  analyserRef: RefObject<AnalyserNode | null>;
  isListeningRef: RefObject<boolean>;
  isRecordingRef: RefObject<boolean>;
  setVolume: (v: number) => void;
  onVoiceDetected: () => void;   // → startRecordingVAD
  onSilenceDetected: () => void; // → stopRecordingVAD
}

export function useVAD({
  analyserRef,
  isListeningRef,
  isRecordingRef,
  setVolume,
  onVoiceDetected,
  onSilenceDetected,
}: UseVADProps) {
  const vadLoopRef = useRef<number>(0);
  const vadThresholdRef = useRef<number>(VAD_DEFAULT_THRESHOLD);
  const voiceFrameCountRef = useRef<number>(0);
  const silenceStartRef = useRef<number | null>(null);

  // 用 ref 儲存 callbacks，避免 startVADLoop 的 empty deps 造成 stale closure
  const onVoiceDetectedRef = useRef(onVoiceDetected);
  const onSilenceDetectedRef = useRef(onSilenceDetected);
  onVoiceDetectedRef.current = onVoiceDetected;
  onSilenceDetectedRef.current = onSilenceDetected;

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
      // throttle：每 4 幀寫一次 store（~15Hz）
      if (++frameCount % 4 === 0) setVolume(avg / 255);

      if (avg > vadThresholdRef.current) {
        voiceFrameCountRef.current++;
        silenceStartRef.current = null;
        if (!isRecordingRef.current && voiceFrameCountRef.current >= VOICE_FRAMES_REQUIRED) {
          onVoiceDetectedRef.current();
        }
      } else {
        voiceFrameCountRef.current = 0;
        if (isRecordingRef.current) {
          if (!silenceStartRef.current) {
            silenceStartRef.current = Date.now();
          } else if (Date.now() - silenceStartRef.current > SILENCE_DURATION) {
            onSilenceDetectedRef.current();
            silenceStartRef.current = null;
          }
        }
      }

      vadLoopRef.current = requestAnimationFrame(loop);
    };

    loop();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const calibrateVAD = useCallback(() => {
    if (!analyserRef.current) return;

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);
    let totalAvg = 0;
    let frameCount = 0;

    const calibrationLoop = () => {
      if (!analyserRef.current || frameCount >= VAD_CALIBRATION_FRAMES) {
        const ambientNoise = frameCount > 0 ? totalAvg / frameCount : 0;
        vadThresholdRef.current = Math.max(
          ambientNoise * VAD_THRESHOLD_MULTIPLIER,
          VAD_MIN_THRESHOLD
        );
        console.log(`[VAD] 校準完成：環境噪音 ${ambientNoise.toFixed(1)}，閾值 ${vadThresholdRef.current.toFixed(1)}`);
        startVADLoop();
        return;
      }

      analyserRef.current.getByteFrequencyData(dataArray);
      let calSum = 0;
      for (let i = 0; i < dataArray.length; i++) calSum += dataArray[i];
      totalAvg += calSum / dataArray.length;
      frameCount++;

      requestAnimationFrame(calibrationLoop);
    };

    calibrationLoop();
  }, [analyserRef, startVADLoop]);

  return { startVADLoop, calibrateVAD, vadLoopRef };
}
