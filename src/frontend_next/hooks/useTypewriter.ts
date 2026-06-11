import { useEffect, useState } from 'react';

/** 逐字顯示 hook — 新 chunk 到達時從已顯示位置繼續打字；initialIndex 可從指定位置接續 */
export function useTypewriter(text: string, speed = 35, initialIndex = 0): string {
  const [index, setIndex] = useState(initialIndex);

  useEffect(() => {
    if (!text) { setIndex(0); return; }
    if (index >= text.length) return;

    const timer = setTimeout(() => setIndex((i) => i + 1), speed);
    return () => clearTimeout(timer);
  }, [text, index, speed]);

  return text.slice(0, index);
}
