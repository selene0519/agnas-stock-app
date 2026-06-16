import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'MONE / AGNAS Stock App',
  description: '국장·미장 의사결정 운용 보드 · 장전·장중·장마감 기준 실전 운용',
  icons: {
    icon: '/favicon.png',
    apple: '/brand/mone-logo-192.png',
  },
  manifest: '/manifest.json',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'MONE',
  },
  themeColor: '#0a0f1a',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="MONE" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="manifest" href="/manifest.json" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              if ('serviceWorker' in navigator) {
                window.addEventListener('load', function() {
                  navigator.serviceWorker.register('/sw.js').catch(function() {});
                });
              }
            `,
          }}
        />
      </head>
      <body suppressHydrationWarning>
        {/* JS 로드 전 인라인 스플래시 — React 마운트 시 자동 제거 */}
        <div
          id="mone-html-splash"
          style={{
            position: "fixed", inset: 0, zIndex: 99999,
            background: "#0b1220",
            display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center",
            fontFamily: "system-ui, sans-serif",
          }}
        >
          <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse 90% 45% at 50% 0%, rgba(20,180,175,0.18), transparent)", pointerEvents: "none" }} />
          <img src="/loading/mone-logo.png" alt="" style={{ width: "min(52vw, 200px)", objectFit: "contain", filter: "drop-shadow(0 0 28px rgba(66,223,212,0.28))" }} />
          <p style={{ marginTop: 4, letterSpacing: "0.35em", color: "#fff", fontWeight: 300, fontSize: "clamp(22px,7vw,32px)", textShadow: "0 0 18px rgba(66,223,212,0.25)" }}>MONE</p>
          <p style={{ marginTop: 4, letterSpacing: "0.25em", color: "rgba(61,216,208,0.6)", fontWeight: 300, fontSize: "clamp(7px,2vw,9px)" }}>WHERE MOMENTUM BEGINS.</p>
        </div>
        {/* React가 마운트되면 page.tsx에서 제거 (removeHtmlSplash()) */}
        {children}
      </body>
    </html>
  );
}
