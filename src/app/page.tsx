'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useRouter } from 'next/navigation'
import { useEffect, useState, useCallback } from 'react'

interface Metrics {
  total_alerts: number
  today_alerts: number
  monitored_products: number
  total_products: number
  keyword_count: number
  today_crawled: number
  crawl_success_rate: number
}

interface TrendPoint {
  date: string
  count: number
}

interface RecentAlert {
  id: number
  product_id: string
  alert_type: string
  message: string
  is_read: boolean
  product_title: string
  created_at: string | null
}

interface DashboardData {
  metrics: Metrics
  alert_trend: TrendPoint[]
  crawl_trend: TrendPoint[]
  recent_alerts: RecentAlert[]
  error?: string
}

export default function Home() {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    try {
      const result = await apiFetch('/api/dashboard/summary')
      setData(result)
    } catch (err: any) {
      setError(err.message || '加载失败')
    }
  }, [])

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      return
    }
    if (isAuthenticated) {
      fetchData()
      const interval = setInterval(fetchData, 30000)
      return () => clearInterval(interval)
    }
  }, [isLoading, isAuthenticated, fetchData])

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-gray-400">加载中...</p>
      </div>
    )
  }

  if (!isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-center space-y-6">
          <h1 className="text-3xl font-bold text-gray-900">电商低价监控系统</h1>
          <p className="text-gray-500">E-commerce Price Monitor Dashboard</p>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-gray-400">{error || '加载中...'}</p>
      </div>
    )
  }

  const m = data.metrics
  const todayStr = new Date().toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })

  const maxAlertCount = Math.max(1, ...data.alert_trend.map((p: TrendPoint) => p.count))
  const maxCrawlCount = Math.max(1, ...data.crawl_trend.map((p: TrendPoint) => p.count))

  const cards = [
    {
      label: '今日预警',
      value: m.today_alerts,
      sub: `总计 ${m.total_alerts}`,
      color: 'border-l-orange-400',
      bg: 'bg-orange-50',
      icon: '🔔',
    },
    {
      label: `今日抓取 (${todayStr})`,
      value: m.today_crawled,
      sub: '个商品',
      color: 'border-l-blue-400',
      bg: 'bg-blue-50',
      icon: '📥',
    },
    {
      label: '监控中',
      value: m.monitored_products,
      sub: `${m.keyword_count} 个关键词`,
      color: 'border-l-green-400',
      bg: 'bg-green-50',
      icon: '📊',
    },
    {
      label: '抓取成功率',
      value: `${m.crawl_success_rate}%`,
      sub: m.today_crawled > 0 ? '今日正常' : '今日无数据',
      color: m.today_crawled > 0 ? 'border-l-emerald-400' : 'border-l-gray-400',
      bg: m.today_crawled > 0 ? 'bg-emerald-50' : 'bg-gray-50',
      icon: m.today_crawled > 0 ? '✅' : '⏳',
    },
  ]

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">数据概览</h1>
          <p className="mt-1 text-sm text-gray-500">电商低价监控系统运行状态</p>
        </div>

        {data.error && (
          <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {data.error}
          </div>
        )}

        <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {cards.map((card) => (
            <div
              key={card.label}
              className={`rounded-lg border border-gray-200 bg-white border-l-4 ${card.color} p-5`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-gray-500">{card.label}</span>
                <span className="text-lg">{card.icon}</span>
              </div>
              <div className="mt-2 text-3xl font-bold text-gray-900">{card.value}</div>
              <div className="mt-1 text-xs text-gray-400">{card.sub}</div>
            </div>
          ))}
        </div>

        <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <h2 className="mb-4 text-sm font-semibold text-gray-700">近 7 天预警趋势</h2>
            <div className="flex items-end gap-1 h-40">
              {data.alert_trend.map((point: TrendPoint, i: number) => {
                const height = Math.max(4, (point.count / maxAlertCount) * 100)
                const d = new Date(point.date + 'T00:00:00')
                const label = `${d.getMonth() + 1}/${d.getDate()}`
                return (
                  <div key={i} className="flex-1 flex flex-col items-center gap-1">
                    <span className="text-xs text-gray-500">{point.count}</span>
                    <div className="w-full flex flex-col justify-end" style={{ height: 128 }}>
                      <div
                        className="w-full rounded-t bg-orange-400 transition-all"
                        style={{ height: `${height}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-gray-400">{label}</span>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <h2 className="mb-4 text-sm font-semibold text-gray-700">近 7 天抓取商品数</h2>
            <div className="flex items-end gap-1 h-40">
              {data.crawl_trend.map((point: TrendPoint, i: number) => {
                const height = Math.max(4, (point.count / maxCrawlCount) * 100)
                const d = new Date(point.date + 'T00:00:00')
                const label = `${d.getMonth() + 1}/${d.getDate()}`
                return (
                  <div key={i} className="flex-1 flex flex-col items-center gap-1">
                    <span className="text-xs text-gray-500">{point.count}</span>
                    <div className="w-full flex flex-col justify-end" style={{ height: 128 }}>
                      <div
                        className="w-full rounded-t bg-blue-400 transition-all"
                        style={{ height: `${height}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-gray-400">{label}</span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
            <h2 className="text-sm font-semibold text-gray-700">最近预警</h2>
            <button
              onClick={() => router.push('/admin/alerts')}
              className="text-xs text-blue-600 hover:text-blue-800"
            >
              查看全部 →
            </button>
          </div>
          <div className="divide-y divide-gray-100">
            {data.recent_alerts.length === 0 ? (
              <div className="px-5 py-12 text-center text-sm text-gray-400">
                暂无预警记录
              </div>
            ) : (
              data.recent_alerts.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center gap-4 px-5 py-3 hover:bg-gray-50 cursor-pointer"
                  onClick={() => router.push(`/admin/products/${a.product_id}`)}
                >
                  <span
                    className={`inline-flex h-2 w-2 rounded-full flex-shrink-0 ${
                      a.is_read ? 'bg-gray-300' : 'bg-orange-400'
                    }`}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                          a.alert_type === 'price'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-orange-100 text-orange-700'
                        }`}
                      >
                        {a.alert_type === 'price' ? '低价' : '销量'}
                      </span>
                      <span className="text-sm text-gray-700 truncate">
                        {a.product_title || a.product_id}
                      </span>
                    </div>
                    <p className="mt-0.5 text-xs text-gray-400 truncate">{a.message}</p>
                  </div>
                  <span className="text-xs text-gray-400 flex-shrink-0">
                    {a.created_at
                      ? new Date(a.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
                      : ''}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
