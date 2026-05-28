'use client'

import './globals.css'
import { AuthProvider, useAuth } from '@/lib/auth-context'
import { useRouter, usePathname } from 'next/navigation'
import { useEffect, useCallback, useState } from 'react'
import { apiFetch } from '@/lib/utils'

function HealthBanner() {
  const { isAuthenticated } = useAuth()
  const pathname = usePathname()
  const [issues, setIssues] = useState<string[]>([])
  const [show, setShow] = useState(false)
  const router = useRouter()

  const fetchHealth = useCallback(async () => {
    try {
      const data = await apiFetch('/api/diagnostics/health')
      if (data.overall !== 'ok' && data.issues?.length > 0) {
        setIssues(data.issues)
        setShow(true)
      }
    } catch {
      // ignore if health fails
    }
  }, [])

  useEffect(() => {
    if (isAuthenticated && pathname !== '/login' && pathname !== '/admin/diagnostics') {
      fetchHealth()
      const interval = setInterval(fetchHealth, 60000)
      return () => clearInterval(interval)
    }
  }, [isAuthenticated, pathname, fetchHealth])

  if (!show || issues.length === 0) return null

  return (
    <div className="bg-amber-50 border-b border-amber-200">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-2.5">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-amber-800">⚠ 系统异常</span>
          <span className="text-xs text-amber-600">{issues.join('；')}</span>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => router.push('/admin/diagnostics')}
            className="rounded bg-amber-600 px-3 py-1 text-xs text-white hover:bg-amber-700"
          >
            一键排查
          </button>
          <button
            onClick={() => setShow(false)}
            className="text-xs text-amber-500 hover:text-amber-700"
          >
            忽略
          </button>
        </div>
      </div>
    </div>
  )
}

function TopBar() {
  const { user, isAuthenticated, logout } = useAuth()
  const router = useRouter()
  const pathname = usePathname()

  if (!isAuthenticated || !user) {
    return null
  }

  const roleLabels: Record<string, string> = {
    admin: '管理员',
    manager: '主管',
    staff: '员工',
  }

  const navItems = [
    { label: '预警管理', href: '/admin/alerts' },
    { label: '关键词监控', href: '/admin/keywords' },
    { label: '商品关联', href: '/admin/product-keywords' },
    { label: '用户管理', href: '/admin/users' },
    { label: '系统设置', href: '/admin/settings' },
    { label: '故障排查', href: '/admin/diagnostics' },
  ]

  return (
    <div className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-2.5">
        <div className="flex items-center gap-4">
          <span className="text-sm font-semibold text-gray-900">电商低价监控系统</span>
          {navItems.map((item) => (
            <button
              key={item.href}
              onClick={() => router.push(item.href)}
              className={`text-sm transition-colors whitespace-nowrap ${
                pathname.startsWith(item.href)
                  ? 'text-blue-600 font-medium'
                  : 'text-gray-600 hover:text-blue-600'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-sm">
            <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-blue-100 text-xs font-medium text-blue-700">
              {user.username.charAt(0).toUpperCase()}
            </span>
            <span className="text-gray-700">{user.username}</span>
            <span className={cn(
              'rounded-full px-2 py-0.5 text-xs font-medium',
              user.role === 'admin' ? 'bg-red-100 text-red-700' :
              user.role === 'manager' ? 'bg-yellow-100 text-yellow-700' :
              'bg-green-100 text-green-700'
            )}>
              {roleLabels[user.role] || user.role}
            </span>
          </div>
          <button
            onClick={logout}
            className="text-sm text-gray-500 hover:text-red-600 transition-colors"
          >
            退出
          </button>
        </div>
      </div>
    </div>
  )
}

function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (!isLoading && !isAuthenticated && pathname !== '/login') {
      router.push('/login')
    }
  }, [isLoading, isAuthenticated, pathname, router])

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-gray-400">加载中...</p>
      </div>
    )
  }

  if (!isAuthenticated && pathname !== '/login') {
    return null
  }

  return <>{children}</>
}

function cn(...args: (string | undefined | false)[]) {
  return args.filter(Boolean).join(' ')
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-gray-50">
        <AuthProvider>
          <TopBar />
          <HealthBanner />
          <AuthGuard>
            {children}
          </AuthGuard>
        </AuthProvider>
      </body>
    </html>
  )
}
