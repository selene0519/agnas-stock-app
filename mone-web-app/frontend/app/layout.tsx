import type { Metadata, Viewport } from 'next';
import localFont from 'next/font/local';
import './globals.css';

const suit = localFont({
  src: './fonts/SUIT-Variable.woff2',
  variable: '--font-suit',
  weight: '100 900',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'MONE / AGNAS Stock App',
  description: '국장·미장 의사결정 운용 보드 · 장전·장중·장마감 기준 실전 운용',
  icons: {
    icon: '/favicon.png',
    apple: '/icons/apple-touch-logo-v2.png?v=3',
  },
  manifest: '/manifest.json',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'MONE',
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#0b1220',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className={suit.variable} suppressHydrationWarning>
      <head>
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="MONE" />
        <link rel="apple-touch-icon" href="/icons/apple-touch-logo-v2.png?v=3" />
        <link rel="manifest" href="/manifest.json" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              if ('serviceWorker' in navigator) {
                window.addEventListener('load', function() {
                  var refreshed = false;
                  navigator.serviceWorker.addEventListener('controllerchange', function() {
                    if (refreshed) return;
                    refreshed = true;
                    window.location.reload();
                  });
                  navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' }).then(function(registration) {
                    registration.update().catch(function() {});
                    if (registration.waiting) {
                      registration.waiting.postMessage({ type: 'SKIP_WAITING' });
                    }
                    registration.addEventListener('updatefound', function() {
                      var worker = registration.installing;
                      if (!worker) return;
                      worker.addEventListener('statechange', function() {
                        if (worker.state === 'installed' && navigator.serviceWorker.controller) {
                          worker.postMessage({ type: 'SKIP_WAITING' });
                        }
                      });
                    });
                  }).catch(function() {});
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
          aria-hidden="true"
          style={{
            position: "fixed", inset: 0, zIndex: 99999,
            background: "#0b1220",
            display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center",
            fontFamily: "system-ui, sans-serif",
          }}
        >
          <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse 90% 45% at 50% 0%, rgba(20,180,175,0.18), transparent)", pointerEvents: "none" }} />
          {/* A raw image keeps the pre-React launch mark available without waiting for Next.js hydration. */}
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/icons/splash-logo-v2-512.png?v=3"
            alt=""
            width={96}
            height={96}
            style={{
              display: "block",
              width: "min(28vw, 96px)",
              height: "auto",
              objectFit: "contain",
              background: "transparent",
              filter: "drop-shadow(0 0 28px rgba(66,223,212,0.28))",
            }}
          />
        </div>
        {/* React가 마운트되면 page.tsx에서 제거 (removeHtmlSplash()) */}
        {children}
      </body>
    </html>
  );
}
