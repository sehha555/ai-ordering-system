'use client';

import { useState, useEffect, useCallback } from 'react';

const MIC_STORAGE_KEY = 'selectedMicId';

/** 讀取 localStorage 中儲存的麥克風 deviceId */
export function getStoredMicId(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(MIC_STORAGE_KEY);
}

/** 取得麥克風 stream，優先用儲存的裝置，失敗自動 fallback */
export async function getPreferredMicStream(): Promise<MediaStream> {
  const storedId = getStoredMicId();
  const base = { echoCancellation: true, noiseSuppression: true };
  if (storedId) {
    try {
      return await navigator.mediaDevices.getUserMedia({
        audio: { ...base, deviceId: { exact: storedId } },
      });
    } catch {
      console.warn('[Mic] 指定裝置不可用，fallback 到預設');
    }
  }
  return await navigator.mediaDevices.getUserMedia({ audio: base });
}

interface AudioDevice {
  deviceId: string;
  label: string;
}

export default function MicSelector() {
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [open, setOpen] = useState(false);

  const loadDevices = useCallback(async () => {
    // 需要先取得權限，enumerateDevices 才會回傳 label
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach(t => t.stop());
    } catch {
      // 權限被拒，無法列舉
    }
    const all = await navigator.mediaDevices.enumerateDevices();
    const audioInputs = all
      .filter(d => d.kind === 'audioinput')
      .map(d => ({ deviceId: d.deviceId, label: d.label || `麥克風 ${d.deviceId.slice(0, 6)}` }));
    setDevices(audioInputs);

    const stored = getStoredMicId();
    if (stored && audioInputs.some(d => d.deviceId === stored)) {
      setSelectedId(stored);
    } else if (audioInputs.length > 0) {
      setSelectedId(audioInputs[0].deviceId);
    }
  }, []);

  useEffect(() => {
    if (open) loadDevices();
  }, [open, loadDevices]);

  const handleChange = (deviceId: string) => {
    setSelectedId(deviceId);
    localStorage.setItem(MIC_STORAGE_KEY, deviceId);
    setOpen(false);
    // 重新載入讓 VoiceController 用新裝置
    window.location.reload();
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="p-1.5 rounded-lg transition-colors"
        style={{ color: '#5a6b70', backgroundColor: open ? '#e8eef0' : 'transparent' }}
        title="切換麥克風"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="23" />
          <line x1="8" y1="23" x2="16" y2="23" />
        </svg>
      </button>

      {open && devices.length > 0 && (
        <div
          className="absolute right-0 top-full mt-1 py-1 rounded-lg shadow-lg z-50 min-w-[200px]"
          style={{ backgroundColor: 'white', border: '1px solid #d0dce0' }}
        >
          {devices.map(d => (
            <button
              key={d.deviceId}
              onClick={() => handleChange(d.deviceId)}
              className="w-full text-left px-3 py-2 text-sm transition-colors hover:bg-gray-50"
              style={{
                color: d.deviceId === selectedId ? '#729DAD' : '#2c3e42',
                fontWeight: d.deviceId === selectedId ? 600 : 400,
              }}
            >
              {d.deviceId === selectedId && '✓ '}{d.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
