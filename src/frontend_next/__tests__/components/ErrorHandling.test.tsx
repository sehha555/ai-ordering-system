import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Toast from '../../components/Toast';
import { useStore } from '../../store/useStore';

beforeEach(() => {
  vi.useFakeTimers();
  useStore.setState({ connectionError: null });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('Toast', () => {
  it('connectionError 為 null 時不顯示', () => {
    render(<Toast />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('connectionError 有值時顯示錯誤訊息', () => {
    useStore.setState({ connectionError: 'SSE 連線中斷' });
    render(<Toast />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByText(/SSE 連線中斷/)).toBeInTheDocument();
  });

  it('5 秒後自動消失', () => {
    useStore.setState({ connectionError: '回應超時' });
    render(<Toast />);
    expect(screen.getByRole('alert')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(5000);
    });

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(useStore.getState().connectionError).toBeNull();
  });

  it('5 秒前不會消失', () => {
    useStore.setState({ connectionError: '回應超時' });
    render(<Toast />);

    act(() => {
      vi.advanceTimersByTime(4999);
    });

    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('點擊關閉按鈕立即消失', async () => {
    vi.useRealTimers();
    useStore.setState({ connectionError: '伺服器錯誤' });
    render(<Toast />);
    expect(screen.getByRole('alert')).toBeInTheDocument();

    await userEvent.click(screen.getByLabelText('關閉通知'));

    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(useStore.getState().connectionError).toBeNull();
  });

  it('錯誤更新時重置計時器', () => {
    useStore.setState({ connectionError: '第一個錯誤' });
    const { rerender } = render(<Toast />);

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole('alert')).toBeInTheDocument();

    act(() => {
      useStore.setState({ connectionError: '第二個錯誤' });
    });
    rerender(<Toast />);

    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByRole('alert')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
