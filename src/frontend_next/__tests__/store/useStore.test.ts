import { useStore } from '../../store/useStore';

// 每個測試前重置 store
beforeEach(() => {
  useStore.setState({
    status: 'idle',
    cart: [],
    total: 0,
    transcript: '',
    checkoutStep: 0,
    orderResult: null,
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

    it('應生成 UUID v4 格式的 sessionId', () => {
      const state = useStore.getState();
      expect(state.sessionId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
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
      useStore.getState().setCheckoutStep(1);
      expect(useStore.getState().checkoutStep).toBe(1);
    });

    it('setOrderResult 應設定訂單結果並自動跳到 step 2', () => {
      const mockResult = {
        order_number: '03',
        total: 150,
        item_count: 3,
        items_display: [
          { name: '紫米傳統加辣', quantity: 1, unit_price: 45, subtotal: 45 },
        ],
        dine_type: 'take-out',
        payment_method: 'cash',
      };
      useStore.getState().setOrderResult(mockResult);

      const state = useStore.getState();
      expect(state.orderResult).toEqual(mockResult);
      expect(state.checkoutStep).toBe(2);
    });

    it('resetCheckout 應重置結帳狀態但保留購物車', () => {
      const items = [{ name: '飯糰', details: '', price: 45, quantity: 1 }];
      useStore.getState().setCart(items, 45);
      useStore.getState().setOrderResult({
        order_number: '01',
        total: 45,
        item_count: 1,
        items_display: [],
        dine_type: 'dine-in',
        payment_method: 'cash',
      });

      useStore.getState().resetCheckout();

      const state = useStore.getState();
      expect(state.checkoutStep).toBe(0);
      expect(state.orderResult).toBeNull();
      // 購物車應保留
      expect(state.cart).toEqual(items);
      expect(state.total).toBe(45);
    });
  });

  describe('當新增訊息時', () => {
    it('addMessage assistant 應清掉 streamingText（即使內容不同）', () => {
      useStore.setState({ messages: [], streamingText: '好的，飯糰' });
      useStore.getState().addMessage('assistant', '好的，飯糰要白米紫米？');

      const state = useStore.getState();
      expect(state.messages).toHaveLength(1);
      expect(state.streamingText).toBe('');
    });

    it('addMessage user 不影響 streamingText', () => {
      useStore.setState({ messages: [], streamingText: '處理中' });
      useStore.getState().addMessage('user', '我要一個飯糰');

      expect(useStore.getState().streamingText).toBe('處理中');
    });
  });

  describe('當重置會話時', () => {
    it('resetSession 應重置全部狀態並生成新 sessionId', () => {
      const oldSessionId = useStore.getState().sessionId;

      useStore.getState().setCart(
        [{ name: '飯糰', details: '', price: 45, quantity: 1 }],
        45
      );
      useStore.getState().setCheckoutStep(1);
      useStore.getState().resetSession();

      const state = useStore.getState();
      expect(state.cart).toEqual([]);
      expect(state.total).toBe(0);
      expect(state.checkoutStep).toBe(0);
      expect(state.orderResult).toBeNull();
      expect(state.status).toBe('idle');
      expect(state.sessionId).not.toBe(oldSessionId);
    });
  });
});
