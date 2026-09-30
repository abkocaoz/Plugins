/** @type {import('next').NextConfig} */
// BACKEND_URL is resolved at build time (Docker build arg); defaults to local dev.
const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";

const nextConfig = {
  output: "standalone",
  // The vendored ai-elements/shadcn components have type mismatches upstream
  // (the example is only run via `next dev`, which skips type checking).
  typescript: { ignoreBuildErrors: true },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
