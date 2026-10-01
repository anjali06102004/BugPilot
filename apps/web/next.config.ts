import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    return [
      { source: "/backend/:path*", destination: `${api}/:path*` },
      { source: "/evidence/:path*", destination: `${api}/evidence/:path*` },
    ];
  },
};

export default nextConfig;
