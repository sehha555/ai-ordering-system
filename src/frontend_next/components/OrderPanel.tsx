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
      <p className="text-4xl mb-3">🛒</p>
      <p className="text-base" style={{ color: '#8a9a9f' }}>
        購物車是空的
      </p>
      <p className="text-sm mt-1" style={{ color: '#b0bec0' }}>
        語音點餐後品項會出現在這裡
      </p>
    </div>
  );
}
