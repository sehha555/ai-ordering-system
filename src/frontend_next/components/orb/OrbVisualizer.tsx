'use client';

import { useEffect, useRef, useState } from 'react';

import { AppStatus } from '../../types';
import AudioVisualizer, { STATUS_COLORS } from '../AudioVisualizer';
import { createOrbRenderer } from './orb-renderer';
import { stylePresets, type OrbParams, type StyleName } from './presets';
import { ORB_STYLE_EVENT, DEFAULT_ORB_STYLE, getStoredOrbStyle } from './orb-style';

// 液態玻璃球視覺化（orb repo, MIT: https://github.com/LerSent001/orb）
// 樣式由 OrbStyleSelector 切換（orb-style.ts：localStorage + window event）
// 依語音狀態調變所選樣式：待機呼吸、聆聽變速、處理變形、講話發光
// WebGPU 初始化失敗時，自動退回原本的 AudioVisualizer 頻譜條

interface OrbVisualizerProps {
  status: AppStatus;
  volume?: number;
}

// 狀態調變：以所選預設為基底，乘/加上狀態差異；狀態色沿用 AudioVisualizer 的 STATUS_COLORS
const SPEED_FACTOR: Record<AppStatus, number> = { idle: 0.7, listening: 1.4, processing: 2.6, speaking: 1.6 };
const DEFORM_ADD: Record<AppStatus, number> = { idle: 0, listening: 0.06, processing: 0.25, speaking: 0.04 };
const GLOW_ADD: Record<AppStatus, number> = { idle: 0, listening: 0.12, processing: 0.15, speaking: 0.45 };
const STATUS_TINT_AMOUNT: Partial<Record<AppStatus, number>> = { listening: 0.5, processing: 0.55, speaking: 0.3 };

// 品牌配色覆蓋（整體風格 #729DAD 系）：預設樣式 voiceWave 由洋紅換成品牌藍。
// 其他樣式保留原色 —— 使用者主動選某個樣式時，要的就是那個樣式本來的顏色。
const VOICE_WAVE_BRAND: Partial<OrbParams> = {
  colorA: '#0a1114',
  colorB: '#729DAD',
  colorC: '#8fb3c0',
  colorD: '#4a7080',
  highlightColor: '#e7f2f6',
  shellMid: '#8fb3c0',
  shellEdge: '#729DAD',
  sheenColor: '#f4fafc',
  specColor: '#d9e9ee',
  canvasColor: '#020404',
  glowColor: '#729DAD',
};

// 球體相對容器的縮放（preset 原始半徑偏大，整體縮小）
const RADIUS_SCALE = 0.78;
const LERP = 0.06;

// 無配置版 hex 內插：整數位元運算，避免每幀產生中間陣列與子字串
function lerpHex(from: string, to: string, k: number): string {
  const f = parseInt(from.slice(1), 16);
  const t = parseInt(to.slice(1), 16);
  const fr = f >> 16, fg = (f >> 8) & 255, fb = f & 255;
  const r = Math.round(fr + (((t >> 16) & 255) - fr) * k);
  const g = Math.round(fg + (((t >> 8) & 255) - fg) * k);
  const b = Math.round(fb + ((t & 255) - fb) * k);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
}

// OrbParams 欄位分類：模組載入時算一次，避免每幀 Object.keys + typeof 分派
// speed 獨立處理（每幀受音量推動），不放進 NUMERIC_KEYS
const SAMPLE: OrbParams = { style: DEFAULT_ORB_STYLE, ...stylePresets[DEFAULT_ORB_STYLE] };
const NUMERIC_KEYS = Object.keys(SAMPLE).filter(
  (k) => k !== 'speed' && typeof SAMPLE[k as keyof OrbParams] === 'number',
);
const COLOR_KEYS = Object.keys(SAMPLE).filter((k) => {
  const v = SAMPLE[k as keyof OrbParams];
  return typeof v === 'string' && v.startsWith('#');
});

function buildTarget(style: StyleName, status: AppStatus): OrbParams {
  const target: OrbParams = {
    style,
    ...stylePresets[style],
    ...(style === 'voiceWave' ? VOICE_WAVE_BRAND : {}),
  };
  target.radius *= RADIUS_SCALE;
  target.speed *= SPEED_FACTOR[status];
  target.contourDeform += DEFORM_ADD[status];
  target.edgeGlow += GLOW_ADD[status];

  const amount = STATUS_TINT_AMOUNT[status];
  if (amount) {
    const tint = STATUS_COLORS[status];
    target.colorA = lerpHex(target.colorA, tint, amount);
    target.colorB = lerpHex(target.colorB, tint, amount);
    target.colorC = lerpHex(target.colorC, tint, amount);
    target.colorD = lerpHex(target.colorD, tint, amount);
    target.glowColor = lerpHex(target.glowColor, tint, 0.7);
  }
  return target;
}

export default function OrbVisualizer({ status, volume = 0 }: OrbVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [gpuFailed, setGpuFailed] = useState(false);

  // rAF 迴圈直接讀 ref，不因 props / 樣式變化重建 renderer
  const statusRef = useRef(status);
  const volumeRef = useRef(volume);
  const styleRef = useRef<StyleName>(DEFAULT_ORB_STYLE);
  useEffect(() => { statusRef.current = status; }, [status]);
  useEffect(() => { volumeRef.current = volume; }, [volume]);

  // 樣式：初始讀 localStorage，之後聽 OrbStyleSelector 發的事件（localStorage 為單一來源）
  useEffect(() => {
    const syncStyle = () => { styleRef.current = getStoredOrbStyle(); };
    syncStyle();
    window.addEventListener(ORB_STYLE_EVENT, syncStyle);
    return () => window.removeEventListener(ORB_STYLE_EVENT, syncStyle);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // target 只在 (style, status) 變化時重建；每幀只做 lerp 與音量推速度
    let lastStyle: StyleName | null = null;
    let lastStatus: AppStatus | null = null;
    let target: OrbParams | null = null;
    let current: OrbParams | null = null;
    let smoothVol = 0;

    return createOrbRenderer({
      canvas,
      getParams: () => {
        const s = statusRef.current;
        const style = styleRef.current;
        if (style !== lastStyle || s !== lastStatus) {
          target = buildTarget(style, s);
          lastStyle = style;
          lastStatus = s;
          if (!current) current = { ...target };
        }
        const t = target as OrbParams;
        const c = current as OrbParams;

        // 音量平滑後推動轉速（只有聽/講兩態）
        smoothVol += (volumeRef.current - smoothVol) * 0.15;
        const volBoost = (s === 'listening' || s === 'speaking') ? smoothVol * 0.9 : 0;
        c.speed += (t.speed + volBoost - c.speed) * LERP;

        const cn = c as unknown as Record<string, number>;
        const tn = t as unknown as Record<string, number>;
        for (const k of NUMERIC_KEYS) cn[k] += (tn[k] - cn[k]) * LERP;

        const cs = c as unknown as Record<string, string>;
        const ts = t as unknown as Record<string, string>;
        for (const k of COLOR_KEYS) cs[k] = lerpHex(cs[k], ts[k], LERP);

        c.style = t.style;
        c.glassEnabled = t.glassEnabled;
        return c;
      },
      onError: () => setGpuFailed(true),
      onReady: () => {},
    });
  }, []);

  if (gpuFailed) {
    return <AudioVisualizer status={status} volume={volume} />;
  }

  return (
    <canvas
      ref={canvasRef}
      style={{ display: 'block', width: '100%', height: '100%' }}
    />
  );
}
