'use client'

import { apiFetch, cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useState } from 'react'

interface LogItem {
  id: number
  user_id: number
  username: string
  action: string
  target: string
  method: string
  path: string
  ip: string
  details: string
  created_at: string | null
}

export default function LogsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [logs, setLogs] = useState<LogItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [filterAction, setFilterAction] = useState('')

  const fetchLogs = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', String(page))
      params.set('page_size', '50')
      if (filterAction) params.set('action', filterAction)
      const data = await apiFetch(`/api/logs/list?${params}`)
      setLogs(data.items)
      setTotal(data.total)
    } catch (err) {
      console.error('获取日志失败:', err)
    } finally {
      setLoading(false)
    }
  }, [page, filterAction])

  useEffect(() => { fetchLogs() }, [fetchLogs])

  const totalPages = Math.ceil(total / 50)

  const actionColors: Record<string, string> = {
    '创建': 'bg-green-100 text-green-700',
    '更新': 'bg-blue-100 text-blue-700',
    '修改': 'bg-blue-100 text-blue-700',
    '删除': 'bg-red-100 text-red-700',
    '导入': 'bg-purple-100 text-purple-700',
    '标记': 'bg-yellow-100 text-yellow-700',
    '批量': 'bg-orange-100 text-orange-700',
    '重启': 'bg-pink-100 text-pink-700',
    '停止': 'bg-pink-100 text-pink-700',
    '启动': 'bg-green-100 text-green-700',
    '设置': 'bg-blue-100 text-blue-700',
    '测试': 'bg-cyan-100 text-cyan-700',
    'API': 'bg-gray-100 text-gray-600',
  }

  function getActionColor(action: string): string {
    for (const [key, color] of Object.entries(actionColors)) {
      if (action.startsWith(key)) return color
    }
    return 'bg-gray-100 text-gray-600'
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">操作日志</h1>
            <p className="mt-1 text-sm text-gray-500">
              {isAdmin ? '所有用户操作记录' : '我的操作记录'}
            </p>
          </div>
        </div>

        <div className="mb-4 flex items-center gap-3">
          <select
            value={filterAction}
            onChange={(e) => { setFilterAction(e.target.value); setPage(1) }}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
          >
            <option value="">全部操作</option>
            <option value="创建关键词">创建关键词</option>
            <option value="更新关键词">更新关键词</option>
            <option value="删除关键词">删除关键词</option>
            <option value="批量切换关键词">批量切换关键词</option>
            <option value="批量绑定关键词">批量绑定关键词</option>
            <option value="导入商品">导入商品</option>
            <option value="导入关键词">导入关键词</option>
            <option value="标记预警已读">标记预警已读</option>
            <option value="标记预警已处理">标记预警已处理</option>
            <option value="批量删除预警">批量删除预警</option>
            <option value="创建用户">创建用户</option>
            <option value="更新用户">更新用户</option>
            <option value="删除用户">删除用户</option>
            <option value="修改密码">修改密码</option>
            <option value="修改系统设置">修改系统设置</option>
            <option value="重启服务">重启服务</option>
            <option value="停止服务">停止服务</option>
            <option value="启动服务">启动服务</option>
            <option value="设置商品关键词">设置商品关键词</option>
          </select>

          <span className="text-xs text-gray-400 ml-auto">共 {total} 条记录</span>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  <th className="px-4 py-3 font-medium">时间</th>
                  <th className="px-4 py-3 font-medium">用户</th>
                  <th className="px-4 py-3 font-medium">操作</th>
                  <th className="px-4 py-3 font-medium">路径</th>
                  <th className="px-4 py-3 font-medium">IP</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-gray-400">
                      加载中...
                    </td>
                  </tr>
                ) : logs.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-12 text-center text-gray-400">
                      暂无操作记录
                    </td>
                  </tr>
                ) : (
                  logs.map((log) => (
                    <tr key={log.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                        {log.created_at
                          ? new Date(log.created_at).toLocaleString('zh-CN', {
                              month: '2-digit',
                              day: '2-digit',
                              hour: '2-digit',
                              minute: '2-digit',
                              second: '2-digit',
                            })
                          : '-'}
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-1.5">
                          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-gray-100 text-xs font-medium text-gray-600">
                            {log.username.charAt(0).toUpperCase()}
                          </span>
                          <span className="text-gray-700">{log.username}</span>
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={cn(
                          'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                          getActionColor(log.action)
                        )}>
                          {log.action}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs font-mono">
                        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-500">
                          {log.method}
                        </span>
                        <span className="ml-1.5 text-gray-400">{log.path}</span>
                      </td>
                      <td className="px-4 py-3 text-gray-400 text-xs">{log.ip}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3">
              <span className="text-xs text-gray-400">
                第 {page}/{totalPages} 页
              </span>
              <div className="flex gap-1">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="rounded border px-3 py-1 text-xs disabled:opacity-40 hover:bg-gray-100"
                >
                  上一页
                </button>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded border px-3 py-1 text-xs disabled:opacity-40 hover:bg-gray-100"
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
