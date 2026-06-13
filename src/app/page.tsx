'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useRouter } from 'next/navigation'
import { useEffect, useState, useCallback } from 'react'

interface StatCards {
  monitor_product_count: number
  total_products: number
  on_sale_count: number
  unhandled_alerts: number
  today_new_alerts: number
}

interface RecentAlert {
  id: number
  product_id: string
  alert_type: string
  message: string
  is_read: boolean
  is_handled: boolean
  product_title: string
  created_at: string | null
}

interface RecentImport {
  id: number
  file_name: string
  import_time: string
  valid_count: number
  total_count: number
  mp_name: string
}

interface DashboardData {
  stat_cards: StatCards
  latest_alerts: RecentAlert[]
  latest_imports: RecentImport[]
}

export default function Home() {
  const { isAuthenticated, isLoading } = useAuth()
  const router = useRouter()
  const [data, setData] = useState<DashboardData | null>(null)
  const [platform, setPlatform] = useState('taobao')
  const [dashLoading, setDashLoading] = useState(true)

  // Sync platform from localStorage
  useEffect(() => {
    const sync = () => setPlatform(localStorage.getItem('platform') || 'taobao')
    sync()
    const onStorage = () => sync()
    window.addEventListener('storage', onStorage)
    // Poll for TopBar platform toggle (since it's same-origin)
    const interval = setInterval(() => {
      const p = localStorage.getItem('platform') || 'taobao'
      setPlatform(prev => prev !== p ? p : prev)
    }, 1000)
    return () => { window.removeEventListener('storage', onStorage); clearInterval(interval) }
  }, [])

  const fetchData = useCallback(async () => {
    setDashLoading(true)
    try {
      const p = localStorage.getItem('platform') || 'taobao'
      const result = await apiFetch(`/api/dashboard/summary?platform=${p}`)
      setData(result)
    } catch { /**/ } finally { setDashLoading(false) }
  }, [])

  useEffect(() => {
    if (!isLoading && !isAuthenticated) return
    if (isAuthenticated) {
      fetchData()
      const interval = setInterval(fetchData, 30000)
      return () => clearInterval(interval)
    }
  }, [isLoading, isAuthenticated, fetchData])

  // Re-fetch when platform changes
  useEffect(() => { if (isAuthenticated) fetchData() }, [platform, isAuthenticated, fetchData])

  if (isLoading || !isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gray-50">
        <div className="text-center">
          <h1 className="text-2xl font-bold text-gray-900">电商低价监控系统</h1>
          <p className="mt-2 text-gray-500">{isLoading ? '加载中...' : '请先登录'}</p>
        </div>
      </div>
    )
  }

  const s = data?.stat_cards
  const cardClass = "rounded-lg border border-gray-200 bg-white border-l-4 p-4 cursor-pointer hover:shadow-md transition-shadow"

  return (
    <div className="min-h-screen bg-gray-50 px-6 py-4">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-gray-900">数据概览</h1>
        <p className="text-xs text-gray-500">电商低价监控系统 · {platform === 'jd' ? '京东' : '淘天'}</p>
      </div>

      {/* Stat Cards */}
      {dashLoading ? (
        <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {[1,2,3,4,5].map(i => <div key={i} className="animate-pulse rounded-lg bg-gray-100 h-24" />)}
        </div>
      ) : (
        <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <div className={`${cardClass} border-l-blue-400`} onClick={() => router.push('/admin/monitor-products')}>
            <div className="text-xs text-gray-500">监控商品</div>
            <div className="mt-1 text-2xl font-bold text-blue-600">{s?.monitor_product_count ?? 0}</div>
            <div className="text-[10px] text-gray-400">个监控项目</div>
          </div>
          <div className={`${cardClass} border-l-green-400`} onClick={() => router.push('/admin/monitor-products')}>
            <div className="text-xs text-gray-500">在售商品</div>
            <div className="mt-1 text-2xl font-bold text-green-600">{s?.on_sale_count ?? 0}</div>
            <div className="text-[10px] text-gray-400">共 {s?.total_products ?? 0} 个商品</div>
          </div>
          <div className={`${cardClass} border-l-red-400`} onClick={() => router.push(`/admin/alerts?is_handled=false`)}>
            <div className="text-xs text-gray-500">未处理预警</div>
            <div className="mt-1 text-2xl font-bold text-red-600">{s?.unhandled_alerts ?? 0}</div>
            <div className="text-[10px] text-gray-400">需关注</div>
          </div>
          <div className={`${cardClass} border-l-orange-400`} onClick={() => router.push('/admin/alerts')}>
            <div className="text-xs text-gray-500">今日新增预警</div>
            <div className="mt-1 text-2xl font-bold text-orange-500">{s?.today_new_alerts ?? 0}</div>
            <div className="text-[10px] text-gray-400">{new Date().toLocaleDateString('zh-CN')}</div>
          </div>
          <div className={`${cardClass} border-l-purple-400 cursor-default hover:shadow-none`}>
            <div className="text-xs text-gray-500">平台</div>
            <div className="mt-1 text-xl font-bold text-purple-600">{platform === 'jd' ? '京东' : '淘天'}</div>
            <div className="text-[10px] text-gray-400">当前数据</div>
          </div>
        </div>
      )}

      {/* Latest Alerts + Latest Imports */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Latest Alerts */}
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2">
            <h2 className="text-sm font-semibold text-gray-700">最近预警</h2>
            <button onClick={() => router.push('/admin/alerts')} className="text-xs text-blue-600 hover:text-blue-800">
              查看全部 →
            </button>
          </div>
          {dashLoading ? (
            <div className="p-4 space-y-2">{[1,2,3].map(i => <div key={i} className="animate-pulse h-6 bg-gray-100 rounded" />)}</div>
          ) : (data?.latest_alerts || []).length === 0 ? (
            <p className="p-4 text-center text-xs text-gray-400">暂无预警</p>
          ) : (
            <div className="divide-y divide-gray-100">
              {(data?.latest_alerts || []).slice(0, 5).map(a => (
                <div key={a.id} className="flex items-center gap-3 px-4 py-2 hover:bg-gray-50 cursor-pointer"
                  onClick={() => router.push(`/admin/alerts?monitor_product_id=&is_handled=false`)}>
                  <span className={`shrink-0 text-xs px-1.5 py-0.5 rounded-full font-medium ${
                    a.alert_type === 'price' ? 'bg-red-100 text-red-700' :
                    a.alert_type === 'price_drop' ? 'bg-purple-100 text-purple-700' : 'bg-orange-100 text-orange-700'}`}>
                    {a.alert_type === 'price' ? '💰' : a.alert_type === 'price_drop' ? '📉' : '📈'}
                  </span>
                  <span className="flex-1 truncate text-xs text-gray-600">{a.product_title}{a.is_handled ? '' : <span className="ml-1 text-red-500">●</span>}</span>
                  <span className="shrink-0 text-[10px] text-gray-400">
                    {a.created_at ? new Date(a.created_at).toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}) : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Latest Imports */}
        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-200 px-4 py-2">
            <h2 className="text-sm font-semibold text-gray-700">最近导入</h2>
            <button onClick={() => router.push('/admin/monitor-products')} className="text-xs text-blue-600 hover:text-blue-800">
              查看全部 →
            </button>
          </div>
          {dashLoading ? (
            <div className="p-4 space-y-2">{[1,2,3].map(i => <div key={i} className="animate-pulse h-6 bg-gray-100 rounded" />)}</div>
          ) : (data?.latest_imports || []).length === 0 ? (
            <p className="p-4 text-center text-xs text-gray-400">暂无导入记录</p>
          ) : (
            <div className="divide-y divide-gray-100">
              {(data?.latest_imports || []).slice(0, 3).map(imp => (
                <div key={imp.id} className="flex items-center gap-3 px-4 py-2">
                  <span className="text-lg">📄</span>
                  <div className="flex-1 min-w-0">
                    <div className="truncate text-xs text-gray-700">{imp.file_name}</div>
                    <div className="text-[10px] text-gray-400">{imp.mp_name} · 有效 {imp.valid_count}/{imp.total_count} 条</div>
                  </div>
                  <span className="shrink-0 text-[10px] text-gray-400">
                    {imp.import_time ? new Date(imp.import_time).toLocaleDateString('zh-CN', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
