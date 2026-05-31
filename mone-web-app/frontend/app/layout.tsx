import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'MONE / AGNAS Stock App',
  description: '국장·미장 의사결정 운용 보드 · 장전·장중·장마감 기준 실전 운용',
  icons: { icon: '/favicon.ico' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
      </head>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}

