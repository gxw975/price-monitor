'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiFetch, cn, formatDateTime } from '@/lib/utils'

interface AlertItem {
  id: number
  product_id: string
  product_title: string
  alert_type: string
  message: string
  is_sent: boolean
  sent_at: string | null
  is_read: boolean
  created_at: string
}

interface AlertsResponse {
  items: AlertItem[]
  total: number
  page: number
  page_size: number
  unread_count: number
}

interface Stats {
  total: number
  unread: number
  by_type: Record<string, number>
  recent_7d: Record<string, number>
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [unreadCount, setUnreadCount] = useState(0)
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<{ type: string; keyword: string; read: string }>({
    type: '',
    keyword: '',
    read: '',
  })
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const fetchAlerts = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', String(page))
      params.set('page_size', '20')
      if (filter.type) params.set('alert_type', filter.type)
      if (filter.read === 'unread') params.set('is_read', 'false')
      if (filter.read === 'read') params.set('is_read', 'true')
      if (filter.keyword) params.set('keyword', filter.keyword)

      const data: AlertsResponse = await apiFetch(`/api/alerts/list?${params}`)
      setAlerts(data.items)
      setTotal(data.total)
      setUnreadCount(data.unread_count)
    } catch (err) {
      console.error('获取预警列表失败:', err)
    } finally {
      setLoading(false)
    }
  }, [page, filter])

  const fetchStats = useCallback(async () => {
    try {
      const data: Stats = await apiFetch('/api/alerts/stats')
      setStats(data)
    } catch (err) {
      console.error('获取统计数据失败:', err)
    }
  }, [])

  useEffect(() => {
    fetchAlerts()
  }, [fetchAlerts])

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  const handleMarkRead = async (ids: number[]) => {
    try {
      await apiFetch('/api/alerts/mark-read', {
        method: 'POST',
        body: JSON.stringify({ ids }),
      } as any)
      setSelectedIds(new Set())
      fetchAlerts()
      fetchStats()
    } catch (err) {
      console.error('标记已读失败:', err)
    }
  }

  const handleExport = async () => {
    try {
      const params = new URLSearchParams()
      if (filter.type) params.set('alert_type', filter.type)
      const data = await apiFetch(`/api/alerts/export?${params}`, {
        method: 'POST',
      } as any)
      const blob = new Blob(['\uFEFF' + data.csv], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `alerts_${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('导出失败:', err)
    }
  }

  const handleSelectAll = () => {
    if (selectedIds.size === alerts.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(alerts.map((a) => a.id)))
    }
  }

  const handleToggleSelect = (id: number) => {
    const next = new Set(selectedIds)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    setSelectedIds(next)
  }

  const totalPages = Math.ceil(total / 20)

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">预警管理</h1>
          <span className="text-sm text-gray-500">电商低价监控系统</span>
        </div>

        <div className="mb-6 grid grid-cols-4 gap-4">
          <Card
            title="总预警"
            value={stats?.total ?? 0}
            color="text-gray-700"
            bg="bg-gray-50"
          />
          <Card
            title="未读"
            value={unreadCount}
            color="text-red-600"
            bg="bg-red-50"
          />
          <Card
            title="价格预警(7天)"
            value={stats?.recent_7d?.price ?? 0}
            color="text-red-500"
            bg="bg-red-50"
          />
          <Card
            title="销量预警(7天)"
            value={stats?.recent_7d?.sales ?? 0}
            color="text-orange-500"
            bg="bg-orange-50"
          />
        </div>

        <div className="mb-4 flex items-center gap-3 flex-wrap">
          <select
            className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
            value={filter.type}
            onChange={(e) => { setFilter((f) => ({ ...f, type: e.target.value })); setPage(1) }}
          >
            <option value="">全部类型</option>
            <option value="price">价格预警</option>
            <option value="sales">销量预警</option>
          </select>

          <select
            className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
            value={filter.read}
            onChange={(e) => { setFilter((f) => ({ ...f, read: e.target.value })); setPage(1) }}
          >
            <option value="">全部状态</option>
            <option value="unread">未读</option>
            <option value="read">已读</option>
          </select>

          <input
            type="text"
            placeholder="搜索商品..."
            className="rounded-md border border-gray-300 px-3 py-2 text-sm flex-1 min-w-[200px]"
            value={filter.keyword}
            onChange={(e) => { setFilter((f) => ({ ...f, keyword: e.target.value })); setPage(1) }}
          />

          <div className="flex gap-2 ml-auto">
            {selectedIds.size > 0 && (
              <button
                onClick={() => handleMarkRead(Array.from(selectedIds))}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
              >
                标记已读 ({selectedIds.size})
              </button>
            )}
            <button
              onClick={handleExport}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
            >
              导出 CSV
            </button>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  <th className="w-10 px-4 py-3">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === alerts.length && alerts.length > 0}
                      onChange={handleSelectAll}
                      className="rounded"
                    />
                  </th>
                  <th className="px-4 py-3 font-medium">类型</th>
                  <th className="px-4 py-3 font-medium">商品</th>
                  <th className="px-4 py-3 font-medium">预警消息</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">时间</th>
                  <th className="px-4 py-3 font-medium">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                      加载中...
                    </td>
                  </tr>
                ) : alerts.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-gray-400">
                      暂无预警记录
                    </td>
                  </tr>
                ) : (
                  alerts.map((alert) => (
                    <tr
                      key={alert.id}
                      className={cn(
                        'hover:bg-gray-50 transition-colors',
                        !alert.is_read && 'bg-blue-50/50'
                      )}
                    >
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selectedIds.has(alert.id)}
                          onChange={() => handleToggleSelect(alert.id)}
                          className="rounded"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
                            alert.alert_type === 'price'
                              ? 'bg-red-100 text-red-700'
                              : 'bg-orange-100 text-orange-700'
                          )}
                        >
                          {alert.alert_type === 'price' ? '价格' : '销量'}
                        </span>
                      </td>
                      <td className="px-4 py-3 max-w-[200px] truncate" title={alert.product_title}>
                        {alert.product_title}
                      </td>
                      <td className="px-4 py-3 max-w-[350px] truncate" title={alert.message}>
                        {alert.message}
                      </td>
                      <td className="px-4 py-3">
                        {alert.is_read ? (
                          <span className="text-green-600 text-xs">已读</span>
                        ) : (
                          <span className="text-red-500 text-xs font-medium">● 未读</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                        {formatDateTime(alert.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        {!alert.is_read && (
                          <button
                            onClick={() => handleMarkRead([alert.id])}
                            className="text-blue-600 hover:text-blue-800 text-xs"
                          >
                            标为已读
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3">
              <span className="text-sm text-gray-500">
                共 {total} 条，第 {page}/{totalPages} 页
              </span>
              <div className="flex gap-1">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="rounded border px-3 py-1 text-sm disabled:opacity-40 hover:bg-gray-100"
                >
                  上一页
                </button>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded border px-3 py-1 text-sm disabled:opacity-40 hover:bg-gray-100"
                >
                  下一页
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Card({
  title,
  value,
  color,
  bg,
}: {
  title: string
  value: number
  color: string
  bg: string
}) {
  return (
    <div className={cn('rounded-lg border p-4', bg)}>
      <div className="text-sm text-gray-500">{title}</div>
      <div className={cn('mt-1 text-2xl font-bold', color)}>{value}</div>
    </div>
  )
}
