'use client';

import { useRef, useEffect, useCallback } from 'react';

import { AppStatus } from '../types';
import { useStore } from '../store/useStore';

// 頻譜聚合參數：fftSize=256 → 128 bin，取前 96 bin 涵蓋語音/TTS 常見頻段
const BAND_COUNT = 14;
const VALID_BINS = 96;

interface AudioVisualizerProps {
  status: AppStatus;
  volume?: number;
  size?: 'large' | 'medium' | 'small';
}

export const STATUS_COLORS: Record<AppStatus, string> = {
  idle: '#729DAD',
  listening: '#4a9d68',
  processing: '#c49a30',
  speaking: '#5a8494',
};

function rgba(hex: string, a: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${a})`;
}

export default function AudioVisualizer({ status, volume = 0, size = 'large' }: AudioVisualizerProps) {
  // isSmall 只用於控制繪圖細節（頻譜條數量），不影響 canvas 尺寸
  const isSmall = size === 'small';
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>(0);
  const phaseRef = useRef(0);
  const colorRef = useRef({ r: 114, g: 157, b: 173 });
  // 平滑音量（避免跳動）
  const smoothVolumeRef = useRef(0);
  // 光暈亮度平滑（避免逐幀閃爍）
  const smoothGlowRef = useRef(0.08);
  // 用 ref 持有動態數據，讓 draw callback 不因 props 變化而重建
  const statusRef = useRef(status);
  const volumeRef = useRef(volume);
  useEffect(() => { statusRef.current = status; }, [status]);
  useEffect(() => { volumeRef.current = volume; }, [volume]);

  // 頻譜驅動：從 store 讀取 AnalyserNode，同步到 ref（rAF 迴圈直接讀 ref，不訂閱 store）
  const storeAnalyser = useStore(s => s.analyser);
  const analyserRef = useRef<AnalyserNode | null>(null);
  useEffect(() => { analyserRef.current = storeAnalyser; }, [storeAnalyser]);
  // 頻率資料陣列（重用，不每幀 new）：fftSize=256 → 128 bin
  const freqDataRef = useRef(new Uint8Array(128));
  // 每個 band 的平滑後能量（上升快、衰減慢，講話停頓時長條緩緩落下）
  const smoothBandsRef = useRef(new Float32Array(BAND_COUNT));

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    if (w === 0 || h === 0) return;

    // scale 根據實際 CSS 尺寸動態計算，基準 256px
    const scale = Math.min(w, h) / 256;

    const cx = w / 2;
    const cy = h / 2;
    ctx.clearRect(0, 0, w, h);

    // 從 ref 讀取最新值（避免 useCallback 依賴 volume/status 導致 rAF 鏈每幀重建）
    const currentVolume = volumeRef.current;
    const currentStatus = statusRef.current;

    // 平滑音量
    const sv = smoothVolumeRef.current;
    smoothVolumeRef.current += (currentVolume - sv) * 0.15;
    const vol = smoothVolumeRef.current;

    // 顏色平滑過渡
    const targetHex = STATUS_COLORS[currentStatus];
    const tr = parseInt(targetHex.slice(1, 3), 16);
    const tg = parseInt(targetHex.slice(3, 5), 16);
    const tb = parseInt(targetHex.slice(5, 7), 16);
    const cr = colorRef.current;
    cr.r += (tr - cr.r) * 0.05;
    cr.g += (tg - cr.g) * 0.05;
    cr.b += (tb - cr.b) * 0.05;
    const hex = `#${Math.round(cr.r).toString(16).padStart(2, '0')}${Math.round(cr.g).toString(16).padStart(2, '0')}${Math.round(cr.b).toString(16).padStart(2, '0')}`;

    const t = phaseRef.current;
    phaseRef.current += 0.016;

    // 頻譜讀取：listening/speaking 時從 AnalyserNode 取得頻率資料
    let hasSpectrum = false;
    const bands = smoothBandsRef.current;
    const currentAnalyser = analyserRef.current;
    if (currentAnalyser && (currentStatus === 'listening' || currentStatus === 'speaking')) {
      try {
        currentAnalyser.getByteFrequencyData(freqDataRef.current);
        hasSpectrum = true;
        for (let b = 0; b < BAND_COUNT; b++) {
          const startBin = Math.floor(b * VALID_BINS / BAND_COUNT);
          const endBin = Math.floor((b + 1) * VALID_BINS / BAND_COUNT);
          let sum = 0;
          for (let j = startBin; j < endBin; j++) sum += freqDataRef.current[j];
          const raw = sum / ((endBin - startBin) * 255); // 正規化 0-1
          // 去噪底 + 提高對比
          const shaped = Math.pow(Math.max(0, raw - 0.06) / 0.94, 1.3);
          const prev = bands[b];
          // 上升較快（0.5）、衰減慢（0.12）：跟得上音節又不會逐幀抖動
          bands[b] = shaped > prev ? prev + (shaped - prev) * 0.5 : prev + (shaped - prev) * 0.12;
        }
      } catch {
        // analyser 已分離（AudioContext 關閉等），安靜降級回音量模式
        hasSpectrum = false;
      }
    } else {
      // 無頻譜時長條緩緩歸零
      for (let b = 0; b < BAND_COUNT; b++) bands[b] *= 0.9;
    }

    // 狀態參數
    let glowTarget = 0.08;
    let idleWave = false;    // idle/processing 的長條波浪動畫
    let waveSpeed = 1;

    switch (currentStatus) {
      case 'idle':
        glowTarget = 0.08;
        idleWave = true;
        waveSpeed = 1.2;
        break;
      case 'listening':
        glowTarget = 0.12 + vol * 0.15;
        break;
      case 'processing':
        glowTarget = 0.16;
        idleWave = true;
        waveSpeed = 4;
        break;
      case 'speaking':
        glowTarget = 0.12 + vol * 0.12;
        break;
    }

    // 光暈亮度用慢速 lerp（0.08），避免逐幀閃爍
    smoothGlowRef.current += (glowTarget - smoothGlowRef.current) * 0.08;
    const glowAlpha = smoothGlowRef.current;

    // ====== 背景光暈 ======
    const glowR = Math.min(w, h) * 0.42;
    const glow = ctx.createRadialGradient(cx, cy, glowR * 0.15, cx, cy, glowR);
    glow.addColorStop(0, rgba(hex, glowAlpha));
    glow.addColorStop(0.6, rgba(hex, glowAlpha * 0.35));
    glow.addColorStop(1, 'transparent');
    ctx.beginPath();
    ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
    ctx.fillStyle = glow;
    ctx.fill();

    // ====== 中央對稱頻譜條 ======
    // 排列：中央低頻、往兩側漸高頻（鏡像對稱）；小尺寸減少條數
    const halfCount = isSmall ? 8 : BAND_COUNT;
    const totalBars = halfCount * 2 - 1;
    const areaW = w * 0.72;
    const gap = areaW / totalBars;
    const barW = Math.max(gap * 0.55, 2);
    const minH = 4 * scale;
    const maxH = Math.min(h * 0.68, 175 * scale);

    for (let i = 0; i < totalBars; i++) {
      // 距中心的顯示位置 → 對應 band：中央 bar = band 0（低頻）
      const dist = Math.abs(i - (halfCount - 1));
      const bandIdx = Math.min(Math.floor(dist * BAND_COUNT / halfCount), BAND_COUNT - 1);

      let level: number;
      if (hasSpectrum) {
        level = bands[bandIdx];
      } else if (idleWave) {
        // idle：緩慢波浪；processing：快速跑動波
        level = 0.08 + 0.06 * (1 + Math.sin(t * waveSpeed - bandIdx * 0.7));
      } else {
        // 無頻譜的 listening/speaking fallback：音量 + 每條相位差
        level = vol * (0.5 + 0.5 * Math.sin(t * 3 + bandIdx * 0.9));
      }

      // 中央高、兩側漸低的包絡（cos 曲線），亮度同步漸暗
      const centerFrac = 1 - Math.abs(i - (totalBars - 1) / 2) / ((totalBars - 1) / 2);
      const envelope = 0.25 + 0.75 * Math.sin(centerFrac * Math.PI / 2);
      const bh = minH + level * envelope * (maxH - minH);
      const bx = cx - areaW / 2 + gap * (i + 0.5);

      const alpha = 0.35 + centerFrac * 0.5;

      ctx.fillStyle = rgba(hex, alpha);
      // 長條主體 + 上下圓頭（不用 roundRect，維持廣泛相容）
      ctx.fillRect(bx - barW / 2, cy - bh / 2, barW, bh);
      ctx.beginPath();
      ctx.arc(bx, cy - bh / 2, barW / 2, 0, Math.PI * 2);
      ctx.arc(bx, cy + bh / 2, barW / 2, 0, Math.PI * 2);
      ctx.fill();
    }

    animationRef.current = requestAnimationFrame(draw);
  }, [isSmall]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const dpr = window.devicePixelRatio || 1;

    const updateCanvasSize = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.scale(dpr, dpr);
      }
    };

    updateCanvasSize();

    const observer = new ResizeObserver(() => {
      updateCanvasSize();
      cancelAnimationFrame(animationRef.current);
      animationRef.current = requestAnimationFrame(draw);
    });
    observer.observe(canvas);

    animationRef.current = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(animationRef.current);
      observer.disconnect();
    };
  }, [draw]);

  // canvas 不設固定 width/height attribute，完全填滿父容器
  // 由父層（motion.div）控制尺寸動畫，ResizeObserver 自動跟進
  return (
    <canvas
      ref={canvasRef}
      style={{ display: 'block', width: '100%', height: '100%' }}
    />
  );
}
