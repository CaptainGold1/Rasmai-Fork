import type { NextConfig } from "next";

// next dev evaluates code at runtime; the production build never does, so eval is only allowed there
const dev = process.env.NODE_ENV !== "production";

const CSP = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""} https://challenges.cloudflare.com https://static.cloudflareinsights.com`,
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self'",
  "img-src 'self' data: https://cdn.discordapp.com",
  "connect-src 'self' https://challenges.cloudflare.com https://cloudflareinsights.com",
  "frame-src https://challenges.cloudflare.com",
  "worker-src 'self'",
  "manifest-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'none'",
  "form-action 'self' https://discord.com",
].join("; ");

const secure = (process.env.MAIMAI_PUBLIC_URL ?? "https://rasmai.nguyen.ink").startsWith("https://");

const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "Content-Security-Policy", value: CSP },
  ...(secure ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }] : []),
];

// stamped into the client at build time: the service worker is registered under it, so every deploy is a new worker
const buildId = (process.env.GITHUB_SHA ?? "").slice(0, 10) || String(Date.now());

const nextConfig: NextConfig = {
  env: { NEXT_PUBLIC_BUILD_ID: buildId },
  output: "standalone",
  trailingSlash: true,
  skipTrailingSlashRedirect: true,
  poweredByHeader: false,
  images: { unoptimized: true },
  // www goes to the bare domain with the path intact. The host is read off the request rather than
  // named here, so this follows the domain wherever it moves and stays out of the way in development.
  async redirects() {
    return [
      {
        source: "/:path*",
        has: [{ type: "host", value: "www\.(?<bare>.+)" }],
        destination: "https://:bare/:path*",
        statusCode: 301,
      },
    ];
  },
  async headers() {
    return [
      { source: "/:path*", headers: SECURITY_HEADERS },
      // the browser must see a new service worker as soon as one is deployed
      { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache, max-age=0, must-revalidate" }] },
      { source: "/manifest.webmanifest", headers: [{ key: "Cache-Control", value: "public, max-age=3600" }] },
      // the sign-in script is the one thing SEGA's gateway page may load from here
      { source: "/:path((?!api/login\\.js$).*)", headers: [{ key: "Cross-Origin-Resource-Policy", value: "same-origin" }] },
    ];
  },
};

export default nextConfig;
