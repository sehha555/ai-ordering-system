import { render, screen } from '@testing-library/react';
import OrderPanel from '../../components/OrderPanel';
import { useStore } from '../../store/useStore';

vi.mock('../../components/OrderTicket', () => ({
  default: ({ items, total, onCheckout }: { items: unknown[]; total: number; onCheckout: () => void }) => (
    <div data-testid="order-ticket">
      <span>total:{total}</span>
      <span>items:{items.length}</span>
      <button onClick={onCheckout}>結帳</button>
    </div>
  ),
}));

vi.mock('../../components/CheckoutFlow', () => ({
  default: () => <div data-testid="checkout-flow">CheckoutFlow</div>,
}));

beforeEach(() => {
  useStore.setState({
    cart: [],
    total: 0,
    checkoutStep: 0,
  });
});

describe('OrderPanel', () => {
  it('購物車空時顯示空狀態文字', () => {
    render(<OrderPanel />);
    expect(screen.getByText('購物車是空的')).toBeInTheDocument();
    expect(screen.queryByTestId('order-ticket')).not.toBeInTheDocument();
  });

  it('有品項時顯示 OrderTicket', () => {
    useStore.setState({
      cart: [{ name: '薯餅', details: '', price: 15, quantity: 1 }],
      total: 15,
    });
    render(<OrderPanel />);
    expect(screen.getByTestId('order-ticket')).toBeInTheDocument();
    expect(screen.getByText('total:15')).toBeInTheDocument();
    expect(screen.queryByText('購物車是空的')).not.toBeInTheDocument();
  });

  it('checkoutStep > 0 時顯示 CheckoutFlow', () => {
    useStore.setState({
      cart: [{ name: '薯餅', details: '', price: 15, quantity: 1 }],
      total: 15,
      checkoutStep: 1,
    });
    render(<OrderPanel />);
    expect(screen.getByTestId('checkout-flow')).toBeInTheDocument();
    expect(screen.queryByTestId('order-ticket')).not.toBeInTheDocument();
  });

  it('點擊結帳按鈕將 checkoutStep 設為 1', async () => {
    const { default: userEvent } = await import('@testing-library/user-event');
    useStore.setState({
      cart: [{ name: '薯餅', details: '', price: 15, quantity: 1 }],
      total: 15,
    });
    render(<OrderPanel />);
    await userEvent.click(screen.getByText('結帳'));
    expect(useStore.getState().checkoutStep).toBe(1);
  });
});
