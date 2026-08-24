'use client';

import { useEffect, useState } from 'react';

import { styleNames, type StyleName } from './presets';
import { DEFAULT_ORB_STYLE, getStoredOrbStyle, setStoredOrbStyle } from './orb-style';

// 球體樣式選單：寫入 localStorage 並發事件，OrbVisualizer 即時切換

const STYLE_LABELS: Record<StyleName, string> = {
  siri: 'Siri 經典',
  voiceWave: '聲波',
  spectrum: '光譜',
  aurora: '極光',
  frost: '霜白',
  plasma: '電漿',
  chrome: '鏡面',
  opal: '蛋白石',
  blueDrop: '藍水滴',
  violetEmber: '紫燼',
  chromaticMetal: '虹彩金屬',
};

export default function OrbStyleSelector() {
  const [style, setStyle] = useState<StyleName>(DEFAULT_ORB_STYLE);

  // SSR 時沒有 localStorage，掛載後再同步實際選擇
  useEffect(() => {
    setStyle(getStoredOrbStyle());
  }, []);

  const handleChange = (next: StyleName) => {
    setStyle(next);
    setStoredOrbStyle(next);
  };

  return (
    <select
      value={style}
      onChange={(e) => handleChange(e.target.value as StyleName)}
      aria-label="球體樣式"
      className="text-xs rounded-full px-3 py-1.5 cursor-pointer outline-none"
      style={{
        color: 'var(--text-muted)',
        backgroundColor: 'var(--background-tertiary)',
        border: '1px solid var(--border-color)',
      }}
    >
      {styleNames.map((name) => (
        <option key={name} value={name}>
          球體：{STYLE_LABELS[name]}
        </option>
      ))}
    </select>
  );
}
