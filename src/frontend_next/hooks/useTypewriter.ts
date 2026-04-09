import { useEffect, useState } from 'react';

/** 逐字顯示 hook — 新 chunk 到達時從已顯示位置繼續打字 */
export function useTypewriter(text: string, speed = 35): string {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!text) { setIndex(0); return; }
    if (index >= text.length) return;

    const timer = setTimeout(() => setIndex((i) => i + 1), speed);
    return () => clearTimeout(timer);
  }, [text, index, speed]);

  return text.slice(0, index);
}
