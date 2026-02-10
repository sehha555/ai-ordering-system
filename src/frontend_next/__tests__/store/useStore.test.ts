import { useStore } from '../../store/useStore';

// 每個測試前重置 store
beforeEach(() => {
  useStore.setState({
    status: 'idle',
    cart: [],
    total: 0,
    transcript: '',
    checkoutStep: 0,
    dineType: null,
    paymentMethod: null,
    orderNumber: null,
    vadEnabled: true,
  });
});

describe('useStore', () => {
  describe('初始狀態', () => {
    it('應有空購物車和 idle 狀態', () => {
      const state = useStore.getState();
      expect(state.status).toBe('idle');
      expect(state.cart).toEqual([]);
      expect(state.total).toBe(0);
    });

    it('應生成 session-xxx 格式的 sessionId', () => {
      const state = useStore.getState();
      expect(state.sessionId).toMatch(/^session-\d+$/);
    });

    it('checkoutStep 應為 0', () => {
      const state = useStore.getState();
      expect(state.checkoutStep).toBe(0);
    });
  });

  describe('當設定購物車時', () => {
    it('setCart 應更新 cart 和 total', () => {
      const items = [
        { name: '飯糰', details: '加蛋', price: 45, quantity: 1 },
        { name: '豆漿', details: '', price: 20, quantity: 2 },
      ];
      useStore.getState().setCart(items, 85);

      const state = useStore.getState();
      expect(state.cart).toEqual(items);
      expect(state.total).toBe(85);
    });

    it('clearCart 應清空 cart 並歸零 total', () => {
      useStore.getState().setCart(
        [{ name: '飯糰', details: '', price: 45, quantity: 1 }],
        45
      );
      useStore.getState().clearCart();

      const state = useStore.getState();
      expect(state.cart).toEqual([]);
      expect(state.total).toBe(0);
    });
  });

  describe('當進行結帳流程時', () => {
    it('setCheckoutStep 應更新步驟', () => {
      useStore.getState().setCheckoutStep(2);
      expect(useStore.getState().checkoutStep).toBe(2);
    });

    it('setDineType 應設定用餐方式', () => {
      useStore.getState().setDineType('dine-in');
      expect(useStore.getState().dineType).toBe('dine-in');
    });

    it('setPaymentMethod 應設定付款方式', () => {
      useStore.getState().setPaymentMethod('cash');
      expect(useStore.getState().paymentMethod).toBe('cash');
    });

    it('resetCheckout 應重置所有結帳狀態但保留購物車', () => {
      const items = [{ name: '飯糰', details: '', price: 45, quantity: 1 }];
      useStore.getState().setCart(items, 45);
      useStore.getState().setCheckoutStep(3);
      useStore.getState().setDineType('dine-in');
      useStore.getState().setPaymentMethod('cash');

      useStore.getState().resetCheckout();

      const state = useStore.getState();
      expect(state.checkoutStep).toBe(0);
      expect(state.dineType).toBeNull();
      expect(state.paymentMethod).toBeNull();
      expect(state.orderNumber).toBeNull();
      // 購物車應保留
      expect(state.cart).toEqual(items);
      expect(state.total).toBe(45);
    });
  });

  describe('當重置會話時', () => {
    it('resetSession 應重置全部狀態並生成新 sessionId', () => {
      const oldSessionId = useStore.getState().sessionId;

      useStore.getState().setCart(
        [{ name: '飯糰', details: '', price: 45, quantity: 1 }],
        45
      );
      useStore.getState().setCheckoutStep(3);
      useStore.getState().resetSession();

      const state = useStore.getState();
      expect(state.cart).toEqual([]);
      expect(state.total).toBe(0);
      expect(state.checkoutStep).toBe(0);
      expect(state.status).toBe('idle');
      expect(state.sessionId).not.toBe(oldSessionId);
    });
  });
});
