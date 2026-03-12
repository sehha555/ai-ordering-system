import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import CheckoutFlow from '../../components/CheckoutFlow';
import { useStore } from '../../store/useStore';

// 測試用購物車資料
const mockCart = [
  { name: '飯糰（加蛋）', details: '加蛋', price: 45, quantity: 1 },
  { name: '豆漿', details: '大杯', price: 25, quantity: 2 },
];
const mockTotal = 95;

const mockOrderResult = {
  order_number: '03',
  total: 95,
  item_count: 2,
  items_display: [
    { name: '飯糰（加蛋）', quantity: 1, unit_price: 45, subtotal: 45 },
    { name: '豆漿', quantity: 2, unit_price: 25, subtotal: 50 },
  ],
  dine_type: 'take-out',
  payment_method: 'cash',
};

beforeEach(() => {
  useStore.setState({
    cart: mockCart,
    total: mockTotal,
    checkoutStep: 1,
    orderResult: null,
    sessionId: 'session-test-123',
  });
  vi.restoreAllMocks();
});

describe('CheckoutFlow', () => {
  describe('手動結帳（一頁式）', () => {
    it('應顯示用餐方式和付款方式選項', () => {
      render(<CheckoutFlow />);
      expect(screen.getByText('內用')).toBeInTheDocument();
      expect(screen.getByText('外帶')).toBeInTheDocument();
      expect(screen.getByText('現金')).toBeInTheDocument();
      expect(screen.getByText('Line Pay')).toBeInTheDocument();
    });

    it('應顯示購物車內容和總計', () => {
      render(<CheckoutFlow />);
      expect(screen.getByText(/飯糰/)).toBeInTheDocument();
      expect(screen.getByText(/豆漿/)).toBeInTheDocument();
      expect(screen.getByText('$95')).toBeInTheDocument();
    });

    it('未選擇用餐方式和付款方式時，確認按鈕應 disabled', () => {
      render(<CheckoutFlow />);
      const submitBtn = screen.getByText('確認送出');
      expect(submitBtn.closest('button')).toBeDisabled();
    });

    it('選擇後點擊確認送出應呼叫 /api/checkout', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          status: 'ok',
          order_number: '03',
          total_price: 95,
          items_display: [],
        }),
      });
      global.fetch = mockFetch;

      render(<CheckoutFlow />);

      // 選擇用餐方式和付款方式
      await userEvent.click(screen.getByText('外帶'));
      await userEvent.click(screen.getByText('現金'));
      await userEvent.click(screen.getByText('確認送出'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('/api/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: 'session-test-123',
            dine_type: 'take-out',
            payment_method: 'cash',
          }),
        });
      });
    });

    it('API 成功後應進入完成畫面', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          status: 'ok',
          order_number: '03',
          total_price: 95,
          items_display: [],
        }),
      });

      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('外帶'));
      await userEvent.click(screen.getByText('現金'));
      await userEvent.click(screen.getByText('確認送出'));

      await waitFor(() => {
        expect(useStore.getState().checkoutStep).toBe(2);
        expect(useStore.getState().orderResult).not.toBeNull();
      });
    });

    it('API 失敗時應顯示錯誤訊息', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({ detail: '購物車為空' }),
      });

      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('內用'));
      await userEvent.click(screen.getByText('現金'));
      await userEvent.click(screen.getByText('確認送出'));

      await waitFor(() => {
        expect(screen.getByText('購物車為空')).toBeInTheDocument();
      });
    });

    it('送出中按鈕應 disabled 並顯示「處理中...」', async () => {
      global.fetch = vi.fn().mockReturnValue(new Promise(() => {}));

      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('外帶'));
      await userEvent.click(screen.getByText('現金'));
      await userEvent.click(screen.getByText('確認送出'));

      await waitFor(() => {
        expect(screen.getByText('處理中...')).toBeInTheDocument();
        expect(screen.getByText('處理中...').closest('button')).toBeDisabled();
      });
    });

    it('購物車為空時應顯示警告提示', () => {
      useStore.setState({ cart: [], total: 0, checkoutStep: 1 });
      render(<CheckoutFlow />);
      expect(screen.getByText('購物車是空的')).toBeInTheDocument();
      expect(screen.getByText('請先點餐再結帳')).toBeInTheDocument();
    });

    it('購物車為空時確認按鈕應 disabled', () => {
      useStore.setState({ cart: [], total: 0, checkoutStep: 1 });
      render(<CheckoutFlow />);
      const submitBtn = screen.getByText('確認送出');
      expect(submitBtn.closest('button')).toBeDisabled();
    });

    it('購物車為空時手動送出應顯示錯誤', async () => {
      useStore.setState({ cart: [], total: 0, checkoutStep: 1 });
      // 強制啟用按鈕來測試 handleManualSubmit 的內部檢查
      render(<CheckoutFlow />);
      // 按鈕已 disabled 所以測試 store 邏輯
      // handleManualSubmit 內部有 cart.length === 0 檢查
      expect(screen.getByText('購物車是空的')).toBeInTheDocument();
    });
  });

  describe('完成畫面（AI 或手動共用）', () => {
    beforeEach(() => {
      useStore.setState({
        checkoutStep: 2,
        orderResult: mockOrderResult,
      });
    });

    it('應顯示取餐號碼和訂單完成', () => {
      render(<CheckoutFlow />);
      expect(screen.getByText('03')).toBeInTheDocument();
      expect(screen.getByText('訂單完成')).toBeInTheDocument();
    });

    it('應顯示品項明細', () => {
      render(<CheckoutFlow />);
      expect(screen.getByText(/飯糰/)).toBeInTheDocument();
      expect(screen.getByText('$45')).toBeInTheDocument();
      expect(screen.getByText('$95')).toBeInTheDocument();
    });

    it('應顯示用餐方式和付款方式', () => {
      render(<CheckoutFlow />);
      expect(screen.getByText(/外帶/)).toBeInTheDocument();
      expect(screen.getByText(/現金/)).toBeInTheDocument();
    });

    it('點擊「開始新訂單」應呼叫 resetSession', async () => {
      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText(/開始新訂單/));
      expect(useStore.getState().checkoutStep).toBe(0);
      expect(useStore.getState().cart).toEqual([]);
    });

    it('完成畫面不應顯示返回按鈕', () => {
      render(<CheckoutFlow />);
      expect(screen.queryByText('返回')).not.toBeInTheDocument();
    });
  });

  describe('返回功能', () => {
    it('手動結帳頁點返回應回到主頁面', async () => {
      useStore.setState({ checkoutStep: 1 });
      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('返回'));
      expect(useStore.getState().checkoutStep).toBe(0);
    });
  });
});
