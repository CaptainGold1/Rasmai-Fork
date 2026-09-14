import { env } from "@/lib/env";
import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import { Pwa } from "@/components/Pwa";
import { THEME_BOOT } from "@/components/Theme";

const display = localFont({
  src: [
    { path: "./fonts/ZenMaruGothic-700.woff2", weight: "700" },
    { path: "./fonts/ZenMaruGothic-900.woff2", weight: "900" },
  ],
  variable: "--font-display",
  display: "swap",
});
const body = localFont({
  src: [
    { path: "./fonts/ZenKakuGothicNew-400.woff2", weight: "400" },
    { path: "./fonts/ZenKakuGothicNew-500.woff2", weight: "500" },
    { path: "./fonts/ZenKakuGothicNew-700.woff2", weight: "700" },
  ],
  variable: "--font-body",
  display: "swap",
});
const mono = localFont({
  src: [
    { path: "./fonts/JetBrainsMono-500.woff2", weight: "500" },
    { path: "./fonts/JetBrainsMono-700.woff2", weight: "700" },
  ],
  variable: "--font-mono",
  display: "swap",
});

const SITE = env.publicUrl();
const TAGLINE =
  "Rasmai reads your maimai DX NET scores and tells you which charts to play next for the most rating, with the odds on each.";

export const metadata: Metadata = {
  // every page's canonical is resolved against this, so one address is the address
  metadataBase: new URL(SITE),
  title: { default: "Rasmai · know what to play next", template: "%s · Rasmai" },
  description: TAGLINE,
  alternates: { canonical: "/" },
  keywords: ["maimai", "maimai DX", "rating", "best 50", "Discord bot", "chart constant", "rhythm game"],
  openGraph: {
    type: "website",
    siteName: "Rasmai",
    url: SITE,
    title: "Rasmai · know what to play next",
    description: TAGLINE,
    locale: "en",
  },
  twitter: { card: "summary_large_image", title: "Rasmai · know what to play next", description: TAGLINE },
  applicationName: "Rasmai",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Rasmai", statusBarStyle: "default" },
  icons: { icon: "/favicon.ico", apple: "/app/apple-touch-icon.png" },
  formatDetection: { telephone: false },
  // Next writes the standard mobile-web-app-capable tag; older iOS only reads Apple's own
  other: { "apple-mobile-web-app-capable": "yes" },
};

export const viewport: Viewport = {
  colorScheme: "light",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  // the theme-color meta is written by the theme boot script, so it follows the reader's switch rather than the device
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        {children}
        <Pwa />
      </body>
    </html>
  );
}
