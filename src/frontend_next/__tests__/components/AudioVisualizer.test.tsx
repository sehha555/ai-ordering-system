import { render, screen, act } from '@testing-library/react';
import { vi, describe, it, expect, beforeAll, afterEach } from 'vitest';
import AudioVisualizer from '../../components/AudioVisualizer';

// jsdom 不支援 canvas，mock getContext 及所有畫布方法
beforeAll(() => {
  const mockCtx = {
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    arc: vi.fn(),
    fillRect: vi.fn(),
    closePath: vi.fn(),
    createRadialGradient: vi.fn().mockReturnValue({
      addColorStop: vi.fn(),
    }),
    scale: vi.fn(),
    setTransform: vi.fn(),
    strokeStyle: '',
    fillStyle: '',
    lineWidth: 0,
  };
  HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(mockCtx);

  // jsdom 不支援 getBoundingClientRect 回傳非零值，給予固定 rect
  HTMLCanvasElement.prototype.getBoundingClientRect = vi.fn().mockReturnValue({
    width: 256,
    height: 256,
    top: 0,
    left: 0,
    right: 256,
    bottom: 256,
    x: 0,
    y: 0,
    toJSON: vi.fn(),
  });

  // mock requestAnimationFrame / cancelAnimationFrame
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
    // 僅執行一次，避免無限遞迴
    return setTimeout(() => cb(0), 0) as unknown as number;
  });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation((id) => {
    clearTimeout(id as unknown as ReturnType<typeof setTimeout>);
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('AudioVisualizer', () => {
  describe('渲染測試', () => {
    it('idle 狀態應正確渲染 canvas', () => {
      render(<AudioVisualizer status="idle" />);
      const canvas = document.querySelector('canvas');
      expect(canvas).toBeInTheDocument();
    });

    it('各狀態都應正確渲染 canvas', () => {
      const statuses = ['listening', 'processing', 'speaking'] as const;
      for (const s of statuses) {
        const { unmount } = render(<AudioVisualizer status={s} />);
        expect(document.querySelector('canvas')).toBeInTheDocument();
        unmount();
      }
    });
  });

  describe('Props 測試', () => {
    it('傳入 volume prop 不應報錯', () => {
      expect(() => {
        render(<AudioVisualizer status="listening" volume={0.5} />);
      }).not.toThrow();
    });

    it('volume 為 0 時不應報錯', () => {
      expect(() => {
        render(<AudioVisualizer status="idle" volume={0} />);
      }).not.toThrow();
    });

    it('volume 為 1 時不應報錯', () => {
      expect(() => {
        render(<AudioVisualizer status="listening" volume={1} />);
      }).not.toThrow();
    });
  });

  describe('Cleanup 測試', () => {
    it('元件 unmount 時不應報錯', () => {
      const { unmount } = render(<AudioVisualizer status="idle" />);
      expect(() => {
        act(() => {
          unmount();
        });
      }).not.toThrow();
    });

    it('狀態切換後元件不應報錯', () => {
      const { rerender } = render(<AudioVisualizer status="idle" />);
      expect(() => {
        rerender(<AudioVisualizer status="listening" />);
        rerender(<AudioVisualizer status="processing" />);
        rerender(<AudioVisualizer status="speaking" />);
        rerender(<AudioVisualizer status="idle" />);
      }).not.toThrow();
    });
  });
});
