import path from "path";
import type { NextConfig } from "next";

const apiBase = process.env.API_REWRITE_TARGET || 'http://127.0.0.1:8000';

const nextConfig: NextConfig = {
  output: "standalone",
  // workspace root 固定為 repo 根目錄：layout/ChatPanel 跨目錄 import src/config/store_config.json 需要，
  // 也避免 Next 用 lockfile/node_modules 推斷 root 造成解析飄移
  turbopack: {
    root: path.resolve(__dirname, "../.."),
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${apiBase}/api/:path*`,
      },
      {
        source: '/healthz',
        destination: `${apiBase}/healthz`,
      },
      {
        source: '/readyz',
        destination: `${apiBase}/readyz`,
      },
      {
        source: '/cart/:path*',
        destination: `${apiBase}/cart/:path*`,
      },
      {
        source: '/static/:path*',
        destination: `${apiBase}/static/:path*`,
      },
      {
        source: '/admin/:path*',
        destination: `${apiBase}/admin/:path*`,
      },
    ];
  },
};

export default nextConfig;
