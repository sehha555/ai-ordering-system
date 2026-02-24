import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';
import MenuDisplay from '../../components/MenuDisplay';
import type { MenuCategory } from '../../types';

// 測試用假菜單資料
const mockCategories: MenuCategory[] = [
  {
    name: '主食',
    icon: '🍔',
    items: [
      { name: '漢堡', price: 80 },
      { name: '薯條', price: 40 },
    ],
  },
  {
    name: '飲料',
    icon: '🧃',
    items: [
      { name: '可樂', price: 30 },
      { name: '柳橙汁', price: 35 },
    ],
  },
];

// 建立成功的 fetch mock（回傳菜單）
function mockFetchSuccess(categories: MenuCategory[] = mockCategories) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ categories }),
    })
  );
}

// 建立 fetch 失敗的 mock
function mockFetchError() {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockRejectedValue(new Error('Network error'))
  );
}

// 建立回傳空菜單的 fetch mock
function mockFetchEmpty() {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ categories: [] }),
    })
  );
}

beforeEach(() => {
  mockFetchSuccess();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('MenuDisplay', () => {
  describe('Loading 狀態', () => {
    it('初始化時應顯示載入文字', () => {
      // fetch 還未 resolve，此時應顯示 loading
      render(<MenuDisplay />);
      expect(screen.getByText('載入菜單中...')).toBeInTheDocument();
    });
  });

  describe('菜單渲染', () => {
    it('菜單載入後應顯示所有分類名稱', async () => {
      render(<MenuDisplay />);
      await waitFor(() => {
        expect(screen.getByText('主食')).toBeInTheDocument();
        expect(screen.getByText('飲料')).toBeInTheDocument();
      });
    });

    it('菜單載入後應顯示分類 icon', async () => {
      render(<MenuDisplay />);
      await waitFor(() => {
        expect(screen.getByText('🍔')).toBeInTheDocument();
        expect(screen.getByText('🧃')).toBeInTheDocument();
      });
    });

    it('菜單載入後應顯示每個分類的品項數量', async () => {
      render(<MenuDisplay />);
      await waitFor(() => {
        // 主食有 2 個品項，飲料有 2 個品項
        const badges = screen.getAllByText('2');
        expect(badges.length).toBeGreaterThanOrEqual(2);
      });
    });

    it('第一個分類預設為展開狀態', async () => {
      render(<MenuDisplay />);
      await waitFor(() => {
        // 第一個分類（主食）展開，應顯示品項
        expect(screen.getByText('漢堡')).toBeInTheDocument();
        expect(screen.getByText('薯條')).toBeInTheDocument();
      });
    });

    it('其他分類預設為收合狀態', async () => {
      render(<MenuDisplay />);
      await waitFor(() => {
        // 第一個分類展開後，第二個分類（飲料）應為收合，品項不可見
        expect(screen.queryByText('可樂')).not.toBeInTheDocument();
        expect(screen.queryByText('柳橙汁')).not.toBeInTheDocument();
      });
    });
  });

  describe('展開/收合互動', () => {
    it('點擊收合的分類應展開並顯示品項', async () => {
      const user = userEvent.setup();
      render(<MenuDisplay />);

      // 等待菜單載入
      await waitFor(() => expect(screen.getByText('飲料')).toBeInTheDocument());

      // 點擊第二個分類（飲料）
      await act(async () => {
        await user.click(screen.getByText('飲料'));
      });

      // 飲料品項應出現
      await waitFor(() => {
        expect(screen.getByText('可樂')).toBeInTheDocument();
        expect(screen.getByText('柳橙汁')).toBeInTheDocument();
      });
    });

    it('點擊已展開的分類應收合', async () => {
      const user = userEvent.setup();
      render(<MenuDisplay />);

      // 等待菜單載入，第一個分類（主食）預設展開
      await waitFor(() => expect(screen.getByText('漢堡')).toBeInTheDocument());

      // 點擊主食收合
      await act(async () => {
        await user.click(screen.getByText('主食'));
      });

      // 主食品項應消失
      await waitFor(() => {
        expect(screen.queryByText('漢堡')).not.toBeInTheDocument();
      });
    });

    it('展開後品項應顯示名稱和價格', async () => {
      const user = userEvent.setup();
      render(<MenuDisplay />);

      // 等待菜單載入（主食已展開）
      await waitFor(() => expect(screen.getByText('漢堡')).toBeInTheDocument());

      // 驗證價格顯示
      expect(screen.getByText('$80')).toBeInTheDocument();
      expect(screen.getByText('$40')).toBeInTheDocument();
    });
  });

  describe('錯誤與備援', () => {
    it('fetch 失敗時應顯示圖片備援', async () => {
      mockFetchError();
      render(<MenuDisplay />);

      await waitFor(() => {
        const img = screen.getByRole('img', { name: '菜單' });
        expect(img).toBeInTheDocument();
        expect(img).toHaveAttribute('src', '/static/menu.png');
      });
    });

    it('菜單為空時應顯示圖片備援', async () => {
      mockFetchEmpty();
      render(<MenuDisplay />);

      await waitFor(() => {
        const img = screen.getByRole('img', { name: '菜單' });
        expect(img).toBeInTheDocument();
      });
    });

    it('點擊「圖片模式」按鈕應切換至圖片顯示', async () => {
      const user = userEvent.setup();
      render(<MenuDisplay />);

      // 等待菜單載入
      await waitFor(() => expect(screen.getByText('圖片模式')).toBeInTheDocument());

      // 點擊圖片模式按鈕
      await act(async () => {
        await user.click(screen.getByText('圖片模式'));
      });

      // 應切換到圖片模式
      await waitFor(() => {
        const img = screen.getByRole('img', { name: '菜單' });
        expect(img).toBeInTheDocument();
      });
    });
  });
});
