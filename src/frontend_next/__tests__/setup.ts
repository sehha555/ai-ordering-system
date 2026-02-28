import '@testing-library/jest-dom/vitest';

// jsdom 沒有 ResizeObserver，補 mock
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};
