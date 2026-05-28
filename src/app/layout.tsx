'use client'

import './globals.css'
import { AuthProvider, useAuth } from '@/lib/auth-context'
import { useRouter, usePathname } from 'next/navigation'
import { useEffect, useCallback, useState, useRef } from 'react'
import { apiFetch } from '@/lib/utils'

function NotificationBell() {
  const { isAuthenticated } = useAuth()
  const pathname = usePathname()
  const router = useRouter()
  const [count, setCount] = useState(0)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const fetchCount = useCallback(async () => {
    if (!isAuthenticated) return
    try {
      const data = await apiFetch('/api/notifications/count')
      setCount(data.unread_alerts || 0)
    } catch { /* ignore */ }
  }, [isAuthenticated])

  useEffect(() => {
    fetchCount()
    const interval = setInterval(fetchCount, 15000)
    return () => clearInterval(interval)
  }, [fetchCount])

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  if (!isAuthenticated || pathname === '/login') return null

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative p-1 text-gray-500 hover:text-gray-700 transition-colors"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {count > 0 && (
          <span className="absolute -top-0.5 -right-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-2 w-72 rounded-lg border border-gray-200 bg-white shadow-lg z-50">
          <div className="border-b border-gray-100 px-4 py-3">
            <span className="text-sm font-semibold text-gray-700">站内通知</span>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {count === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-gray-400">
                暂无新通知
              </div>
            ) : (
              <div className="px-4 py-4">
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 inline-flex h-2 w-2 rounded-full bg-red-500 flex-shrink-0" />
                  <div>
                    <p className="text-sm text-gray-700">
                      您有 <span className="font-semibold text-red-600">{count}</span> 条未处理预警
                    </p>
                    <button
                      onClick={() => { router.push('/admin/alerts'); setOpen(false) }}
                      className="mt-2 text-xs text-blue-600 hover:text-blue-800"
                    >
                      查看预警 →
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

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
    } catch { /* ignore */ }
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
    { label: '操作日志', href: '/admin/logs' },
    { label: '系统设置', href: '/admin/settings' },
    { label: '故障排查', href: '/admin/diagnostics' },
  ]

  return (
    <div className="border-b border-gray-200 bg-white">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-2.5">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push('/')}
            className="text-sm font-semibold text-gray-900 hover:text-blue-600"
          >
            电商低价监控系统
          </button>
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
          <NotificationBell />
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
