'use client';

import { useState, useEffect, useCallback } from 'react';

// ───────────────────────────── 型別定義 ─────────────────────────────

interface MenuItem {
  name: string;
  price: number;
}

interface MenuCategory {
  name: string;
  icon: string;
  items: MenuItem[];
}

interface ComboStatusEntry {
  available: boolean;
  reason?: string;
}

interface AdminMenuState {
  categories: MenuCategory[];
  sold_out_items: string[];
  sold_out_categories: Record<string, boolean>;
  effective_sold_out: string[];
  combo_status: Record<string, ComboStatusEntry>;
  business_hours: { open: string; close: string };
  is_open_override: boolean | null;
  is_currently_open: boolean;
}

// 分類控制的顯示設定
interface CategoryControl {
  key: string;
  label: string;
  group: string;
}

const CATEGORY_CONTROLS: CategoryControl[] = [
  // 載體
  { key: 'carrier_toast', label: '吐司', group: '載體' },
  { key: 'carrier_burger', label: '漢堡', group: '載體' },
  { key: 'carrier_thick_toast', label: '厚片', group: '載體' },
  // 米種
  { key: 'rice_purple', label: '紫米', group: '米種' },
  { key: 'rice_white', label: '白米', group: '米種' },
  // 饅頭
  { key: 'mantou_black_sugar', label: '黑糖饅頭', group: '饅頭' },
  { key: 'mantou_white', label: '白饅頭', group: '饅頭' },
  { key: 'mantou_black_sugar_roll', label: '黑糖花捲', group: '饅頭' },
  { key: 'mantou_white_roll', label: '白花捲', group: '饅頭' },
  { key: 'mantou_taro', label: '芋頭饅頭', group: '饅頭' },
  // 鐵板麵
  { key: 'noodle_oil', label: '油麵', group: '鐵板麵' },
  { key: 'noodle_udon', label: '烏龍麵', group: '鐵板麵' },
  // 其他
  { key: 'scallion_pancake', label: '蔥抓餅', group: '其他' },
];

// 分類控制分組
const CATEGORY_GROUPS = ['載體', '米種', '饅頭', '鐵板麵', '其他'];

// ───────────────────────────── 主元件 ─────────────────────────────

export default function AdminMenuPage() {
  const [state, setState] = useState<AdminMenuState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('全部');
  const [editingHours, setEditingHours] = useState(false);
  const [hoursInput, setHoursInput] = useState({ open: '', close: '' });
  const [saving, setSaving] = useState(false);

  // ── 載入狀態 ──
  const fetchState = useCallback(async () => {
    try {
      const res = await fetch('/admin/menu/state');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: AdminMenuState = await res.json();
      setState(data);
      setError(null);
    } catch (e) {
      setError('無法連線到後端，請確認後端服務正在執行');
      console.error('載入菜單狀態失敗:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchState();
  }, [fetchState]);

  // ── 品項售完 toggle（樂觀更新）──
  const toggleItem = useCallback(async (itemName: string, currentSoldOut: boolean) => {
    if (!state) return;
    const newSoldOut = !currentSoldOut;

    // 樂觀更新
    setState((prev) => {
      if (!prev) return prev;
      const sold_out_items = newSoldOut
        ? [...prev.sold_out_items, itemName]
        : prev.sold_out_items.filter((n) => n !== itemName);
      return { ...prev, sold_out_items };
    });

    try {
      const res = await fetch('/admin/menu/sold-out/item', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: itemName, sold_out: newSoldOut }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // 重新載入以取得連動後的正確狀態
      await fetchState();
    } catch (e) {
      // 失敗：rollback
      console.error('更新品項售完狀態失敗:', e);
      setState((prev) => {
        if (!prev) return prev;
        const sold_out_items = currentSoldOut
          ? [...prev.sold_out_items, itemName]
          : prev.sold_out_items.filter((n) => n !== itemName);
        return { ...prev, sold_out_items };
      });
    }
  }, [state, fetchState]);

  // ── 分類售完 toggle（樂觀更新）──
  const toggleCategory = useCallback(async (key: string, currentSoldOut: boolean) => {
    if (!state) return;
    const newSoldOut = !currentSoldOut;

    // 樂觀更新
    setState((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        sold_out_categories: { ...prev.sold_out_categories, [key]: newSoldOut },
      };
    });

    try {
      const res = await fetch('/admin/menu/sold-out/category', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, sold_out: newSoldOut }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchState();
    } catch (e) {
      // 失敗：rollback
      console.error('更新分類售完狀態失敗:', e);
      setState((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          sold_out_categories: { ...prev.sold_out_categories, [key]: currentSoldOut },
        };
      });
    }
  }, [state, fetchState]);

  // ── 一鍵恢復全部 ──
  const resetAllSoldOut = useCallback(async () => {
    setSaving(true);
    try {
      const res = await fetch('/admin/menu/reset-sold-out', { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchState();
    } catch (e) {
      console.error('一鍵恢復失敗:', e);
    } finally {
      setSaving(false);
    }
  }, [fetchState]);

  // ── 儲存營業時間 ──
  const saveBusinessHours = useCallback(async () => {
    setSaving(true);
    try {
      const res = await fetch('/admin/menu/business-hours', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ open: hoursInput.open, close: hoursInput.close }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setEditingHours(false);
      await fetchState();
    } catch (e) {
      console.error('儲存營業時間失敗:', e);
    } finally {
      setSaving(false);
    }
  }, [hoursInput, fetchState]);

  // ── 手動 override 營業狀態 ──
  const setOpenOverride = useCallback(async (override: boolean | null) => {
    try {
      const res = await fetch('/admin/menu/open-override', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ override }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchState();
    } catch (e) {
      console.error('設定營業狀態失敗:', e);
    }
  }, [fetchState]);

  // ── 計算目前 effective_sold_out 中各分類的售完數量 ──
  const getSoldOutCountForCategory = useCallback((catName: string): number => {
    if (!state) return 0;
    const cat = state.categories.find((c) => c.name === catName);
    if (!cat) return 0;
    return cat.items.filter((item) => state.effective_sold_out.includes(item.name)).length;
  }, [state]);

  // ── 過濾品項列表 ──
  const filteredCategories = state
    ? selectedCategory === '全部'
      ? state.categories
      : state.categories.filter((c) => c.name === selectedCategory)
    : [];

  // ── 總售完數量（用於一鍵恢復按鈕提示）──
  const totalSoldOut = state
    ? state.sold_out_items.length + Object.values(state.sold_out_categories).filter(Boolean).length
    : 0;

  // ───────── Loading / Error ─────────

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: '#f4f7f8' }}>
        <p className="text-lg" style={{ color: '#5a6b70' }}>載入中...</p>
      </div>
    );
  }

  if (error || !state) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: '#f4f7f8' }}>
        <div className="text-center p-6">
          <p className="text-lg mb-4" style={{ color: '#c45c5c' }}>{error || '未知錯誤'}</p>
          <button
            onClick={fetchState}
            className="px-4 py-2 rounded-xl text-white text-sm font-medium"
            style={{ backgroundColor: '#729DAD' }}
          >
            重試
          </button>
        </div>
      </div>
    );
  }

  // ───────────────────────────── 渲染 ─────────────────────────────

  return (
    <div className="min-h-screen pb-10" style={{ backgroundColor: '#f4f7f8' }}>
      <div className="max-w-md mx-auto px-4">

        {/* ─── Header：店名 + 營業時間 + 狀態 ─── */}
        <header
          className="sticky top-0 z-10 pt-4 pb-3"
          style={{ backgroundColor: '#f4f7f8' }}
        >
          <div
            className="rounded-2xl p-4"
            style={{
              background: 'linear-gradient(135deg, #ffffff 0%, #e8eef0 100%)',
              border: '1px solid #d0dce0',
              boxShadow: '0 2px 12px rgba(114, 157, 173, 0.12)',
            }}
          >
            {/* 標題列 */}
            <div className="flex items-center justify-between mb-3">
              <h1 className="text-xl font-bold" style={{ color: '#2c3e42' }}>
                🏪 菜單管理
              </h1>
              {/* 目前營業狀態 */}
              <span
                className="text-sm font-medium px-3 py-1 rounded-full"
                style={{
                  backgroundColor: state.is_currently_open ? '#dcf0e4' : '#fde8e8',
                  color: state.is_currently_open ? '#4a9d68' : '#c45c5c',
                }}
              >
                {state.is_currently_open ? '🟢 營業中' : '🔴 已休息'}
              </span>
            </div>

            {/* 營業時間 */}
            {editingHours ? (
              <div className="flex items-center gap-2 mb-3">
                <input
                  type="time"
                  value={hoursInput.open}
                  onChange={(e) => setHoursInput((prev) => ({ ...prev, open: e.target.value }))}
                  className="flex-1 px-3 py-1.5 rounded-lg text-sm border"
                  style={{ borderColor: '#d0dce0', color: '#2c3e42' }}
                />
                <span style={{ color: '#5a6b70' }}>–</span>
                <input
                  type="time"
                  value={hoursInput.close}
                  onChange={(e) => setHoursInput((prev) => ({ ...prev, close: e.target.value }))}
                  className="flex-1 px-3 py-1.5 rounded-lg text-sm border"
                  style={{ borderColor: '#d0dce0', color: '#2c3e42' }}
                />
                <button
                  onClick={saveBusinessHours}
                  disabled={saving}
                  className="px-3 py-1.5 rounded-lg text-sm text-white font-medium"
                  style={{ backgroundColor: '#4a9d68' }}
                >
                  儲存
                </button>
                <button
                  onClick={() => setEditingHours(false)}
                  className="px-3 py-1.5 rounded-lg text-sm"
                  style={{ backgroundColor: '#e8eef0', color: '#5a6b70' }}
                >
                  取消
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm" style={{ color: '#5a6b70' }}>
                  營業時間：{state.business_hours.open} – {state.business_hours.close}
                </span>
                <button
                  onClick={() => {
                    setHoursInput({
                      open: state.business_hours.open,
                      close: state.business_hours.close,
                    });
                    setEditingHours(true);
                  }}
                  className="text-sm px-2 py-0.5 rounded-lg transition-colors"
                  style={{ backgroundColor: '#e8eef0', color: '#729DAD' }}
                >
                  ✏️ 編輯
                </button>
              </div>
            )}

            {/* 手動 override 控制 */}
            <div className="flex items-center gap-2">
              <span className="text-xs" style={{ color: '#5a6b70' }}>手動控制：</span>
              {[
                { label: '自動', value: null },
                { label: '強制營業', value: true },
                { label: '強制休息', value: false },
              ].map(({ label, value }) => {
                const isActive = state.is_open_override === value;
                return (
                  <button
                    key={label}
                    onClick={() => setOpenOverride(value)}
                    className="flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors"
                    style={{
                      backgroundColor: isActive ? '#729DAD' : '#e8eef0',
                      color: isActive ? 'white' : '#5a6b70',
                    }}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          </div>
        </header>

        {/* ─── 一鍵恢復 ─── */}
        <div className="mt-3">
          <button
            onClick={resetAllSoldOut}
            disabled={saving || totalSoldOut === 0}
            className="w-full py-3 rounded-xl font-medium text-sm transition-opacity"
            style={{
              backgroundColor: totalSoldOut > 0 ? '#729DAD' : '#d0dce0',
              color: totalSoldOut > 0 ? 'white' : '#8a9a9f',
              opacity: saving ? 0.7 : 1,
            }}
          >
            {totalSoldOut > 0
              ? `🔄 一鍵恢復全部（${totalSoldOut} 項售完）`
              : '✅ 目前無售完品項'}
          </button>
        </div>

        {/* ─── 分類控制區 ─── */}
        <section
          className="mt-3 rounded-2xl p-4"
          style={{
            backgroundColor: 'white',
            border: '1px solid #d0dce0',
            boxShadow: '0 2px 8px rgba(114, 157, 173, 0.08)',
          }}
        >
          <h2 className="text-sm font-semibold mb-3" style={{ color: '#729DAD' }}>
            分類控制
          </h2>
          {CATEGORY_GROUPS.map((group) => {
            const controls = CATEGORY_CONTROLS.filter((c) => c.group === group);
            return (
              <div key={group} className="mb-3 last:mb-0">
                <p className="text-xs mb-1.5" style={{ color: '#8a9a9f' }}>{group}</p>
                <div className="flex flex-wrap gap-2">
                  {controls.map(({ key, label }) => {
                    const isSoldOut = state.sold_out_categories[key] ?? false;
                    return (
                      <button
                        key={key}
                        onClick={() => toggleCategory(key, isSoldOut)}
                        className="px-3 py-1.5 rounded-full text-sm font-medium transition-colors"
                        style={{
                          backgroundColor: isSoldOut ? '#c45c5c' : '#4a9d68',
                          color: 'white',
                        }}
                      >
                        {label} {isSoldOut ? '🔴' : '🟢'}
                      </button>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </section>

        {/* ─── 分類 pill tabs（橫向滑動）─── */}
        <div className="mt-3 -mx-4 px-4 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
          <div className="flex gap-2 pb-1" style={{ width: 'max-content' }}>
            {['全部', ...state.categories.map((c) => c.name)].map((catName) => {
              const isSelected = selectedCategory === catName;
              const soldOutCount = catName !== '全部' ? getSoldOutCountForCategory(catName) : 0;
              return (
                <button
                  key={catName}
                  onClick={() => setSelectedCategory(catName)}
                  className="px-4 py-2 rounded-full text-sm font-medium whitespace-nowrap transition-colors"
                  style={{
                    backgroundColor: isSelected ? '#729DAD' : '#e8eef0',
                    color: isSelected ? 'white' : '#5a6b70',
                  }}
                >
                  {catName}
                  {soldOutCount > 0 && (
                    <span
                      className="ml-1.5 text-xs px-1.5 py-0.5 rounded-full"
                      style={{
                        backgroundColor: isSelected ? 'rgba(255,255,255,0.3)' : '#c45c5c',
                        color: 'white',
                      }}
                    >
                      {soldOutCount}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {/* ─── 品項列表 ─── */}
        <div className="mt-3 space-y-3">
          {filteredCategories.map((cat) => {
            const soldOutInCat = getSoldOutCountForCategory(cat.name);
            return (
              <section
                key={cat.name}
                className="rounded-2xl overflow-hidden"
                style={{
                  backgroundColor: 'white',
                  border: '1px solid #d0dce0',
                  boxShadow: '0 2px 8px rgba(114, 157, 173, 0.08)',
                }}
              >
                {/* 分類標題 */}
                <div
                  className="px-4 py-3 flex items-center gap-2"
                  style={{
                    borderBottom: '1px solid #e8eef0',
                    background: 'linear-gradient(135deg, #f4f7f8 0%, #e8eef0 100%)',
                  }}
                >
                  <span className="text-lg">{cat.icon}</span>
                  <span className="font-semibold text-sm" style={{ color: '#2c3e42' }}>
                    {cat.name}
                  </span>
                  {soldOutInCat > 0 && (
                    <span
                      className="text-xs px-2 py-0.5 rounded-full"
                      style={{ backgroundColor: '#fde8e8', color: '#c45c5c' }}
                    >
                      {soldOutInCat} 售完
                    </span>
                  )}
                </div>

                {/* 品項列表 */}
                <div className="divide-y" style={{ borderColor: '#f0f4f5' }}>
                  {cat.items.map((item) => {
                    // 判斷品項是否為套餐連動鎖定（combo_status key 是簡稱如「套餐一」，item.name 是全稱）
                    const comboMatch = Object.entries(state.combo_status).find(
                      ([key]) => item.name.startsWith(key)
                    );
                    const comboEntry = comboMatch ? comboMatch[1] as { available: boolean; reason?: string } : undefined;
                    const isComboLocked = comboEntry !== undefined && !comboEntry.available;

                    // 品項是否手動標記售完
                    const isManualSoldOut = state.sold_out_items.includes(item.name);

                    // 最終 effective 是否售完（含連動）
                    const isEffectiveSoldOut = state.effective_sold_out.includes(item.name);

                    return (
                      <div
                        key={item.name}
                        className="flex items-center px-4 py-3 gap-3"
                        style={{
                          opacity: isEffectiveSoldOut && !isManualSoldOut && !isComboLocked ? 0.6 : 1,
                        }}
                      >
                        {/* 品項名稱 + 價格 */}
                        <div className="flex-1 min-w-0">
                          <span
                            className="text-sm"
                            style={{
                              color: isEffectiveSoldOut ? '#8a9a9f' : '#2c3e42',
                              textDecoration: isEffectiveSoldOut ? 'line-through' : 'none',
                            }}
                          >
                            {item.name}
                          </span>
                          {/* 套餐連動：顯示原因 */}
                          {isComboLocked && comboEntry.reason && (
                            <p className="text-xs mt-0.5" style={{ color: '#c45c5c' }}>
                              {comboEntry.reason}
                            </p>
                          )}
                          {item.price > 0 && (
                            <span className="text-xs ml-2" style={{ color: '#729DAD' }}>
                              ${item.price}
                            </span>
                          )}
                        </div>

                        {/* Toggle 按鈕或鎖定圖示 */}
                        {isComboLocked ? (
                          // 套餐連動鎖定：顯示 🔒
                          <div
                            className="w-10 h-10 rounded-xl flex items-center justify-center text-lg"
                            style={{ backgroundColor: '#fde8e8' }}
                            title={comboEntry.reason ?? '連動鎖定'}
                          >
                            🔒
                          </div>
                        ) : (
                          // 一般品項：toggle 按鈕
                          <button
                            onClick={() => toggleItem(item.name, isManualSoldOut)}
                            className="w-10 h-10 rounded-xl flex items-center justify-center text-lg transition-colors active:scale-95"
                            style={{
                              backgroundColor: isManualSoldOut ? '#fde8e8' : '#dcf0e4',
                            }}
                            aria-label={isManualSoldOut ? `恢復 ${item.name}` : `標記 ${item.name} 售完`}
                          >
                            {isManualSoldOut ? '🔴' : '🟢'}
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>

        {/* ─── 底部空間（避免最後一個卡片被截）─── */}
        <div className="h-6" />
      </div>
    </div>
  );
}
