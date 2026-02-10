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

beforeEach(() => {
  useStore.setState({
    cart: mockCart,
    total: mockTotal,
    checkoutStep: 1,
    dineType: null,
    paymentMethod: null,
    orderNumber: null,
    sessionId: 'session-test-123',
  });
  vi.restoreAllMocks();
});

describe('CheckoutFlow', () => {
  describe('步驟 1：用餐方式選擇', () => {
    it('應顯示「內用」和「外帶」兩個按鈕', () => {
      render(<CheckoutFlow />);
      expect(screen.getByText('內用')).toBeInTheDocument();
      expect(screen.getByText('外帶')).toBeInTheDocument();
    });

    it('點擊「內用」後應進入步驟 2', async () => {
      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('內用'));
      expect(useStore.getState().dineType).toBe('dine-in');
      expect(useStore.getState().checkoutStep).toBe(2);
    });

    it('點擊「外帶」後應進入步驟 2', async () => {
      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('外帶'));
      expect(useStore.getState().dineType).toBe('take-out');
      expect(useStore.getState().checkoutStep).toBe(2);
    });
  });

  describe('步驟 2：付款方式選擇', () => {
    beforeEach(() => {
      useStore.setState({ checkoutStep: 2, dineType: 'dine-in' });
    });

    it('應顯示「現金」和「行動支付」兩個按鈕', () => {
      render(<CheckoutFlow />);
      expect(screen.getByText('現金')).toBeInTheDocument();
      expect(screen.getByText('行動支付')).toBeInTheDocument();
    });

    it('點擊「現金」後應進入步驟 3', async () => {
      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('現金'));
      expect(useStore.getState().paymentMethod).toBe('cash');
      expect(useStore.getState().checkoutStep).toBe(3);
    });
  });

  describe('步驟 3：確認訂單', () => {
    beforeEach(() => {
      useStore.setState({
        checkoutStep: 3,
        dineType: 'dine-in',
        paymentMethod: 'cash',
      });
    });

    it('應顯示購物車內容和總計', () => {
      render(<CheckoutFlow />);
      expect(screen.getByText(/飯糰/)).toBeInTheDocument();
      expect(screen.getByText(/豆漿/)).toBeInTheDocument();
      expect(screen.getByText('$95')).toBeInTheDocument();
    });

    it('應顯示已選的用餐方式和付款方式', () => {
      render(<CheckoutFlow />);
      expect(screen.getByText('內用')).toBeInTheDocument();
      expect(screen.getByText('現金')).toBeInTheDocument();
    });

    it('點擊確認送出應呼叫 /api/checkout', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ status: 'ok', order_number: 'A001' }),
      });
      global.fetch = mockFetch;

      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('確認送出'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('/api/checkout', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: 'session-test-123',
            dine_type: 'dine-in',
            payment_method: 'cash',
          }),
        });
      });
    });

    it('API 成功後應進入步驟 4 並顯示取餐號碼', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ status: 'ok', order_number: 'A001' }),
      });

      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('確認送出'));

      await waitFor(() => {
        expect(useStore.getState().checkoutStep).toBe(4);
        expect(useStore.getState().orderNumber).toBe('A001');
      });
    });

    it('API 失敗時應顯示錯誤訊息', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        json: () => Promise.resolve({ detail: '購物車為空' }),
      });

      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('確認送出'));

      await waitFor(() => {
        expect(screen.getByText('購物車為空')).toBeInTheDocument();
      });
    });

    it('送出中按鈕應 disabled 並顯示「處理中...」', async () => {
      // fetch 永不 resolve，模擬等待中
      global.fetch = vi.fn().mockReturnValue(new Promise(() => {}));

      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('確認送出'));

      await waitFor(() => {
        expect(screen.getByText('處理中...')).toBeInTheDocument();
        expect(screen.getByText('處理中...').closest('button')).toBeDisabled();
      });
    });
  });

  describe('步驟 4：訂單完成', () => {
    beforeEach(() => {
      useStore.setState({ checkoutStep: 4, orderNumber: 'A001' });
    });

    it('應顯示取餐號碼', () => {
      render(<CheckoutFlow />);
      expect(screen.getByText('A001')).toBeInTheDocument();
      expect(screen.getByText('訂單完成')).toBeInTheDocument();
    });

    it('點擊「開始新訂單」應呼叫 resetSession', async () => {
      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('開始新訂單'));
      expect(useStore.getState().checkoutStep).toBe(0);
      expect(useStore.getState().cart).toEqual([]);
    });
  });

  describe('返回功能', () => {
    it('步驟 2 點返回應回到步驟 1', async () => {
      useStore.setState({ checkoutStep: 2 });
      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('返回'));
      expect(useStore.getState().checkoutStep).toBe(1);
    });

    it('步驟 3 點返回應回到步驟 2', async () => {
      useStore.setState({ checkoutStep: 3, dineType: 'dine-in', paymentMethod: 'cash' });
      render(<CheckoutFlow />);
      await userEvent.click(screen.getByText('返回'));
      expect(useStore.getState().checkoutStep).toBe(2);
    });

    it('步驟 4 不應顯示返回按鈕', () => {
      useStore.setState({ checkoutStep: 4, orderNumber: 'A001' });
      render(<CheckoutFlow />);
      expect(screen.queryByText('返回')).not.toBeInTheDocument();
    });
  });
});
