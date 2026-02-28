'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { ShoppingBag, Bell, ChevronDown, ChevronUp } from 'lucide-react';

// ───────────────────────────── 型別 ─────────────────────────────

interface OrderItem {
  name: string;
  price: number;
  quantity: number;
  details?: string;
}

interface Order {
  order_id: string;
  order_number: string;
  status: 'SUBMITTED' | 'IN_PROGRESS' | 'COMPLETED';
  payment_status: 'UNPAID' | 'PAID';
  items: OrderItem[];
  total_price: number;
  dine_type: string;
  created_at: string;
}

type TabType = 'ACTIVE' | 'COMPLETED';

// ───────────────────────────── 常數 ─────────────────────────────

// 煎台分類（以品名結尾判斷）
const GRIDDLE_CATEGORIES = ['蛋餅', '吐司', '漢堡', '蔥抓餅', '鐵板麵'];
// 饅頭含蛋 → 煎台
const GRIDDLE_MANTOU_KEYWORDS = ['夾蛋', '蛋饅頭'];

function isGriddle(itemName: string): boolean {
  if (GRIDDLE_CATEGORIES.some((cat) => itemName.includes(cat))) return true;
  if (itemName.includes('饅頭') && GRIDDLE_MANTOU_KEYWORDS.some((kw) => itemName.includes(kw))) return true;
  return false;
}

function classifyItems(items: OrderItem[]) {
  const griddle: OrderItem[] = [];
  const nonGriddle: OrderItem[] = [];
  for (const item of items) {
    if (isGriddle(item.name)) griddle.push(item);
    else nonGriddle.push(item);
  }
  return { griddle, nonGriddle };
}

function isComplex(items: OrderItem[]): boolean {
  const total = items.reduce((sum, i) => sum + i.quantity, 0);
  if (total > 2) return true;
  const { griddle, nonGriddle } = classifyItems(items);
  return griddle.length > 0 && nonGriddle.length > 0;
}

function formatTime(isoStr: string): string {
  const d = new Date(isoStr);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function summarizeItems(items: OrderItem[]): string {
  return items.map((i) => `${i.name}${i.quantity > 1 ? ` ×${i.quantity}` : ''}`).join('　');
}

// ───────────────────────────── 子元件 ─────────────────────────────

function PaymentPill({ status, onToggle }: { status: 'UNPAID' | 'PAID'; onToggle: () => void }) {
  const isPaid = status === 'PAID';
  return (
    <button
      onClick={(e) => { e.stopPropagation(); onToggle(); }}
      className="text-xs font-semibold px-2.5 py-1 rounded-full transition-colors"
      style={{
        backgroundColor: isPaid ? '#dcf0e4' : '#fde8e8',
        color: isPaid ? '#4a9d68' : '#c45c5c',
      }}
    >
      {isPaid ? '● 已付款' : '● 待收款'}
    </button>
  );
}

function StationSummary({ items }: { items: OrderItem[] }) {
  const { griddle, nonGriddle } = classifyItems(items);
  return (
    <div className="space-y-1 mt-2">
      {nonGriddle.length > 0 && (
        <p className="text-sm" style={{ color: '#2c3e42' }}>
          <span className="mr-1">🍙</span>
          {summarizeItems(nonGriddle)}
        </p>
      )}
      {griddle.length > 0 && (
        <p className="text-sm" style={{ color: '#2c3e42' }}>
          <span className="mr-1">🔥</span>
          {summarizeItems(griddle)}
        </p>
      )}
    </div>
  );
}

// 左滑元件
function SwipeToComplete({ onComplete, children }: { onComplete: () => void; children: React.ReactNode }) {
  const startXRef = useRef<number | null>(null);
  const [offset, setOffset] = useState(0);
  const [swiped, setSwiped] = useState(false);
  const THRESHOLD = 80;

  const onTouchStart = (e: React.TouchEvent) => { startXRef.current = e.touches[0].clientX; };
  const onTouchMove = (e: React.TouchEvent) => {
    if (startXRef.current === null) return;
    const dx = startXRef.current - e.touches[0].clientX;
    if (dx > 0) setOffset(Math.min(dx, 120));
  };
  const onTouchEnd = () => {
    if (offset >= THRESHOLD && !swiped) {
      setSwiped(true);
      onComplete();
    }
    setOffset(0);
    startXRef.current = null;
  };

  return (
    <div className="relative overflow-hidden rounded-2xl">
      {/* 底層紅色背景 */}
      <div
        className="absolute inset-y-0 right-0 flex items-center justify-end px-5 rounded-2xl"
        style={{ backgroundColor: '#4a9d68', width: `${offset}px`, transition: offset === 0 ? 'width 0.2s' : 'none' }}
      >
        <span className="text-white text-xs font-bold whitespace-nowrap">完成</span>
      </div>
      {/* 卡片本體 */}
      <div
        style={{ transform: `translateX(-${offset}px)`, transition: offset === 0 ? 'transform 0.2s' : 'none' }}
        onTouchStart={onTouchStart}
        onTouchMove={onTouchMove}
        onTouchEnd={onTouchEnd}
      >
        {children}
      </div>
    </div>
  );
}

// 訂單卡片
function OrderCard({
  order,
  onStatusChange,
  onPaymentToggle,
}: {
  order: Order;
  onStatusChange: (id: string, status: Order['status']) => void;
  onPaymentToggle: (id: string, current: Order['payment_status']) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [completing, setCompleting] = useState(false);
  const complex = isComplex(order.items);

  const borderColor =
    order.status === 'SUBMITTED' ? '#c45c5c' :
    order.status === 'IN_PROGRESS' ? '#c49a30' : '#d0dce0';

  const statusLabel =
    order.status === 'SUBMITTED' ? '新單' :
    order.status === 'IN_PROGRESS' ? '製作中' : '完成';

  const statusBg =
    order.status === 'SUBMITTED' ? '#fde8e8' :
    order.status === 'IN_PROGRESS' ? '#fff4e6' : '#f0f4f5';

  const statusColor =
    order.status === 'SUBMITTED' ? '#c45c5c' :
    order.status === 'IN_PROGRESS' ? '#c49a30' : '#8a9a9f';

  const handleComplete = (e: React.MouseEvent) => {
    e.stopPropagation();
    setCompleting(true);
    setTimeout(() => onStatusChange(order.order_id, 'COMPLETED'), 400);
  };

  const cardContent = (
    <div
      className="rounded-2xl p-4 cursor-pointer transition-colors duration-300"
      style={{
        backgroundColor: completing ? '#e8f7ee' : order.status === 'COMPLETED' ? '#fafcfd' : 'white',
        border: '1px solid #d0dce0',
        borderLeft: `4px solid ${completing ? '#4a9d68' : borderColor}`,
        opacity: order.status === 'COMPLETED' ? 0.75 : 1,
        transition: 'background-color 0.3s, border-left-color 0.3s',
      }}
      onClick={() => complex && setExpanded((v) => !v)}
    >
      {/* 第一列：號碼 + 狀態 badge + 展開箭頭 */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="font-black" style={{ fontSize: 36, lineHeight: 1, color: '#2c3e42' }}>
            №{order.order_number}
          </span>
          <span
            className="font-semibold rounded-full"
            style={{
              backgroundColor: statusBg,
              color: statusColor,
              fontSize: 13,
              padding: '4px 10px',
            }}
          >
            {statusLabel}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs" style={{ color: '#8a9a9f' }}>{formatTime(order.created_at)}</span>
          {complex && (
            <span style={{ color: '#8a9a9f' }}>
              {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </span>
          )}
        </div>
      </div>

      {/* 第二列：內用/外帶 + 付款 */}
      <div className="flex items-center justify-between mt-1.5">
        <span className="font-bold" style={{ fontSize: 18, color: '#2c3e42' }}>
          {order.dine_type || '內用'}
        </span>
        {order.status !== 'COMPLETED' && (
          <PaymentPill
            status={order.payment_status}
            onToggle={() => onPaymentToggle(order.order_id, order.payment_status)}
          />
        )}
      </div>

      {/* 摘要或品項（依複雜度）*/}
      {!expanded && (
        complex
          ? <StationSummary items={order.items} />
          : (
            <div className="mt-2 space-y-0.5">
              {order.items.map((item, i) => (
                <p key={i} className="text-sm" style={{ color: '#2c3e42' }}>
                  {item.name}{item.quantity > 1 ? ` ×${item.quantity}` : ''}
                  {item.details ? `（${item.details}）` : ''}
                </p>
              ))}
            </div>
          )
      )}

      {/* 展開後：完整品項 + 按鈕 */}
      {expanded && (
        <div className="mt-3">
          <div
            className="rounded-xl p-3 space-y-1.5 mb-3"
            style={{ backgroundColor: '#f4f7f8' }}
          >
            {order.items.map((item, i) => (
              <div key={i} className="flex justify-between text-sm" style={{ color: '#2c3e42' }}>
                <span>{item.name}{item.details ? `（${item.details}）` : ''}</span>
                <span style={{ color: '#8a9a9f' }}>×{item.quantity}</span>
              </div>
            ))}
            <div
              className="flex justify-between pt-2 font-semibold text-sm"
              style={{ borderTop: '1px solid #d0dce0', color: '#729DAD' }}
            >
              <span>合計</span>
              <span>${order.total_price}</span>
            </div>
          </div>

        </div>
      )}

      {/* 底部：金額 + 動作按鈕 */}
      <div className="flex items-center justify-between mt-3 gap-2">
        <span className="text-sm font-semibold shrink-0" style={{ color: '#729DAD' }}>
          ${order.total_price}
        </span>

        {order.status === 'SUBMITTED' && (
          <div className="flex gap-2">
            <button
              onClick={(e) => { e.stopPropagation(); onStatusChange(order.order_id, 'IN_PROGRESS'); }}
              className="px-4 py-2 rounded-xl text-sm font-semibold transition-transform active:scale-95"
              style={{ backgroundColor: '#fff4e6', color: '#c49a30', border: '1px solid #f5c98a' }}
            >
              開始製作
            </button>
            <button
              onClick={handleComplete}
              className="px-4 py-2 rounded-xl text-sm font-semibold text-white transition-transform active:scale-95"
              style={{ backgroundColor: '#4a9d68' }}
            >
              完成出餐
            </button>
          </div>
        )}

        {order.status === 'IN_PROGRESS' && (
          <button
            onClick={handleComplete}
            className="px-4 py-2 rounded-xl text-sm font-semibold text-white transition-transform active:scale-95"
            style={{ backgroundColor: '#4a9d68' }}
          >
            完成出餐
          </button>
        )}
      </div>
    </div>
  );

  return cardContent;
}

// ───────────────────────────── 主元件 ─────────────────────────────

export default function AdminOrdersPage() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [activeTab, setActiveTab] = useState<TabType>('ACTIVE');
  const [toast, setToast] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── 提示音 ──
  const playDing = useCallback(() => {
    try {
      if (!audioRef.current) {
        audioRef.current = new Audio('/sounds/ding.mp3');
      }
      audioRef.current.currentTime = 0;
      audioRef.current.play().catch(() => {});
    } catch {}
  }, []);

  // ── Toast 通知 ──
  const showToast = useCallback((msg: string) => {
    setToast(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);

  // ── 載入今日訂單 ──
  const fetchOrders = useCallback(async () => {
    try {
      const res = await fetch('/admin/orders/list');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setOrders(data.items);
    } catch (e) {
      console.error('載入訂單失敗:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  // ── SSE 訂閱 ──
  useEffect(() => {
    const es = new EventSource('/admin/orders/stream');

    es.addEventListener('new_order', (e) => {
      const order: Order = JSON.parse(e.data);
      setOrders((prev) => {
        // 若已存在則不重複插入
        if (prev.some((o) => o.order_id === order.order_id)) return prev;
        return [order, ...prev].sort(
          (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        );
      });
      playDing();
      showToast(`🔔 №${order.order_number} 新單！`);
      setActiveTab('ACTIVE');
    });

    es.onerror = () => {
      // 靜默重連，瀏覽器自動 retry
    };

    return () => es.close();
  }, [playDing, showToast]);

  // ── 更新狀態（樂觀更新）──
  const handleStatusChange = useCallback(async (order_id: string, status: Order['status']) => {
    setOrders((prev) =>
      prev.map((o) => o.order_id === order_id ? { ...o, status } : o)
    );
    try {
      await fetch(`/admin/orders/${order_id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
    } catch (e) {
      console.error('更新狀態失敗:', e);
      fetchOrders(); // 失敗時重新載入
    }
  }, [fetchOrders]);

  // ── 切換付款狀態（樂觀更新）──
  const handlePaymentToggle = useCallback(async (order_id: string, current: Order['payment_status']) => {
    const next = current === 'UNPAID' ? 'PAID' : 'UNPAID';
    setOrders((prev) =>
      prev.map((o) => o.order_id === order_id ? { ...o, payment_status: next } : o)
    );
    try {
      await fetch(`/admin/orders/${order_id}/payment`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payment_status: next }),
      });
    } catch (e) {
      console.error('更新付款狀態失敗:', e);
      fetchOrders();
    }
  }, [fetchOrders]);

  // ── Tab 篩選 ──
  const filtered = activeTab === 'ACTIVE'
    ? orders.filter((o) => o.status === 'SUBMITTED' || o.status === 'IN_PROGRESS')
    : orders.filter((o) => o.status === 'COMPLETED');
  const counts = {
    ACTIVE: orders.filter((o) => o.status === 'SUBMITTED' || o.status === 'IN_PROGRESS').length,
    COMPLETED: orders.filter((o) => o.status === 'COMPLETED').length,
  };

  // ───────────────────────────── 渲染 ─────────────────────────────

  return (
    <div className="min-h-screen" style={{ backgroundColor: '#f4f7f8' }}>

      {/* ─── Toast ─── */}
      {toast && (
        <div
          className="fixed top-4 right-4 z-50 px-4 py-3 rounded-2xl text-sm font-semibold shadow-lg flex items-center gap-2"
          style={{ backgroundColor: '#2c3e42', color: 'white', boxShadow: '0 4px 20px rgba(0,0,0,0.2)' }}
        >
          <Bell size={16} />
          {toast}
        </div>
      )}

      {/* ─── Sticky Header ─── */}
      <header className="sticky z-20 px-4 pt-4 pb-3" style={{ top: '52px', backgroundColor: '#f4f7f8' }}>
        <div
          className="rounded-2xl p-4"
          style={{
            background: 'linear-gradient(135deg, #ffffff 0%, #edf3f5 100%)',
            border: '1px solid #d0dce0',
            boxShadow: '0 2px 12px rgba(114, 157, 173, 0.12)',
          }}
        >
          {/* 標題列 */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <ShoppingBag size={18} color="#729DAD" />
              <h1 className="text-lg font-bold" style={{ color: '#2c3e42' }}>訂單列表</h1>
            </div>
            <span className="text-xs" style={{ color: '#8a9a9f' }}>
              今日 {orders.length} 筆
            </span>
          </div>

          {/* Tab 切換 */}
          <div
            className="flex rounded-xl p-0.5 gap-0.5"
            style={{ backgroundColor: '#e8eef0' }}
          >
            {([
              { key: 'ACTIVE', label: '進行中', activeColor: '#c45c5c' },
              { key: 'COMPLETED', label: '完成', activeColor: '#729DAD' },
            ] as { key: TabType; label: string; activeColor: string }[]).map(({ key, label, activeColor }) => {
              const isActive = activeTab === key;
              const count = counts[key];
              return (
                <button
                  key={key}
                  onClick={() => setActiveTab(key)}
                  className="flex-1 py-1.5 rounded-[10px] text-xs font-medium transition-all flex items-center justify-center gap-1"
                  style={{
                    backgroundColor: isActive ? 'white' : 'transparent',
                    color: isActive ? '#2c3e42' : '#5a6b70',
                    boxShadow: isActive ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                  }}
                >
                  {label}
                  {count > 0 && (
                    <span
                      className="px-1.5 py-0.5 rounded-full text-xs leading-none"
                      style={{
                        backgroundColor: isActive ? activeColor : '#d0dce0',
                        color: isActive ? 'white' : '#5a6b70',
                      }}
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </header>

      {/* ─── 訂單列表 ─── */}
      <main className="max-w-lg mx-auto px-4 pb-10 pt-2">
        {loading ? (
          <p className="text-center py-12" style={{ color: '#8a9a9f' }}>載入中...</p>
        ) : filtered.length === 0 ? (
          <div
            className="rounded-2xl p-10 text-center mt-4"
            style={{ backgroundColor: 'white', border: '1px solid #d0dce0' }}
          >
            <ShoppingBag size={32} color="#d0dce0" className="mx-auto mb-2" />
            <p style={{ color: '#8a9a9f' }}>
              {activeTab === 'ACTIVE' ? '目前沒有進行中的單' : '今日尚無完成訂單'}
            </p>
          </div>
        ) : (
          <div className="space-y-3 mt-2">
            {filtered.map((order) => (
              <OrderCard
                key={order.order_id}
                order={order}
                onStatusChange={handleStatusChange}
                onPaymentToggle={handlePaymentToggle}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
