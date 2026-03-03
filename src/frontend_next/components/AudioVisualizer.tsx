'use client';

import { useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AppStatus } from '../types';

interface AudioVisualizerProps {
  status: AppStatus;
  volume?: number;
  size?: 'large' | 'small';
}

const STATUS_COLORS: Record<AppStatus, string> = {
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
  const isSmall = size === 'small';
  const canvasSize = isSmall ? 40 : 256;
  const scale = isSmall ? 40 / 256 : 1;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>(0);
  const phaseRef = useRef(0);
  const colorRef = useRef({ r: 114, g: 157, b: 173 });
  // 平滑音量（避免跳動）
  const smoothVolumeRef = useRef(0);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const w = canvas.width / dpr;
    const h = canvas.height / dpr;
    if (w === 0 || h === 0) return;

    const cx = w / 2;
    const cy = h / 2;
    ctx.clearRect(0, 0, w, h);

    // 平滑音量
    const sv = smoothVolumeRef.current;
    smoothVolumeRef.current += (volume - sv) * 0.15;
    const vol = smoothVolumeRef.current;

    // 顏色平滑過渡
    const targetHex = STATUS_COLORS[status];
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

    const baseR = Math.min(w, h) * 0.25;

    // 狀態參數
    let noiseAmp = 0;      // 表面噪點振幅
    let breathAmp = 0;     // 呼吸振幅
    let breathSpeed = 0;
    let waveCount = 6;     // 表面波浪數
    let waveSpeed = 1;
    let glowAlpha = 0.1;
    let scaleFactor = 1;   // 整體大小隨音量
    let rimAlpha = 0.3;    // 邊緣亮度

    switch (status) {
      case 'idle':
        noiseAmp = 3 * scale;
        breathAmp = 6 * scale;
        breathSpeed = 0.8;
        waveCount = 5;
        waveSpeed = 0.6;
        glowAlpha = 0.08;
        rimAlpha = 0.2;
        break;
      case 'listening':
        noiseAmp = (5 + vol * 25) * scale;
        breathAmp = (4 + vol * 15) * scale;
        breathSpeed = 1.2;
        waveCount = 7;
        waveSpeed = 1.5 + vol * 2;
        glowAlpha = 0.1 + vol * 0.2;
        scaleFactor = 1 + vol * 0.25;
        rimAlpha = 0.3 + vol * 0.4;
        break;
      case 'processing':
        noiseAmp = 12 * scale;
        breathAmp = 8 * scale;
        breathSpeed = 2;
        waveCount = 8;
        waveSpeed = 3;
        glowAlpha = 0.18;
        scaleFactor = 1.05 + Math.sin(t * 3) * 0.05;
        rimAlpha = 0.4;
        break;
      case 'speaking':
        noiseAmp = (8 + Math.sin(t * 2.5) * 6) * scale;
        breathAmp = (10 + Math.sin(t * 1.8) * 5) * scale;
        breathSpeed = 1.5;
        waveCount = 6;
        waveSpeed = 2;
        glowAlpha = 0.15;
        scaleFactor = 1.08 + Math.sin(t * 2) * 0.06;
        rimAlpha = 0.35;
        break;
    }

    const breath = Math.sin(t * breathSpeed) * breathAmp;
    const effectiveR = (baseR + breath) * scaleFactor;

    // ====== 外層光暈 ======
    const glowR = effectiveR + 40 * scale;
    const glow = ctx.createRadialGradient(cx, cy, effectiveR * 0.3, cx, cy, glowR);
    glow.addColorStop(0, rgba(hex, glowAlpha));
    glow.addColorStop(0.5, rgba(hex, glowAlpha * 0.3));
    glow.addColorStop(1, 'transparent');
    ctx.beginPath();
    ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
    ctx.fillStyle = glow;
    ctx.fill();

    // ====== 球體表面（帶噪點變形的圓）======
    // 計算變形後的輪廓點
    const points: Array<{ x: number; y: number; r: number }> = [];
    const pointCount = isSmall ? 60 : 120;

    for (let i = 0; i < pointCount; i++) {
      const angle = (i / pointCount) * Math.PI * 2;
      // 多層噪點疊加模擬球體表面
      const n1 = Math.sin(angle * waveCount + t * waveSpeed) * noiseAmp;
      const n2 = Math.sin(angle * (waveCount + 3) - t * waveSpeed * 0.7) * noiseAmp * 0.4;
      const n3 = Math.sin(angle * (waveCount * 2) + t * waveSpeed * 1.3) * noiseAmp * 0.2;
      const localR = effectiveR + n1 + n2 + n3;
      points.push({
        x: cx + Math.cos(angle) * localR,
        y: cy + Math.sin(angle) * localR,
        r: localR,
      });
    }

    // 球體填充：放射漸層模擬 3D 光照
    // 光源偏左上，營造球體立體感
    const lightOffX = -effectiveR * 0.25;
    const lightOffY = -effectiveR * 0.25;
    const sphereGrad = ctx.createRadialGradient(
      cx + lightOffX, cy + lightOffY, effectiveR * 0.1,
      cx, cy, effectiveR + noiseAmp,
    );
    sphereGrad.addColorStop(0, rgba(hex, 0.35));
    sphereGrad.addColorStop(0.4, rgba(hex, 0.2));
    sphereGrad.addColorStop(0.75, rgba(hex, 0.1));
    sphereGrad.addColorStop(1, rgba(hex, 0.03));

    // 繪製填充
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
      const prev = points[i - 1];
      const curr = points[i];
      const cpx = (prev.x + curr.x) / 2;
      const cpy = (prev.y + curr.y) / 2;
      ctx.quadraticCurveTo(prev.x, prev.y, cpx, cpy);
    }
    ctx.closePath();
    ctx.fillStyle = sphereGrad;
    ctx.fill();

    // 邊緣線（rim light 效果）
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i++) {
      const prev = points[i - 1];
      const curr = points[i];
      const cpx = (prev.x + curr.x) / 2;
      const cpy = (prev.y + curr.y) / 2;
      ctx.quadraticCurveTo(prev.x, prev.y, cpx, cpy);
    }
    ctx.closePath();
    ctx.strokeStyle = rgba(hex, rimAlpha);
    ctx.lineWidth = isSmall ? 1 : 2;
    ctx.stroke();

    // ====== 球體內部高光（模擬反射）======
    if (!isSmall) {
      // 主高光（左上方）
      const hlR = effectiveR * 0.35;
      const hlGrad = ctx.createRadialGradient(
        cx + lightOffX * 1.2, cy + lightOffY * 1.2, 0,
        cx + lightOffX * 1.2, cy + lightOffY * 1.2, hlR,
      );
      hlGrad.addColorStop(0, 'rgba(255,255,255,0.15)');
      hlGrad.addColorStop(0.5, 'rgba(255,255,255,0.05)');
      hlGrad.addColorStop(1, 'transparent');
      ctx.beginPath();
      ctx.arc(cx + lightOffX * 1.2, cy + lightOffY * 1.2, hlR, 0, Math.PI * 2);
      ctx.fillStyle = hlGrad;
      ctx.fill();

      // 底部邊緣反光
      const rimGrad = ctx.createRadialGradient(
        cx + effectiveR * 0.15, cy + effectiveR * 0.3, 0,
        cx + effectiveR * 0.15, cy + effectiveR * 0.3, effectiveR * 0.3,
      );
      rimGrad.addColorStop(0, rgba(hex, 0.12));
      rimGrad.addColorStop(1, 'transparent');
      ctx.beginPath();
      ctx.arc(cx + effectiveR * 0.15, cy + effectiveR * 0.3, effectiveR * 0.3, 0, Math.PI * 2);
      ctx.fillStyle = rimGrad;
      ctx.fill();
    }

    // ====== 表面經緯線（增加球體感）======
    if (!isSmall) {
      ctx.save();
      // 用 clip 限制在球體輪廓內
      ctx.beginPath();
      ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        const prev = points[i - 1];
        const curr = points[i];
        ctx.quadraticCurveTo(prev.x, prev.y, (prev.x + curr.x) / 2, (prev.y + curr.y) / 2);
      }
      ctx.closePath();
      ctx.clip();

      // 緯線（水平橢圓）
      const latCount = 5;
      for (let i = 1; i < latCount; i++) {
        const frac = i / latCount;
        const latY = cy - effectiveR + frac * effectiveR * 2;
        const dist = Math.abs(latY - cy) / effectiveR;
        const latRx = effectiveR * Math.sqrt(1 - dist * dist);
        const latRy = latRx * 0.15; // 壓扁成橢圓

        ctx.beginPath();
        ctx.ellipse(cx, latY, latRx, latRy, 0, 0, Math.PI * 2);
        ctx.strokeStyle = rgba(hex, 0.06 + (1 - dist) * 0.04);
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }

      // 經線（垂直橢圓）
      const lonCount = 6;
      for (let i = 0; i < lonCount; i++) {
        const lonAngle = (i / lonCount) * Math.PI + t * 0.1;
        const lonRx = effectiveR * Math.abs(Math.sin(lonAngle));
        const lonRy = effectiveR;

        ctx.beginPath();
        ctx.ellipse(cx, cy, lonRx, lonRy, 0, 0, Math.PI * 2);
        ctx.strokeStyle = rgba(hex, 0.05);
        ctx.lineWidth = 0.5;
        ctx.stroke();
      }

      ctx.restore();
    }

    // ====== 中心亮點 ======
    const dotR = Math.max(2.5 * scale, 1);
    ctx.beginPath();
    ctx.arc(cx, cy, dotR, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255,255,255,0.6)';
    ctx.fill();

    animationRef.current = requestAnimationFrame(draw);
  }, [status, volume, scale, isSmall]);

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

  const statusText: Record<AppStatus, string> = {
    idle: '點擊開始',
    listening: '聆聽中...',
    processing: '處理中...',
    speaking: '回覆中...',
  };

  if (isSmall) {
    return (
      <canvas
        ref={canvasRef}
        width={canvasSize}
        height={canvasSize}
        style={{ width: canvasSize, height: canvasSize }}
      />
    );
  }

  return (
    <div className="flex flex-col items-center gap-4">
      <canvas
        ref={canvasRef}
        width={256}
        height={256}
        className="w-64 h-64 cursor-pointer"
        style={{ width: 256, height: 256 }}
      />
      <div className="h-7 flex items-center justify-center overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.p
            key={status}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.2 }}
            className="text-lg font-medium"
            style={{ color: STATUS_COLORS[status] }}
          >
            {statusText[status]}
          </motion.p>
        </AnimatePresence>
      </div>
    </div>
  );
}
