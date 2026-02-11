'use client';

import { useRef, useState, useCallback, useEffect } from 'react';
import { useStore } from '../store/useStore';
import AudioVisualizer from './AudioVisualizer';

// VAD 設定
const VAD_THRESHOLD = 15;
const SILENCE_DURATION = 1500;

export default function VoiceController() {
  const { status, setStatus, setCart, setTranscript, vadEnabled, setVadEnabled, sessionId } = useStore();

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef<boolean>(false);

  // VAD refs
  const isListeningRef = useRef<boolean>(false);
  const isRecordingRef = useRef<boolean>(false);
  const silenceStartRef = useRef<number | null>(null);
  const vadLoopRef = useRef<number>(0);

  const [volume, setVolume] = useState(0);

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

      if (avg > VAD_THRESHOLD) {
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

      if (audioBlob.size > 1000) {
        await sendAudioToServer(audioBlob);
      } else {
        setStatus('idle');
      }
    };

    mediaRecorderRef.current = recorder;
    recorder.start(200);
  }, [setStatus]);

  // Stop recording in VAD mode
  const stopRecordingVAD = useCallback(() => {
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
        if (audioBlob.size > 1000) {
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

  // Play audio queue
  const playNextAudio = useCallback(() => {
    if (audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      setStatus('idle');
      // Resume VAD after playback
      if (vadEnabled && isListeningRef.current) {
        startVADLoop();
      }
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
  }, [setStatus, vadEnabled, startVADLoop]);

  // Send audio to server and handle SSE
  const sendAudioToServer = useCallback(async (audioBlob: Blob) => {
    // Pause VAD during processing
    if (vadEnabled) {
      cancelAnimationFrame(vadLoopRef.current);
    }

    const formData = new FormData();
    formData.append('file', audioBlob, 'recording.webm');
    formData.append('session_id', sessionId);

    try {
      setStatus('processing');

      const response = await fetch('/api/voice-chat', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) throw new Error('Server error');

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
      setStatus('idle');
      // Resume VAD on error
      if (vadEnabled && isListeningRef.current) {
        startVADLoop();
      }
    }
  }, [setStatus, playNextAudio, vadEnabled, startVADLoop]);

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
        case 'audio_chunk': {
          const audioData = JSON.parse(dataStr);
          audioQueueRef.current.push(audioData);
          break;
        }
      }
    } catch (error) {
      console.error('Error parsing SSE event:', event, error);
    }
  }, [setStatus, setTranscript, setCart]);

  // Click handler
  const handleClick = useCallback(() => {
    if (vadEnabled) return; // In VAD mode, clicking does nothing
    if (status === 'idle') {
      startRecording();
    } else if (status === 'listening') {
      stopRecording();
    }
  }, [status, vadEnabled, startRecording, stopRecording]);

  // Initialize VAD on mount
  useEffect(() => {
    if (vadEnabled) {
      initMicrophone().then(() => {
        startVADLoop();
      });
    }

    return () => {
      cancelAnimationFrame(vadLoopRef.current);
      isListeningRef.current = false;
    };
  }, [vadEnabled, initMicrophone, startVADLoop]);

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

      {/* VAD 模式切換 */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          // Clean up current mode before switching
          if (vadEnabled) {
            cancelAnimationFrame(vadLoopRef.current);
            isListeningRef.current = false;
          }
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
