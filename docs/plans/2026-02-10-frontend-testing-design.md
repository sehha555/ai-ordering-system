# 前端單元測試設計文件

**日期**：2026-02-10
**規畫者**：Opus
**執行者**：Haiku
**狀態**：待執行

---

## 1. 概要

為 `src/frontend_next/` 建立 Vitest + Testing Library 測試環境，以 BDD describe/it 風格撰寫核心元件測試。

### 測試範圍（核心優先）

| 目標 | 檔案 | 行數 | 測試類型 |
|------|------|------|----------|
| Zustand Store | `store/useStore.ts` | 55 | 純邏輯測試 |
| 結帳流程 | `components/CheckoutFlow.tsx` | 409 | 元件測試 + fetch mock |
| 購物車面板 | `components/LiveReceipt.tsx` | 121 | 元件測試 |

### 不在本次範圍

- `VoiceController.tsx` — 大量 Web API（MediaRecorder, AudioContext, SSE），需獨立處理
- `AudioVisualizer.tsx` — Canvas 繪圖，難以斷言
- `MenuDisplay.tsx` — 可在下次加入

---

## 2. 環境設定

### 2.1 安裝依賴

在 `src/frontend_next/` 下執行：

```bash
npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom
```

### 2.2 新增檔案

#### `src/frontend_next/vitest.config.ts`

```typescript
import { defineConfig } from 'vitest/config';
import path from 'path';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./__tests__/setup.ts'],
    include: ['__tests__/**/*.test.{ts,tsx}'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
});
```

#### `src/frontend_next/__tests__/setup.ts`

```typescript
import '@testing-library/jest-dom/vitest';
```

#### `src/frontend_next/package.json` — 新增 script

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

### 2.3 檔案結構

```
src/frontend_next/
├── __tests__/
│   ├── setup.ts
│   ├── store/
│   │   └── useStore.test.ts
│   └── components/
│       ├── CheckoutFlow.test.tsx
│       └── LiveReceipt.test.tsx
├── vitest.config.ts
```

---

## 3. 測試案例

### 3.1 useStore.test.ts — Zustand Store 純邏輯測試

**不需 DOM、不需 mock**，直接呼叫 store action 驗證狀態。

每個測試前用 `useStore.setState()` 重置 store 到初始狀態，避免測試間互相影響。

```typescript
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
```

---

### 3.2 CheckoutFlow.test.tsx — 結帳流程元件測試

**Mock 策略：**
- `global.fetch` — mock `/api/checkout` 回應
- 渲染前用 `useStore.setState()` 設定 store 狀態

**注意事項：**
- Framer Motion 的 AnimatePresence 需要等動畫完成，用 `waitFor` 處理
- 每個步驟用 `useStore.setState({ checkoutStep: N })` 直接跳到該步驟測試

```typescript
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
```

---

### 3.3 LiveReceipt.test.tsx — 購物車面板測試

**Mock 策略：** 只需操作 Zustand store，不需 mock fetch。

```typescript
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LiveReceipt from '../../components/LiveReceipt';
import { useStore } from '../../store/useStore';

beforeEach(() => {
  useStore.setState({
    cart: [],
    total: 0,
    transcript: '',
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
      expect(screen.getByText('$45')).toBeInTheDocument();
      expect(screen.getByText('豆漿')).toBeInTheDocument();
      expect(screen.getByText('$25')).toBeInTheDocument();
    });

    it('商品有 details 時應顯示細節', () => {
      render(<LiveReceipt />);
      expect(screen.getByText('加蛋')).toBeInTheDocument();
      expect(screen.getByText('大杯')).toBeInTheDocument();
    });

    it('數量 > 1 時應顯示 x數量', () => {
      render(<LiveReceipt />);
      expect(screen.getByText('x2')).toBeInTheDocument();
      // quantity=1 不顯示
      expect(screen.queryByText('x1')).not.toBeInTheDocument();
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

  describe('語音識別結果', () => {
    it('有 transcript 時應顯示「你說的是：」區塊', () => {
      useStore.setState({ transcript: '我要一個飯糰' });
      render(<LiveReceipt />);
      expect(screen.getByText('你說的是：')).toBeInTheDocument();
      expect(screen.getByText('我要一個飯糰')).toBeInTheDocument();
    });

    it('無 transcript 時不應顯示該區塊', () => {
      render(<LiveReceipt />);
      expect(screen.queryByText('你說的是：')).not.toBeInTheDocument();
    });
  });
});
```

---

## 4. 執行指令

```bash
cd src/frontend_next
npm run test          # 單次執行
npm run test:watch    # 開發時 watch 模式
```

## 5. 預期結果

| 測試檔 | 測試案例數 |
|--------|-----------|
| useStore.test.ts | 9 |
| CheckoutFlow.test.tsx | 13 |
| LiveReceipt.test.tsx | 10 |
| **合計** | **32** |
