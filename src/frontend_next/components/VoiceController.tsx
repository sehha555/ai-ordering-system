'use client';

import { useRef, useState, useCallback, useEffect } from 'react';
import { useStore } from '../store/useStore';
import AudioVisualizer from './AudioVisualizer';

export default function VoiceController() {
  const { status, setStatus, setCart, setTranscript } = useStore();

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const audioQueueRef = useRef<string[]>([]);
  const isPlayingRef = useRef<boolean>(false);

  const [volume, setVolume] = useState(0);

  // 初始化音訊分析器（用於視覺化）
  const initAudioAnalyser = useCallback(async (stream: MediaStream) => {
    audioContextRef.current = new AudioContext();
    analyserRef.current = audioContextRef.current.createAnalyser();
    const source = audioContextRef.current.createMediaStreamSource(stream);
    source.connect(analyserRef.current);
    analyserRef.current.fftSize = 256;

    const dataArray = new Uint8Array(analyserRef.current.frequencyBinCount);

    const updateVolume = () => {
      if (analyserRef.current && status === 'listening') {
        analyserRef.current.getByteFrequencyData(dataArray);
        const avg = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
        setVolume(avg / 255);
        requestAnimationFrame(updateVolume);
      }
    };
    updateVolume();
  }, [status]);

  // 開始錄音
  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

      mediaRecorderRef.current = new MediaRecorder(stream, {
        mimeType: 'audio/webm;codecs=opus',
      });

      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorderRef.current.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        stream.getTracks().forEach(track => track.stop());

        if (audioBlob.size > 1000) {
          await sendAudioToServer(audioBlob);
        } else {
          setStatus('idle');
        }
      };

      mediaRecorderRef.current.start();
      setStatus('listening');
      initAudioAnalyser(stream);
    } catch (error) {
      console.error('Failed to start recording:', error);
      setStatus('idle');
    }
  }, [setStatus, initAudioAnalyser]);

  // 停止錄音
  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop();
      setStatus('processing');
      setVolume(0);
    }
  }, [setStatus]);

  // 播放音訊佇列
  const playNextAudio = useCallback(() => {
    if (audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      setStatus('idle');
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
  }, [setStatus]);

  // 發送音訊到伺服器並處理 SSE
  const sendAudioToServer = useCallback(async (audioBlob: Blob) => {
    const formData = new FormData();
    formData.append('file', audioBlob, 'recording.webm');

    try {
      const response = await fetch('/api/voice-chat', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('Server error');
      }

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error('No response body');
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // 解析 SSE 事件
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

      // 處理剩餘的 buffer
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

      // 開始播放音訊
      if (audioQueueRef.current.length > 0 && !isPlayingRef.current) {
        setStatus('speaking');
        playNextAudio();
      } else if (audioQueueRef.current.length === 0) {
        setStatus('idle');
      }

    } catch (error) {
      console.error('Error sending audio:', error);
      setStatus('idle');
    }
  }, [setStatus, playNextAudio]);

  // 處理 SSE 事件
  const handleSSEEvent = useCallback((event: string, dataStr: string) => {
    try {
      switch (event) {
        case 'thinking':
          setStatus('processing');
          break;

        case 'transcription':
          const transcriptionData = JSON.parse(dataStr);
          setTranscript(transcriptionData.text || '');
          break;

        case 'cart_update':
          const cartData = JSON.parse(dataStr);
          setCart(cartData.items || [], cartData.total || 0);
          break;

        case 'audio_chunk':
          // dataStr 是 base64 編碼的音訊
          const audioData = JSON.parse(dataStr);
          audioQueueRef.current.push(audioData);
          break;
      }
    } catch (error) {
      console.error('Error parsing SSE event:', event, error);
    }
  }, [setStatus, setTranscript, setCart]);

  // 點擊處理
  const handleClick = useCallback(() => {
    if (status === 'idle') {
      startRecording();
    } else if (status === 'listening') {
      stopRecording();
    }
  }, [status, startRecording, stopRecording]);

  // 鍵盤快捷鍵
  useEffect(() => {
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
  }, [status, startRecording, stopRecording]);

  return (
    <div
      className="flex flex-col items-center cursor-pointer select-none"
      onClick={handleClick}
    >
      <AudioVisualizer status={status} volume={volume} />
      <p className="mt-4 text-sm text-gray-500">
        {status === 'idle' ? '按住空白鍵或點擊開始說話' : ''}
      </p>
    </div>
  );
}
