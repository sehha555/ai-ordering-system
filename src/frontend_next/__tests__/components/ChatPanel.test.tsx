import { render, screen } from '@testing-library/react';
import ChatPanel from '../../components/ChatPanel';
import { useStore } from '../../store/useStore';

Element.prototype.scrollIntoView = vi.fn();

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => (
      <div {...(props as React.HTMLAttributes<HTMLDivElement>)}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: React.PropsWithChildren) => <>{children}</>,
}));

vi.mock('../../hooks/useTypewriter', () => ({
  useTypewriter: (text: string) => text,
}));

vi.mock('../../../config/store_config.json', () => ({
  default: {
    store: { name: '源飯糰' },
    messages: {
      welcome_title: '歡迎光臨源飯糰',
      welcome_subtitle: '按空白鍵或點擊球體開始點餐',
    },
  },
}));

beforeEach(() => {
  useStore.setState({
    messages: [],
    streamingText: '',
  });
});

describe('ChatPanel', () => {
  it('沒有訊息時顯示歡迎畫面', () => {
    render(<ChatPanel />);
    expect(screen.getByText('歡迎光臨源飯糰')).toBeInTheDocument();
    expect(screen.getByText('按空白鍵或點擊球體開始點餐')).toBeInTheDocument();
  });

  it('有訊息時不顯示歡迎畫面', () => {
    useStore.setState({
      messages: [
        { id: '1', role: 'user' as const, content: '我要一個飯糰', timestamp: Date.now() },
      ],
    });
    render(<ChatPanel />);
    expect(screen.queryByText('歡迎光臨源飯糰')).not.toBeInTheDocument();
  });

  it('顯示 user 和 assistant 訊息', () => {
    useStore.setState({
      messages: [
        { id: '1', role: 'user' as const, content: '我要一個飯糰', timestamp: Date.now() },
        { id: '2', role: 'assistant' as const, content: '好的，飯糰要白米紫米？', timestamp: Date.now() },
      ],
    });
    render(<ChatPanel />);
    expect(screen.getByText('我要一個飯糰')).toBeInTheDocument();
    expect(screen.getByText('好的，飯糰要白米紫米？')).toBeInTheDocument();
  });

  it('streamingText 存在時顯示串流氣泡', () => {
    useStore.setState({
      messages: [
        { id: '1', role: 'user' as const, content: '我要一個飯糰', timestamp: Date.now() },
      ],
      streamingText: '好的，飯糰',
    });
    render(<ChatPanel />);
    expect(screen.getByText('好的，飯糰')).toBeInTheDocument();
  });

  it('streamingText 為空時不顯示串流氣泡', () => {
    useStore.setState({
      messages: [
        { id: '1', role: 'user' as const, content: '你好', timestamp: Date.now() },
        { id: '2', role: 'assistant' as const, content: '歡迎光臨', timestamp: Date.now() },
      ],
      streamingText: '',
    });
    render(<ChatPanel />);
    const bubbles = screen.getAllByText(/.+/);
    const streamingCursors = document.querySelectorAll('.animate-pulse');
    expect(streamingCursors).toHaveLength(0);
  });
});
