import { styleNames, type StyleName } from './presets';

// 球體樣式的持久化（localStorage）與跨元件通知（window event）。
// 抽成 leaf 模組讓 OrbStyleSelector 不必 import 渲染器元件。
// 之後若要收進 Zustand store，改這裡的讀寫即可。

export const ORB_STYLE_KEY = 'orbStyle';
export const ORB_STYLE_EVENT = 'orb-style-change';
export const DEFAULT_ORB_STYLE: StyleName = 'voiceWave';

export function getStoredOrbStyle(): StyleName {
  if (typeof window === 'undefined') return DEFAULT_ORB_STYLE;
  const stored = localStorage.getItem(ORB_STYLE_KEY);
  return (styleNames as readonly string[]).includes(stored ?? '')
    ? (stored as StyleName)
    : DEFAULT_ORB_STYLE;
}

export function setStoredOrbStyle(next: StyleName): void {
  localStorage.setItem(ORB_STYLE_KEY, next);
  window.dispatchEvent(new Event(ORB_STYLE_EVENT));
}
