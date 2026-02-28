'use client';

import { useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AppStatus } from '../types';

interface AudioVisualizerProps {
  status: AppStatus;
  volume?: number; // 0-1 range for mic input level
  size?: 'large' | 'small';
}

// 狀態對應的顏色 - 品牌色系
const STATUS_COLORS: Record<AppStatus, string> = {
  idle: '#729DAD',      // brand primary
  listening: '#4a9d68', // success green
  processing: '#c49a30', // warning amber
  speaking: '#5a8494',  // accent-dark
};

export default function AudioVisualizer({ status, volume = 0, size = 'large' }: AudioVisualizerProps) {
  const isSmall = size === 'small';
  const canvasSize = isSmall ? 40 : 256;
  // small 模式縮放比例（40/256 ≈ 0.156）
  const scale = isSmall ? 40 / 256 : 1;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number>(0);
  const phaseRef = useRef<number>(0);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;

    // 元素不可見（display:none）時 dimensions 為 0，暫停繪製，不排下一幀
    if (width === 0 || height === 0) return;

    const centerX = width / 2;
    const centerY = height / 2;

    // 清除畫布
    ctx.clearRect(0, 0, width, height);

    const color = STATUS_COLORS[status];
    const baseRadius = Math.min(width, height) * 0.25;

    // 根據狀態計算動畫參數
    let radiusOffset = 0;
    let pulseSpeed = 0.02;
    let waveAmplitude = 5;

    switch (status) {
      case 'idle':
        // 緩慢呼吸效果
        pulseSpeed = 0.015;
        waveAmplitude = 3 * scale;
        radiusOffset = Math.sin(phaseRef.current) * 8 * scale;
        break;
      case 'listening':
        // 根據音量變化
        pulseSpeed = 0.03;
        waveAmplitude = (10 + volume * 30) * scale;
        radiusOffset = volume * 40 * scale;
        break;
      case 'processing':
        // 快速旋轉效果
        pulseSpeed = 0.05;
        waveAmplitude = 15 * scale;
        radiusOffset = Math.sin(phaseRef.current * 3) * 12 * scale;
        break;
      case 'speaking':
        // 說話時的脈動
        pulseSpeed = 0.04;
        waveAmplitude = 20 * scale;
        radiusOffset = Math.sin(phaseRef.current * 2) * 15 * scale;
        break;
    }

    phaseRef.current += pulseSpeed;

    // 繪製外圈光暈
    const glowExtra = 50 * scale;
    const gradient = ctx.createRadialGradient(
      centerX, centerY, baseRadius * 0.5,
      centerX, centerY, baseRadius + radiusOffset + glowExtra
    );
    gradient.addColorStop(0, color + '40'); // 25% opacity
    gradient.addColorStop(0.7, color + '20'); // 12% opacity
    gradient.addColorStop(1, 'transparent');

    ctx.beginPath();
    ctx.arc(centerX, centerY, baseRadius + radiusOffset + glowExtra, 0, Math.PI * 2);
    ctx.fillStyle = gradient;
    ctx.fill();

    // 繪製波浪圓圈
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = isSmall ? 1.5 : 3;

    for (let angle = 0; angle < Math.PI * 2; angle += 0.02) {
      const wave = Math.sin(angle * 8 + phaseRef.current * 4) * waveAmplitude;
      const r = baseRadius + radiusOffset + wave;
      const x = centerX + Math.cos(angle) * r;
      const y = centerY + Math.sin(angle) * r;

      if (angle === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    }
    ctx.closePath();
    ctx.stroke();

    // 繪製內圈
    ctx.beginPath();
    ctx.arc(centerX, centerY, baseRadius * 0.6 + radiusOffset * 0.3, 0, Math.PI * 2);
    ctx.fillStyle = color + '30';
    ctx.fill();

    // 繪製中心點
    ctx.beginPath();
    ctx.arc(centerX, centerY, 8 * scale, 0, Math.PI * 2);
    ctx.fillStyle = color;
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
      if (ctx) ctx.scale(dpr, dpr);
    };

    updateCanvasSize();

    // 元素從 hidden → visible 時重啟 rAF（ResizeObserver 偵測尺寸恢復）
    const observer = new ResizeObserver(() => {
      updateCanvasSize();
      cancelAnimationFrame(animationRef.current);
      animationRef.current = requestAnimationFrame(draw);
    });
    observer.observe(canvas);

    // 開始動畫
    animationRef.current = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(animationRef.current);
      observer.disconnect();
    };
  }, [draw]);

  // 狀態文字
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
