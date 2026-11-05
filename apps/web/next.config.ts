import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // API requests go to NEXT_PUBLIC_API_URL in development, or to the
  // server-side proxy at /backend in production (which keeps the API key out of
  // the browser bundle). No rewrites are needed.
};

export default nextConfig;