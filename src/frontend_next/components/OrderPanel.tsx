'use client';

import { useStore } from '../store/useStore';
import OrderTicket from './OrderTicket';
import CheckoutFlow from './CheckoutFlow';

export default function OrderPanel() {
  const { cart, total, checkoutStep, setCheckoutStep } = useStore();
  const hasItems = cart.length > 0;

  if (checkoutStep > 0) {
    return <CheckoutFlow />;
  }

  if (hasItems) {
    return (
      <div className="flex-1 overflow-y-auto p-4">
        <OrderTicket items={cart} total={total} onCheckout={() => setCheckoutStep(1)} />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center p-4">
      <svg className="w-12 h-12 mb-3" viewBox="0 0 24 24" fill="none" stroke="#8a9a9f" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="9" cy="21" r="1" /><circle cx="20" cy="21" r="1" />
        <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6" />
      </svg>
      <p className="text-base" style={{ color: '#8a9a9f' }}>
        購物車是空的
      </p>
      <p className="text-sm mt-1" style={{ color: '#b0bec0' }}>
        語音點餐後品項會出現在這裡
      </p>
    </div>
  );
}
