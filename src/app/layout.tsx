import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: '电商低价监控系统',
  description: 'E-commerce Price Monitor',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-gray-50">{children}</body>
    </html>
  )
}
