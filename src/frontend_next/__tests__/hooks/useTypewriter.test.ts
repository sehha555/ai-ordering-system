import { renderHook, act } from '@testing-library/react';
import { useTypewriter } from '../../hooks/useTypewriter';

// timeout 是鏈式排程（effect 跑完才排下一個），每打一字要各自 advance 一次
const typeChars = (n: number) => {
  for (let i = 0; i < n; i++) {
    act(() => vi.advanceTimersByTime(35));
  }
};

describe('useTypewriter', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('逐字打出文字', () => {
    const { result } = renderHook(() => useTypewriter('你好嗎', 35));
    expect(result.current).toBe('');

    typeChars(1);
    expect(result.current).toBe('你');

    typeChars(2);
    expect(result.current).toBe('你好嗎');
  });

  it('initialIndex 從指定位置接續，不重打前段', () => {
    const { result } = renderHook(() => useTypewriter('好的，飯糰要白米紫米？', 35, 5));
    expect(result.current).toBe('好的，飯糰');

    typeChars(1);
    expect(result.current).toBe('好的，飯糰要');
  });

  it('打完後停止，不再變動', () => {
    const { result } = renderHook(() => useTypewriter('嗨', 35));
    typeChars(5);
    expect(result.current).toBe('嗨');
  });

  it('文字清空時重置進度', () => {
    const { result, rerender } = renderHook(({ text }) => useTypewriter(text, 35), {
      initialProps: { text: '你好' },
    });
    typeChars(2);
    expect(result.current).toBe('你好');

    rerender({ text: '' });
    expect(result.current).toBe('');
  });
});
