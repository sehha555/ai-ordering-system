import type { NextConfig } from "next";

const apiBase = process.env.API_REWRITE_TARGET || 'http://127.0.0.1:8000';

const nextConfig: NextConfig = {
  output: "standalone",
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
    ];
  },
};

export default nextConfig;
