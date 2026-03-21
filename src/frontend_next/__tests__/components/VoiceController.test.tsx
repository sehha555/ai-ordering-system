import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import VoiceController from '../../components/VoiceController';
import { useStore } from '../../store/useStore';

// Mock AudioVisualizer 子元件
vi.mock('../../components/AudioVisualizer', () => ({
  default: ({ status, volume }: { status: string; volume: number }) => (
    <div data-testid="audio-visualizer" data-status={status} data-volume={volume} />
  ),
}));

// Mock MicSelector 的 getPreferredMicStream
vi.mock('../../components/MicSelector', () => ({
  getPreferredMicStream: vi.fn().mockResolvedValue({
    getTracks: () => [{ stop: vi.fn() }],
  }),
  default: () => null,
}));

// Mock navigator.mediaDevices
const mockGetUserMedia = vi.fn().mockResolvedValue({
  getTracks: () => [{ stop: vi.fn() }],
});
Object.defineProperty(navigator, 'mediaDevices', {
  value: { getUserMedia: mockGetUserMedia },
  writable: true,
});

// Mock MediaRecorder
class MockMediaRecorder {
  state = 'inactive';
  ondataavailable: ((e: any) => void) | null = null;
  onstop: (() => void) | null = null;
  start = vi.fn(() => { this.state = 'recording'; });
  stop = vi.fn(() => { this.state = 'inactive'; this.onstop?.(); });
  requestData = vi.fn();
  static isTypeSupported = vi.fn(() => true);
}
vi.stubGlobal('MediaRecorder', MockMediaRecorder);

// Mock AudioContext
const mockGetByteFrequencyData = vi.fn((arr: Uint8Array) => arr.fill(0));
const mockAnalyser = {
  fftSize: 256,
  smoothingTimeConstant: 0.8,
  frequencyBinCount: 128,
  getByteFrequencyData: mockGetByteFrequencyData,
};
const mockAudioContext = {
  createAnalyser: vi.fn(() => mockAnalyser),
  createMediaStreamSource: vi.fn(() => ({ connect: vi.fn() })),
};
// 用 class 包裝確保 new AudioContext() 可行
class MockAudioContext {
  createAnalyser = vi.fn(() => mockAnalyser);
  createMediaStreamSource = vi.fn(() => ({ connect: vi.fn() }));
  close = vi.fn();
}
vi.stubGlobal('AudioContext', MockAudioContext);

beforeEach(() => {
  useStore.setState({
    status: 'idle',
    vadEnabled: false,
    sessionId: 'test-session',
    cart: [],
    total: 0,
    transcript: '',
    connectionError: null,
    checkoutStep: 0,
    orderResult: null,
  });
  vi.restoreAllMocks();
  mockGetUserMedia.mockResolvedValue({
    getTracks: () => [{ stop: vi.fn() }],
  });
});

describe('VoiceController', () => {
  describe('渲染測試', () => {
    it('應正確渲染 AudioVisualizer 子元件', () => {
      render(<VoiceController />);
      expect(screen.getByTestId('audio-visualizer')).toBeInTheDocument();
    });

    it('idle 狀態下應顯示按鍵說話提示', () => {
      useStore.setState({ vadEnabled: false, status: 'idle' });
      render(<VoiceController />);
      expect(screen.getByText('按住空白鍵或點擊開始說話')).toBeInTheDocument();
    });

    it('VAD 模式下應顯示自動偵測提示', () => {
      useStore.setState({ vadEnabled: true, status: 'idle' });
      render(<VoiceController />);
      expect(screen.getByText('語音自動偵測已啟用，請直接說話')).toBeInTheDocument();
    });
  });

  describe('VAD 模式切換', () => {
    // VAD 切換按鈕位於 page.tsx，VoiceController 不渲染此按鈕

    it('VAD 模式下點擊主區域不應觸發錄音', async () => {
      useStore.setState({ vadEnabled: true, status: 'idle' });
      render(<VoiceController />);

      // 點擊 AudioVisualizer 區域
      await userEvent.click(screen.getByTestId('audio-visualizer'));

      // 狀態應保持 idle（不觸發錄音）
      expect(useStore.getState().status).toBe('idle');
    });
  });

  describe('網路錯誤', () => {
    it('connectionError 有值時元件仍能正常渲染', () => {
      useStore.setState({ connectionError: '網路已斷線' });
      const { container } = render(<VoiceController />);
      expect(container.firstChild).toBeInTheDocument();
    });

    it('connectionError 清除後元件正常', () => {
      useStore.setState({ connectionError: '網路錯誤' });
      render(<VoiceController />);

      // 清除錯誤
      useStore.setState({ connectionError: null });

      // 元件應正常顯示
      expect(screen.getByTestId('audio-visualizer')).toBeInTheDocument();
    });
  });

  describe('狀態顯示', () => {
    it('processing 狀態下不顯示提示文字', () => {
      useStore.setState({ status: 'processing', vadEnabled: false });
      render(<VoiceController />);

      // 不應顯示 idle 狀態的提示文字
      expect(screen.queryByText('按住空白鍵或點擊開始說話')).not.toBeInTheDocument();
      expect(screen.queryByText('語音自動偵測已啟用，請直接說話')).not.toBeInTheDocument();
    });

    it('listening 狀態下不顯示提示文字', () => {
      useStore.setState({ status: 'listening', vadEnabled: false });
      render(<VoiceController />);

      // 不應顯示 idle 狀態的提示文字
      expect(screen.queryByText('按住空白鍵或點擊開始說話')).not.toBeInTheDocument();
      expect(screen.queryByText('語音自動偵測已啟用，請直接說話')).not.toBeInTheDocument();
    });
  });
});
