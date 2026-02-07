'use client';

import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MenuCategory } from '../types';

export default function MenuDisplay() {
  const [categories, setCategories] = useState<MenuCategory[]>([]);
  const [expandedCat, setExpandedCat] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [useImage, setUseImage] = useState(false);

  useEffect(() => {
    fetch('/api/menu')
      .then((res) => res.json())
      .then((data) => {
        if (data.categories && data.categories.length > 0) {
          setCategories(data.categories);
          // Expand first category by default
          setExpandedCat(data.categories[0].name);
        } else {
          setUseImage(true);
        }
        setLoading(false);
      })
      .catch(() => {
        setUseImage(true);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full" style={{ color: '#5a6b70' }}>
        <p className="text-lg">載入菜單中...</p>
      </div>
    );
  }

  if (useImage) {
    return (
      <div className="flex items-center justify-center h-full p-4">
        <img
          src="/static/menu.png"
          alt="菜單"
          className="max-w-full max-h-full object-contain rounded-lg"
          style={{ boxShadow: '0 4px 16px rgba(114, 157, 173, 0.1)' }}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Menu toggle */}
      <div className="flex items-center justify-between px-4 pt-2 pb-1">
        <h2 className="text-lg font-semibold" style={{ color: '#729DAD' }}>菜單</h2>
        <button
          onClick={() => setUseImage(true)}
          className="text-xs px-3 py-1 rounded-full transition-colors"
          style={{ backgroundColor: '#e8eef0', color: '#5a6b70' }}
        >
          圖片模式
        </button>
      </div>

      {/* Categories accordion */}
      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-2">
        {categories.map((cat) => {
          const isExpanded = expandedCat === cat.name;
          return (
            <div
              key={cat.name}
              className="rounded-xl overflow-hidden"
              style={{
                backgroundColor: 'white',
                border: '1px solid #d0dce0',
                boxShadow: '0 2px 8px rgba(114, 157, 173, 0.08)',
              }}
            >
              {/* Category header */}
              <button
                onClick={() => setExpandedCat(isExpanded ? null : cat.name)}
                className="w-full flex items-center justify-between px-4 py-3 transition-colors"
                style={{
                  backgroundColor: isExpanded ? '#e8eef0' : 'transparent',
                  borderBottom: isExpanded ? '1px solid #d0dce0' : 'none',
                }}
              >
                <div className="flex items-center gap-2.5">
                  <span className="text-xl">{cat.icon}</span>
                  <span className="font-semibold" style={{ color: '#2c3e42' }}>{cat.name}</span>
                  <span
                    className="text-xs px-2 py-0.5 rounded-full"
                    style={{ backgroundColor: '#e8eef0', color: '#5a6b70' }}
                  >
                    {cat.items.length}
                  </span>
                </div>
                <span
                  className="text-sm transition-transform"
                  style={{
                    color: '#8a9a9f',
                    transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                  }}
                >
                  ▼
                </span>
              </button>

              {/* Items list */}
              <AnimatePresence>
                {isExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden"
                  >
                    <div className="p-2">
                      {cat.items.map((item) => (
                        <div
                          key={item.name}
                          className="flex justify-between items-center px-3 py-2.5 rounded-lg transition-colors"
                          style={{ cursor: 'default' }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.backgroundColor = 'rgba(114, 157, 173, 0.1)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.backgroundColor = 'transparent';
                          }}
                        >
                          <span style={{ color: '#2c3e42' }}>{item.name}</span>
                          <span className="font-semibold" style={{ color: '#729DAD' }}>
                            ${item.price}
                          </span>
                        </div>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}
