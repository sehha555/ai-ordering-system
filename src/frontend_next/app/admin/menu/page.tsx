'use client';

import { useState, useEffect, useCallback } from 'react';
import { Search, RotateCcw, Lock, Clock, Store, AlertCircle } from 'lucide-react';

// ───────────────────────────── 型別定義（admin-only）─────────────────────────────

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

const CATEGORY_GROUPS = ['載體', '米種', '饅頭', '鐵板麵', '其他'];

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

function SegmentControl({
  options,
  value,
  onChange,
}: {
  options: Array<{ label: string; value: boolean | null }>;
  value: boolean | null;
  onChange: (v: boolean | null) => void;
}) {
  return (
    <div
      className="flex rounded-xl p-0.5"
      style={{ backgroundColor: '#e8eef0' }}
    >
      {options.map((opt) => {
        const isActive = value === opt.value;
        return (
          <button
            key={String(opt.value)}
            onClick={() => onChange(opt.value)}
            className="flex-1 py-1.5 rounded-[10px] text-xs font-medium transition-all"
            style={{
              backgroundColor: isActive ? 'white' : 'transparent',
              color: isActive ? '#2c3e42' : '#5a6b70',
              boxShadow: isActive ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

// ───────────────────────────── 主元件 ─────────────────────────────

export default function AdminMenuPage() {
  const [state, setState] = useState<AdminMenuState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedCategory, setSelectedCategory] = useState<string>('全部');
  const [editingHours, setEditingHours] = useState(false);
  const [hoursInput, setHoursInput] = useState({ open: '', close: '' });
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

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

  useEffect(() => { fetchState(); }, [fetchState]);

  // ── 品項售完 toggle（樂觀更新）──
  const toggleItem = useCallback(async (itemName: string, currentSoldOut: boolean) => {
    if (!state) return;
    const newSoldOut = !currentSoldOut;
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
      await fetchState();
    } catch (e) {
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
      await fetchState();
    } catch (e) {
      console.error('更新分類售完狀態失敗:', e);
      setState((prev) => {
        if (!prev) return prev;
        return { ...prev, sold_out_categories: { ...prev.sold_out_categories, [key]: currentSoldOut } };
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

  // ── 計算每分類的售完數量 ──
  const getSoldOutCount = useCallback((catName: string): number => {
    if (!state) return 0;
    const cat = state.categories.find((c) => c.name === catName);
    if (!cat) return 0;
    return cat.items.filter((item) => state.effective_sold_out.includes(item.name)).length;
  }, [state]);

  // ── 總售完數量 ──
  const totalSoldOut = state
    ? state.sold_out_items.length + Object.values(state.sold_out_categories).filter(Boolean).length
    : 0;

  // ── 搜尋 + 分類過濾 ──
  const isSearching = searchQuery.trim().length > 0;
  const filteredCategories = state
    ? isSearching
      ? state.categories
          .map((cat) => ({
            ...cat,
            items: cat.items.filter((item) =>
              item.name.toLowerCase().includes(searchQuery.toLowerCase())
            ),
          }))
          .filter((cat) => cat.items.length > 0)
      : selectedCategory === '全部'
        ? state.categories
        : state.categories.filter((c) => c.name === selectedCategory)
    : [];

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

  const categoryNames = ['全部', ...state.categories.map((c) => c.name)];

  // ───────────────────────────── 渲染 ─────────────────────────────

  return (
    <div className="min-h-screen" style={{ backgroundColor: '#f4f7f8' }}>

      {/* ─── Sticky Header ─── */}
      <header
        className="sticky top-0 z-20 px-4 pt-4 pb-3"
        style={{ backgroundColor: '#f4f7f8' }}
      >
        <div
          className="rounded-2xl p-4"
          style={{
            background: 'linear-gradient(135deg, #ffffff 0%, #edf3f5 100%)',
            border: '1px solid #d0dce0',
            boxShadow: '0 2px 12px rgba(114, 157, 173, 0.12)',
          }}
        >
          {/* 第一列：店名 + 狀態 */}
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Store size={18} color="#729DAD" />
              <h1 className="text-lg font-bold" style={{ color: '#2c3e42' }}>
                菜單管理
              </h1>
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

          {/* 第二列：營業時間 */}
          <div className="flex items-center gap-2 mb-3">
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

          {/* 第三列：手動 override — iOS segment control */}
          <SegmentControl
            options={[
              { label: '自動', value: null },
              { label: '強制營業', value: true },
              { label: '強制休息', value: false },
            ]}
            value={state.is_open_override}
            onChange={setOpenOverride}
          />
        </div>

        {/* 售完 Banner（有售完才顯示）*/}
        {totalSoldOut > 0 && (
          <div
            className="mt-2 rounded-xl px-4 py-2.5 flex items-center justify-between"
            style={{ backgroundColor: '#fff4e6', border: '1px solid #f5c98a' }}
          >
            <div className="flex items-center gap-2">
              <AlertCircle size={15} color="#c49a30" />
              <span className="text-sm font-medium" style={{ color: '#8a6420' }}>
                {totalSoldOut} 項售完
              </span>
            </div>
            <button
              onClick={resetAllSoldOut}
              disabled={saving}
              className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg"
              style={{ backgroundColor: '#c49a30', color: 'white', opacity: saving ? 0.6 : 1 }}
            >
              <RotateCcw size={12} />
              全部恢復
            </button>
          </div>
        )}
      </header>

      {/* ─── 主體：響應式雙欄 ─── */}
      <div className="flex max-w-2xl mx-auto px-4 gap-4 pb-10">

        {/* ─── 左側分類欄（平板才顯示）─── */}
        <aside className="hidden md:block w-44 shrink-0 pt-4">
          <div
            className="rounded-2xl overflow-hidden sticky top-44"
            style={{ backgroundColor: 'white', border: '1px solid #d0dce0' }}
          >
            {categoryNames.map((catName) => {
              const isSelected = !isSearching && selectedCategory === catName;
              const soldOut = catName !== '全部' ? getSoldOutCount(catName) : 0;
              return (
                <button
                  key={catName}
                  onClick={() => { setSelectedCategory(catName); setSearchQuery(''); }}
                  className="w-full flex items-center justify-between px-3 py-2.5 text-sm transition-colors"
                  style={{
                    backgroundColor: isSelected ? 'rgba(114,157,173,0.1)' : 'transparent',
                    color: isSelected ? '#729DAD' : '#3a4d52',
                    fontWeight: isSelected ? 600 : 400,
                    borderLeft: isSelected ? '3px solid #729DAD' : '3px solid transparent',
                  }}
                >
                  <span className="truncate">{catName}</span>
                  {soldOut > 0 && (
                    <span
                      className="ml-1 text-xs px-1.5 py-0.5 rounded-full shrink-0"
                      style={{ backgroundColor: '#fde8e8', color: '#c45c5c' }}
                    >
                      {soldOut}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </aside>

        {/* ─── 右側主內容 ─── */}
        <div className="flex-1 min-w-0 pt-4">

          {/* 搜尋列 */}
          <div
            className="flex items-center gap-2 px-3 py-2.5 rounded-xl mb-3"
            style={{ backgroundColor: 'white', border: '1px solid #d0dce0' }}
          >
            <Search size={16} color="#8a9a9f" className="shrink-0" />
            <input
              type="text"
              placeholder="搜尋品項名稱..."
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

          {/* 分類控制 Chip 區 */}
          <div
            className="rounded-2xl p-4 mb-3"
            style={{ backgroundColor: 'white', border: '1px solid #d0dce0' }}
          >
            <p className="text-xs font-semibold mb-3" style={{ color: '#729DAD' }}>
              選項控制
            </p>
            <div className="space-y-3">
              {CATEGORY_GROUPS.map((group) => {
                const controls = CATEGORY_CONTROLS.filter((c) => c.group === group);
                return (
                  <div key={group}>
                    <p className="text-xs mb-1.5" style={{ color: '#8a9a9f' }}>{group}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {controls.map(({ key, label }) => {
                        const isSoldOut = state.sold_out_categories[key] ?? false;
                        return (
                          <button
                            key={key}
                            onClick={() => toggleCategory(key, isSoldOut)}
                            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors"
                            style={{
                              backgroundColor: isSoldOut ? '#fde8e8' : '#dcf0e4',
                              color: isSoldOut ? '#c45c5c' : '#4a9d68',
                            }}
                          >
                            <span
                              className="inline-block w-1.5 h-1.5 rounded-full"
                              style={{ backgroundColor: isSoldOut ? '#c45c5c' : '#4a9d68' }}
                            />
                            {label}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 分類 tabs（手機才顯示）*/}
          {!isSearching && (
            <div className="md:hidden -mx-0 mb-3 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
              <div className="flex gap-2 pb-1" style={{ width: 'max-content' }}>
                {categoryNames.map((catName) => {
                  const isSelected = selectedCategory === catName;
                  const soldOut = catName !== '全部' ? getSoldOutCount(catName) : 0;
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

          {/* 品項列表 */}
          {isSearching && filteredCategories.length === 0 ? (
            <div
              className="rounded-2xl p-8 text-center"
              style={{ backgroundColor: 'white', border: '1px solid #d0dce0' }}
            >
              <Search size={32} color="#d0dce0" className="mx-auto mb-2" />
              <p style={{ color: '#8a9a9f' }}>找不到「{searchQuery}」</p>
            </div>
          ) : (
            <div className="space-y-3">
              {filteredCategories.map((cat) => {
                const soldOutInCat = getSoldOutCount(cat.name);
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
                      <span className="text-base">{cat.icon}</span>
                      <span className="font-semibold text-sm flex-1" style={{ color: '#2c3e42' }}>
                        {cat.name}
                      </span>
                      <span className="text-xs" style={{ color: '#8a9a9f' }}>
                        {cat.items.length} 項
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
                        const comboMatch = Object.entries(state.combo_status).find(
                          ([key]) => item.name.startsWith(key)
                        );
                        const comboEntry = comboMatch
                          ? (comboMatch[1] as ComboStatusEntry)
                          : undefined;
                        const isComboLocked = comboEntry !== undefined && !comboEntry.available;
                        const isManualSoldOut = state.sold_out_items.includes(item.name);
                        const isEffectiveSoldOut = state.effective_sold_out.includes(item.name);

                        return (
                          <div
                            key={item.name}
                            className="flex items-center px-4 py-3 gap-3 transition-opacity"
                            style={{ opacity: isEffectiveSoldOut ? 0.45 : 1 }}
                          >
                            {/* 品項資訊 */}
                            <div className="flex-1 min-w-0">
                              <p
                                className="text-sm"
                                style={{ color: '#2c3e42' }}
                              >
                                {item.name}
                              </p>
                              {isComboLocked && comboEntry?.reason && (
                                <p className="text-xs mt-0.5 flex items-center gap-1" style={{ color: '#c45c5c' }}>
                                  <Lock size={10} />
                                  {comboEntry.reason}
                                </p>
                              )}
                              {item.price > 0 && (
                                <p className="text-xs mt-0.5 font-medium" style={{ color: '#729DAD' }}>
                                  ${item.price}
                                </p>
                              )}
                            </div>

                            {/* Toggle 或鎖定 */}
                            {isComboLocked ? (
                              <div
                                className="w-8 h-8 rounded-xl flex items-center justify-center"
                                style={{ backgroundColor: '#fde8e8' }}
                                title={comboEntry?.reason ?? '連動鎖定'}
                              >
                                <Lock size={14} color="#c45c5c" />
                              </div>
                            ) : (
                              <ToggleSwitch
                                checked={!isManualSoldOut}
                                onChange={() => toggleItem(item.name, isManualSoldOut)}
                              />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </section>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
