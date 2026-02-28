'use client';

import { useState, useEffect, useCallback } from 'react';
import { Search, RotateCcw, Clock, Store, AlertCircle, RefreshCw } from 'lucide-react';

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

interface CategoryControl {
  key: string;
  label: string;
  group: string;
}

// ───────────────────────────── 常數 ─────────────────────────────

const CATEGORY_CONTROLS: CategoryControl[] = [
  { key: 'carrier_toast', label: '吐司', group: '載體' },
  { key: 'carrier_burger', label: '漢堡', group: '載體' },
  { key: 'carrier_thick_toast', label: '厚片', group: '載體' },
  { key: 'rice_purple', label: '紫米', group: '米種' },
  { key: 'rice_white', label: '白米', group: '米種' },
  { key: 'mantou_black_sugar', label: '黑糖饅頭', group: '饅頭' },
  { key: 'mantou_white', label: '白饅頭', group: '饅頭' },
  { key: 'mantou_black_sugar_roll', label: '黑糖花捲', group: '饅頭' },
  { key: 'mantou_white_roll', label: '白花捲', group: '饅頭' },
  { key: 'mantou_taro', label: '芋頭饅頭', group: '饅頭' },
  { key: 'noodle_oil', label: '油麵', group: '鐵板麵' },
  { key: 'noodle_udon', label: '烏龍麵', group: '鐵板麵' },
  { key: 'scallion_pancake', label: '蔥抓餅', group: '其他' },
];

// 分類 → 相關備料 key 的對應（只有真正有「選項」概念的分類才顯示 chips）
const CATEGORY_RELATED_CONTROLS: Record<string, string[]> = {
  '飯糰':   ['rice_purple', 'rice_white'],
  '鐵板麵': ['noodle_oil', 'noodle_udon'],
};

// ───────────────────────────── 子元件 ─────────────────────────────

function ToggleSwitch({
  checked,
  onChange,
  disabled = false,
}: {
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      onClick={disabled ? undefined : onChange}
      disabled={disabled}
      className="relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors duration-200 focus:outline-none"
      style={{
        backgroundColor: disabled ? '#e0e6e8' : checked ? '#4a9d68' : '#d0dce0',
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      <span
        className="inline-block h-5 w-5 rounded-full bg-white shadow-sm transition-transform duration-200"
        style={{ transform: checked ? 'translateX(22px)' : 'translateX(2px)' }}
      />
    </button>
  );
}

// 備料 chip — 顯示在分類頂部，點擊切換售完
function OptionChip({
  label,
  isSoldOut,
  onToggle,
}: {
  label: string;
  isSoldOut: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all active:scale-95"
      style={{
        backgroundColor: isSoldOut ? '#fde8e8' : '#dcf0e4',
        color: isSoldOut ? '#c45c5c' : '#4a9d68',
        border: `1px solid ${isSoldOut ? '#f5c0c0' : '#b4dfc4'}`,
      }}
    >
      <span
        className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
        style={{ backgroundColor: isSoldOut ? '#c45c5c' : '#4a9d68' }}
      />
      {label}
    </button>
  );
}

// ───────────────────────────── 主元件 ─────────────────────────────

export default function AdminMenuPage() {
  const [state, setState] = useState<AdminMenuState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingHours, setEditingHours] = useState(false);
  const [hoursInput, setHoursInput] = useState({ open: '', close: '' });
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeCategory, setActiveCategory] = useState<string>('');

  // ── 載入狀態 ──
  const fetchState = useCallback(async (): Promise<AdminMenuState | null> => {
    try {
      const res = await fetch('/admin/menu/state');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: AdminMenuState = await res.json();
      setState(data);
      setActiveCategory((prev) => prev || data.categories[0]?.name || '');
      setError(null);
      return data;
    } catch (e) {
      setError('無法連線到後端，請確認後端服務正在執行');
      console.error('載入菜單狀態失敗:', e);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  // ── 套餐連動：將 combo_status.available=false 的套餐同步寫入 sold_out_items ──
  const syncComboStatus = useCallback(async (newState: AdminMenuState) => {
    const toClose: string[] = [];
    for (const [comboKey, comboEntry] of Object.entries(newState.combo_status)) {
      if (comboEntry.available) continue;
      for (const cat of newState.categories) {
        for (const item of cat.items) {
          if (item.name.startsWith(comboKey) && !newState.sold_out_items.includes(item.name)) {
            toClose.push(item.name);
          }
        }
      }
    }
    if (toClose.length === 0) return;
    try {
      await Promise.all(
        toClose.map((name) =>
          fetch('/admin/menu/sold-out/item', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, sold_out: true }),
          })
        )
      );
      await fetchState();
    } catch (e) {
      console.error('套餐連動同步失敗:', e);
      await fetchState();
    }
  }, [fetchState]);

  useEffect(() => { fetchState(); }, [fetchState]);

  // ── 取得同飲品的所有尺寸變體（如「有糖豆漿(中)」→「有糖豆漿(大)」）──
  const getSizeVariants = useCallback((itemName: string): string[] => {
    if (!state) return [itemName];
    const sizeMatch = itemName.match(/^(.+)\((中|大|小)\)$/);
    if (!sizeMatch) return [itemName];
    const base = sizeMatch[1];
    const variants: string[] = [];
    for (const cat of state.categories) {
      for (const item of cat.items) {
        if (item.name.match(/^(.+)\((中|大|小)\)$/)
          && item.name.startsWith(base + '(')) {
          variants.push(item.name);
        }
      }
    }
    return variants.length > 0 ? variants : [itemName];
  }, [state]);

  // ── 品項售完 toggle（樂觀更新，標記售完時連動同款其他尺寸 + 套餐連動）──
  const toggleItem = useCallback(async (itemName: string, currentSoldOut: boolean) => {
    if (!state) return;
    const newSoldOut = !currentSoldOut;
    // 標記售完時，連動同款其他尺寸
    const targets = newSoldOut ? getSizeVariants(itemName) : [itemName];

    setState((prev) => {
      if (!prev) return prev;
      let sold_out_items = [...prev.sold_out_items];
      for (const name of targets) {
        if (newSoldOut && !sold_out_items.includes(name)) {
          sold_out_items.push(name);
        } else if (!newSoldOut) {
          sold_out_items = sold_out_items.filter((n) => n !== name);
        }
      }
      return { ...prev, sold_out_items };
    });
    try {
      await Promise.all(targets.map((name) =>
        fetch('/admin/menu/sold-out/item', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, sold_out: newSoldOut }),
        })
      ));
      const newState = await fetchState();
      if (newState) await syncComboStatus(newState);
    } catch (e) {
      console.error('更新品項售完狀態失敗:', e);
      await fetchState();
    }
  }, [state, fetchState, getSizeVariants, syncComboStatus]);

  // ── 備料/選項 toggle（樂觀更新 + 套餐連動）──
  const toggleCategory = useCallback(async (key: string, currentSoldOut: boolean) => {
    if (!state) return;
    const newSoldOut = !currentSoldOut;
    setState((prev) => {
      if (!prev) return prev;
      return { ...prev, sold_out_categories: { ...prev.sold_out_categories, [key]: newSoldOut } };
    });
    try {
      const res = await fetch('/admin/menu/sold-out/category', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key, sold_out: newSoldOut }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const newState = await fetchState();
      if (newState) await syncComboStatus(newState);
    } catch (e) {
      console.error('更新分類售完狀態失敗:', e);
      setState((prev) => {
        if (!prev) return prev;
        return { ...prev, sold_out_categories: { ...prev.sold_out_categories, [key]: currentSoldOut } };
      });
    }
  }, [state, fetchState, syncComboStatus]);

  // ── 一鍵切換單一分類所有品項（全售完 ↔ 全恢復）+ 套餐連動 ──
  const toggleAllItems = useCallback(async (items: MenuItem[], targetSoldOut: boolean) => {
    if (!state) return;
    const toChange = items.filter(
      (item) => state.sold_out_items.includes(item.name) !== targetSoldOut
    );
    if (toChange.length === 0) return;
    try {
      await Promise.all(
        toChange.map((item) =>
          fetch('/admin/menu/sold-out/item', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: item.name, sold_out: targetSoldOut }),
          })
        )
      );
      const newState = await fetchState();
      if (newState) await syncComboStatus(newState);
    } catch (e) {
      console.error('批次更新售完狀態失敗:', e);
      await fetchState();
    }
  }, [state, fetchState, syncComboStatus]);

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

  // ── 營業狀態切換 ──
  const setOpenOverride = useCallback(async (override: boolean | null) => {
    setState((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        is_open_override: override,
        is_currently_open: override !== null ? override : prev.is_currently_open,
      };
    });
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

  // ───────── Loading / Error ─────────

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: '#f4f7f8' }}>
        <p style={{ color: '#5a6b70' }}>載入中...</p>
      </div>
    );
  }

  if (error || !state) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: '#f4f7f8' }}>
        <div className="text-center p-6">
          <AlertCircle className="mx-auto mb-3" size={32} color="#c45c5c" />
          <p className="mb-4" style={{ color: '#c45c5c' }}>{error || '未知錯誤'}</p>
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

  // ── 衍生狀態 ──
  const totalSoldOut = state.sold_out_items.length +
    Object.values(state.sold_out_categories).filter(Boolean).length;
  const isOverrideActive = state.is_open_override !== null;
  const searchLower = searchQuery.toLowerCase().trim();
  const isSearching = searchLower.length > 0;

  // 搜尋時跨分類顯示，否則只顯示目前 tab
  const visibleCategories = isSearching
    ? state.categories
        .map((cat) => ({ ...cat, items: cat.items.filter((i) => i.name.toLowerCase().includes(searchLower)) }))
        .filter((cat) => cat.items.length > 0)
    : state.categories.filter((c) => c.name === activeCategory);

  const categoryNames = state.categories.map((c) => c.name);

  // 取得某分類的售完數量
  const getSoldOutCount = (catName: string) => {
    const cat = state.categories.find((c) => c.name === catName);
    if (!cat) return 0;
    return cat.items.filter((item) => state.effective_sold_out.includes(item.name)).length;
  };

  // ───────────────────────────── 渲染 ─────────────────────────────

  return (
    <div className="min-h-screen" style={{ backgroundColor: '#f4f7f8' }}>

      {/* ─── Sticky Header ─── */}
      <header
        className="sticky z-20 px-4 pt-4 pb-3"
        style={{ top: '52px', backgroundColor: '#f4f7f8' }}
      >
        <div
          className="rounded-2xl p-4"
          style={{
            background: 'linear-gradient(135deg, #ffffff 0%, #edf3f5 100%)',
            border: '1px solid #d0dce0',
            boxShadow: '0 2px 12px rgba(114, 157, 173, 0.12)',
          }}
        >
          {/* 店名 + 狀態 badge */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Store size={18} color="#729DAD" />
              <h1 className="text-lg font-bold" style={{ color: '#2c3e42' }}>菜單管理</h1>
            </div>
            <span
              className="text-xs font-semibold px-3 py-1 rounded-full"
              style={{
                backgroundColor: state.is_currently_open ? '#dcf0e4' : '#fde8e8',
                color: state.is_currently_open ? '#4a9d68' : '#c45c5c',
              }}
            >
              {state.is_currently_open ? '● 營業中' : '● 已休息'}
            </span>
          </div>

          {/* 營業 toggle + 重設自動 */}
          <div className="flex items-center gap-3 mb-3">
            <ToggleSwitch
              checked={state.is_currently_open}
              onChange={() => setOpenOverride(state.is_currently_open ? false : true)}
            />
            <span className="text-sm" style={{ color: '#4a5a60' }}>
              {state.is_currently_open ? '目前營業中' : '目前休息中'}
            </span>
            {isOverrideActive && (
              <button
                onClick={() => setOpenOverride(null)}
                className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg ml-auto active:scale-95 transition-transform"
                style={{ backgroundColor: '#e8eef0', color: '#729DAD' }}
              >
                <RefreshCw size={11} />
                重設自動
              </button>
            )}
          </div>

          {/* 營業時間 */}
          <div className="flex items-center gap-2">
            <Clock size={14} color="#8a9a9f" />
            {editingHours ? (
              <>
                <input
                  type="time"
                  value={hoursInput.open}
                  onChange={(e) => setHoursInput((p) => ({ ...p, open: e.target.value }))}
                  className="flex-1 px-2 py-1 rounded-lg text-sm border"
                  style={{ borderColor: '#d0dce0', color: '#2c3e42', backgroundColor: 'white' }}
                />
                <span style={{ color: '#8a9a9f', fontSize: 12 }}>–</span>
                <input
                  type="time"
                  value={hoursInput.close}
                  onChange={(e) => setHoursInput((p) => ({ ...p, close: e.target.value }))}
                  className="flex-1 px-2 py-1 rounded-lg text-sm border"
                  style={{ borderColor: '#d0dce0', color: '#2c3e42', backgroundColor: 'white' }}
                />
                <button
                  onClick={saveBusinessHours}
                  disabled={saving}
                  className="px-3 py-1 rounded-lg text-xs text-white font-medium"
                  style={{ backgroundColor: '#4a9d68' }}
                >
                  儲存
                </button>
                <button
                  onClick={() => setEditingHours(false)}
                  className="px-3 py-1 rounded-lg text-xs font-medium"
                  style={{ backgroundColor: '#e8eef0', color: '#5a6b70' }}
                >
                  取消
                </button>
              </>
            ) : (
              <>
                <span className="text-sm flex-1" style={{ color: '#5a6b70' }}>
                  {state.business_hours.open} – {state.business_hours.close}
                </span>
                <button
                  onClick={() => {
                    setHoursInput({ open: state.business_hours.open, close: state.business_hours.close });
                    setEditingHours(true);
                  }}
                  className="text-xs px-2 py-0.5 rounded-lg"
                  style={{ backgroundColor: '#e8eef0', color: '#729DAD' }}
                >
                  編輯
                </button>
              </>
            )}
          </div>
        </div>

        {/* 售完 Banner */}
        {totalSoldOut > 0 && (
          <div
            className="mt-2 rounded-xl px-4 py-2.5 flex items-center justify-between"
            style={{ backgroundColor: '#fff4e6', border: '1px solid #f5c98a' }}
          >
            <div className="flex items-center gap-2">
              <AlertCircle size={15} color="#c49a30" />
              <span className="text-sm font-medium" style={{ color: '#8a6420' }}>
                {totalSoldOut} 項售完中
              </span>
            </div>
            <button
              onClick={resetAllSoldOut}
              disabled={saving}
              className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg active:scale-95"
              style={{ backgroundColor: '#c49a30', color: 'white', opacity: saving ? 0.6 : 1 }}
            >
              <RotateCcw size={12} />
              全部恢復
            </button>
          </div>
        )}
      </header>

      {/* ─── 主體 ─── */}
      <div className="max-w-2xl mx-auto px-4 pb-10">

        {/* 搜尋列 */}
        <div
          className="flex items-center gap-2 px-3 py-2.5 rounded-xl mb-3"
          style={{ backgroundColor: 'white', border: '1px solid #d0dce0' }}
        >
          <Search size={16} color="#8a9a9f" className="shrink-0" />
          <input
            type="text"
            placeholder="搜尋備料或品項名稱..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="flex-1 text-sm bg-transparent focus:outline-none"
            style={{ color: '#2c3e42' }}
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="text-xs shrink-0"
              style={{ color: '#8a9a9f' }}
            >
              清除
            </button>
          )}
        </div>

        {/* 分類 tabs（搜尋時隱藏）*/}
        {!isSearching && (
          <div
            className="mb-3 overflow-x-auto"
            style={{ scrollbarWidth: 'none' }}
          >
            <div className="flex gap-2 pb-1" style={{ width: 'max-content' }}>
              {categoryNames.map((catName) => {
                const isSelected = activeCategory === catName;
                const soldOut = getSoldOutCount(catName);
                return (
                  <button
                    key={catName}
                    onClick={() => setActiveCategory(catName)}
                    className="px-4 py-2 rounded-full text-sm font-medium whitespace-nowrap transition-colors"
                    style={{
                      backgroundColor: isSelected ? '#729DAD' : '#e8eef0',
                      color: isSelected ? 'white' : '#5a6b70',
                    }}
                  >
                    {catName}
                    {soldOut > 0 && (
                      <span
                        className="ml-1.5 text-xs px-1.5 py-0.5 rounded-full"
                        style={{
                          backgroundColor: isSelected ? 'rgba(255,255,255,0.3)' : '#fde8e8',
                          color: isSelected ? 'white' : '#c45c5c',
                        }}
                      >
                        {soldOut}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* 搜尋無結果 */}
        {isSearching && visibleCategories.length === 0 && (
          <div
            className="rounded-2xl p-8 text-center"
            style={{ backgroundColor: 'white', border: '1px solid #d0dce0' }}
          >
            <Search size={32} color="#d0dce0" className="mx-auto mb-2" />
            <p style={{ color: '#8a9a9f' }}>找不到「{searchQuery}」</p>
          </div>
        )}

        {/* 品項列表 */}
        <div className="space-y-3">
          {visibleCategories.map((cat) => {
            const soldOutInCat = getSoldOutCount(cat.name);
            const totalInCat = cat.items.length;
            const relatedKeys = CATEGORY_RELATED_CONTROLS[cat.name] ?? [];
            const relatedControls = CATEGORY_CONTROLS.filter((c) => relatedKeys.includes(c.key));
            // 品項售完狀態
            const anyItemsSoldOut = cat.items.some((i) => state.sold_out_items.includes(i.name));

            return (
              <section
                key={cat.name}
                className="rounded-2xl overflow-hidden"
                style={{ backgroundColor: 'white', border: '1px solid #d0dce0' }}
              >
                {/* 分類標題 */}
                <div
                  className="px-4 py-3 flex items-center gap-2"
                  style={{ borderBottom: '1px solid #f0f4f5', backgroundColor: '#fafcfd' }}
                >
                  <span className="font-semibold text-sm flex-1" style={{ color: '#2c3e42' }}>
                    {cat.name}
                  </span>
                  {soldOutInCat > 0 && (
                    <span className="text-xs font-medium" style={{ color: '#c45c5c' }}>
                      {soldOutInCat} / {totalInCat} 售完
                    </span>
                  )}
                  <button
                    onClick={() => toggleAllItems(cat.items, !anyItemsSoldOut)}
                    className="text-xs px-2.5 py-1 rounded-full active:scale-95 transition-transform"
                    style={anyItemsSoldOut
                      ? { backgroundColor: '#dcf0e4', color: '#4a9d68' }
                      : { backgroundColor: '#fde8e8', color: '#c45c5c' }
                    }
                  >
                    {anyItemsSoldOut ? '全部恢復' : '全部售完'}
                  </button>
                </div>

                {/* 備料 & 選項 chips（有對應備料才顯示）*/}
                {relatedControls.length > 0 && (
                  <div
                    className="px-4 py-3 flex flex-wrap items-center gap-2"
                    style={{ borderBottom: '1px solid #f0f4f5', backgroundColor: '#fbfcfd' }}
                  >
                    {relatedControls.map((ctrl) => {
                      const isSoldOut = state.sold_out_categories[ctrl.key] ?? false;
                      return (
                        <OptionChip
                          key={ctrl.key}
                          label={ctrl.label}
                          isSoldOut={isSoldOut}
                          onToggle={() => toggleCategory(ctrl.key, isSoldOut)}
                        />
                      );
                    })}
                  </div>
                )}

                {/* 品項列表 */}
                <div className="divide-y" style={{ borderColor: '#f0f4f5' }}>
                  {cat.items.map((item) => {
                    const isManualSoldOut = state.sold_out_items.includes(item.name);
                    const isEffectiveSoldOut = state.effective_sold_out.includes(item.name);

                    return (
                      <div
                        key={item.name}
                        className="flex items-center px-4 py-2.5 gap-3"
                        style={{
                          backgroundColor: isEffectiveSoldOut ? '#fefafa' : 'transparent',
                        }}
                      >
                        {/* 品項名稱 + 價格（inline）*/}
                        <div className="flex-1 min-w-0 flex items-baseline gap-1.5">
                          <span
                            className="text-sm font-medium"
                            style={{
                              color: isEffectiveSoldOut ? '#b0b8bc' : '#2c3e42',
                              textDecoration: isManualSoldOut ? 'line-through' : 'none',
                            }}
                          >
                            {item.name}
                          </span>
                          {item.price > 0 && (
                            <span
                              className="text-xs shrink-0"
                              style={{ color: isEffectiveSoldOut ? '#c8d0d4' : '#8fb3c0' }}
                            >
                              ${item.price}
                            </span>
                          )}
                        </div>

                        {/* 連動售完提示（非手動但被連動到）*/}
                        {isEffectiveSoldOut && !isManualSoldOut && (
                          <span className="text-xs shrink-0" style={{ color: '#c45c5c' }}>
                            連動
                          </span>
                        )}

                        <ToggleSwitch
                          checked={!isManualSoldOut}
                          onChange={() => toggleItem(item.name, isManualSoldOut)}
                        />
                      </div>
                    );
                  })}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}
