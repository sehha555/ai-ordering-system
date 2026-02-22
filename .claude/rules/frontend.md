---
paths:
  - "src/frontend_next/**"
---

# Frontend 開發規則

- Framework: Next.js 16 App Router + React 19
- State: Zustand 5（`store/useStore.ts`）
- Styling: Tailwind v4（品牌色定義在 CSS variables）
- Animation: Framer Motion 12
- 所有 API 呼叫透過 Next.js rewrites proxy 到 backend（不直接打 :8000）
