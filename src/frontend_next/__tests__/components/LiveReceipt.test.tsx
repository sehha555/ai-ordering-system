import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LiveReceipt from '../../components/LiveReceipt';
import { useStore } from '../../store/useStore';

beforeEach(() => {
  useStore.setState({
    cart: [],
    total: 0,
    checkoutStep: 0,
  });
});

describe('LiveReceipt', () => {
  describe('當購物車為空時', () => {
    it('應顯示「購物車是空的」', () => {
      render(<LiveReceipt />);
      expect(screen.getByText('購物車是空的')).toBeInTheDocument();
    });

    it('不應顯示總計和結帳按鈕', () => {
      render(<LiveReceipt />);
      expect(screen.queryByText('總計')).not.toBeInTheDocument();
      expect(screen.queryByText('結帳')).not.toBeInTheDocument();
    });

    it('不應顯示商品數量 badge', () => {
      render(<LiveReceipt />);
      expect(screen.queryByText(/項/)).not.toBeInTheDocument();
    });
  });

  describe('當購物車有商品時', () => {
    const items = [
      { name: '飯糰（加蛋）', details: '加蛋', price: 45, quantity: 1 },
      { name: '豆漿', details: '大杯', price: 25, quantity: 2 },
    ];

    beforeEach(() => {
      useStore.setState({ cart: items, total: 95 });
    });

    it('應顯示每個商品的名稱和價格', () => {
      render(<LiveReceipt />);
      expect(screen.getByText('飯糰（加蛋）')).toBeInTheDocument();
      expect(screen.getByText('1 × $45')).toBeInTheDocument();
      expect(screen.getByText('豆漿')).toBeInTheDocument();
      expect(screen.getByText('2 × $25')).toBeInTheDocument();
    });

    it('商品有 details 時應顯示細節', () => {
      render(<LiveReceipt />);
      expect(screen.getByText('加蛋')).toBeInTheDocument();
      expect(screen.getByText('大杯')).toBeInTheDocument();
    });

    it('應顯示商品數量 badge', () => {
      render(<LiveReceipt />);
      expect(screen.getByText('2 項')).toBeInTheDocument();
    });

    it('應顯示總計金額', () => {
      render(<LiveReceipt />);
      expect(screen.getByText('$95')).toBeInTheDocument();
    });

    it('應顯示結帳按鈕', () => {
      render(<LiveReceipt />);
      expect(screen.getByText('結帳')).toBeInTheDocument();
    });

    it('點擊結帳應將 checkoutStep 設為 1', async () => {
      render(<LiveReceipt />);
      await userEvent.click(screen.getByText('結帳'));
      expect(useStore.getState().checkoutStep).toBe(1);
    });
  });

});
