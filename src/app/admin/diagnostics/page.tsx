'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useRef, useState } from 'react'

interface HealthItem {
  name: string
  status: string
  detail: string
}

interface HealthResult {
  overall: string
  checked_at: string
  issues: string[]
  items: HealthItem[]
}

interface TaobaoLoginState {
  session: string
  qrcode: string
  status: string
  message: string
  logged_in: boolean
  banned: boolean
  username: string
}

type LogFile = 'crawl' | 'alert' | 'backend' | 'frontend'

export default function DiagnosticsPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'

  const [health, setHealth] = useState<HealthResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [logFile, setLogFile] = useState<LogFile>('crawl')
  const [logLines, setLogLines] = useState<string[]>([])
  const [logInfo, setLogInfo] = useState({ total_lines: 0, showing: 0 })
  const [logLoading, setLogLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState('')
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)

  const [tbLogin, setTbLogin] = useState<TaobaoLoginState | null>(null)
  const [tbLoading, setTbLoading] = useState(false)
  const [tbMsg, setTbMsg] = useState<{ type: 'success' | 'error' | 'warning'; text: string } | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [tbStatus, setTbStatus] = useState<{ logged_in: boolean; banned: boolean; username: string; status: string } | null>(null)

  const fetchHealth = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiFetch('/api/diagnostics/health')
      setHealth(data)
      setMsg(null)
    } catch {
      setMsg({ type: 'error', text: '健康检查失败' })
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchLogs = useCallback(async (file: LogFile) => {
    setLogLoading(true)
    try {
      const data = await apiFetch(`/api/diagnostics/logs?file=${file}&lines=100`)
      setLogLines(data.lines || [])
      setLogInfo({ total_lines: data.total_lines, showing: data.showing })
    } catch {
      setLogLines([])
    } finally {
      setLogLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchHealth()
  }, [fetchHealth])

  useEffect(() => {
    fetchLogs(logFile)
  }, [logFile, fetchLogs])

  useEffect(() => {
    if (autoRefresh) {
      const interval = setInterval(() => {
        fetchHealth()
        fetchLogs(logFile)
      }, 10000)
      return () => clearInterval(interval)
    }
  }, [autoRefresh, logFile, fetchHealth, fetchLogs])

  const maintenance = async (action: string) => {
    setActionLoading(action)
    setMsg(null)
    try {
      const data = await apiFetch(`/api/diagnostics/maintenance/${action}`, { method: 'POST' })
      setMsg({
        type: data.success ? 'success' : 'error',
        text: data.message || (data.success ? '操作成功' : '操作失败'),
      })
      if (action === 'restart') setTimeout(fetchHealth, 3000)
      else fetchHealth()
    } catch (err: any) {
      setMsg({ type: 'error', text: err.message || '操作失败' })
    } finally {
      setActionLoading('')
    }
  }

  const fetchTaobaoStatus = useCallback(async () => {
    try {
      const data = await apiFetch('/api/taobao/status')
      setTbStatus(data)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    if (canWrite) fetchTaobaoStatus()
  }, [canWrite, fetchTaobaoStatus])

  const startTaobaoLogin = async () => {
    setTbLoading(true)
    setTbLogin(null)
    setTbMsg(null)
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
    try {
      const data = await apiFetch('/api/taobao/start-login', { method: 'POST' })
      setTbLogin(data)
      setTbMsg({ type: 'success', text: data.message || '二维码已生成' })
      pollRef.current = setInterval(() => checkTaobaoLogin(), 3000)
    } catch (err: any) {
      setTbMsg({ type: 'error', text: err.message || '启动登录失败' })
    } finally {
      setTbLoading(false)
    }
  }

  const checkTaobaoLogin = async () => {
    if (!tbLogin) return
    try {
      const data = await apiFetch('/api/taobao/check-login')
      if (data.logged_in) {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
        setTbMsg({ type: 'success', text: data.message || `登录成功！当前账号：${data.username}` })
        fetchTaobaoStatus()
      } else if (data.banned) {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
        setTbMsg({ type: 'error', text: data.message || '该账号已被限制登录' })
      } else if (data.status === 'expired') {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
        setTbMsg({ type: 'warning', text: data.message })
        setTimeout(() => setTbLogin(null), 3000)
      }
    } catch { /* polling error, ignore */ }
  }

  useEffect(() => {
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  if (loading || !health) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-gray-400">加载中...</p>
      </div>
    )
  }

  const logFiles: { key: LogFile; label: string }[] = [
    { key: 'crawl', label: '抓取日志' },
    { key: 'alert', label: '预警日志' },
    { key: 'backend', label: '后端日志' },
    { key: 'frontend', label: '前端日志' },
  ]

  const statusColor = (status: string) => {
    if (status === 'ok') return 'bg-green-100 text-green-700 border-green-200'
    if (status === 'warning') return 'bg-yellow-100 text-yellow-700 border-yellow-200'
    return 'bg-red-100 text-red-700 border-red-200'
  }

  const statusIcon = (status: string) => {
    if (status === 'ok') return '✅'
    if (status === 'warning') return '⚠️'
    return '❌'
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">故障排查</h1>
            <p className="mt-1 text-sm text-gray-500">
              系统健康状态：{health.overall === 'ok' ? '正常' : '异常'} · 检查时间 {new Date(health.checked_at).toLocaleTimeString('zh-CN')}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded"
              />
              自动刷新
            </label>
            <button
              onClick={fetchHealth}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
            >
              刷新
            </button>
          </div>
        </div>

        {msg && (
          <div className={`mb-4 rounded-lg px-4 py-3 text-sm ${
            msg.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' :
            'bg-red-50 text-red-700 border border-red-200'
          }`}>
            {msg.text}
          </div>
        )}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="space-y-4">
            <div className="rounded-lg border border-gray-200 bg-white p-5">
              <h2 className="mb-3 text-base font-semibold text-gray-900">系统健康状态</h2>
              <div className="space-y-2">
                {health.items.map((item, idx) => (
                  <div key={idx} className={`rounded-lg border px-4 py-3 ${statusColor(item.status)}`}>
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">
                        {statusIcon(item.status)} {item.name}
                      </span>
                      <span className={`text-xs font-mono px-2 py-0.5 rounded ${
                        item.status === 'ok' ? 'bg-green-50' : item.status === 'warning' ? 'bg-yellow-50' : 'bg-red-50'
                      }`}>
                        {item.status === 'ok' ? '正常' : item.status === 'warning' ? '警告' : '异常'}
                      </span>
                    </div>
                    <p className="mt-1 text-xs opacity-75">{item.detail}</p>
                  </div>
                ))}
              </div>
            </div>

            {canWrite && (
              <div className="rounded-lg border border-gray-200 bg-white p-5">
                <h2 className="mb-3 text-base font-semibold text-gray-900">一键维护</h2>
                <div className="grid grid-cols-1 gap-2">
                  <button
                    onClick={() => maintenance('restart')}
                    disabled={actionLoading !== ''}
                    className="flex items-center justify-between rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-700 hover:bg-blue-100 disabled:opacity-50"
                  >
                    <span>🔄 一键重启所有服务</span>
                    <span className="text-xs text-blue-400">
                      {actionLoading === 'restart' ? '执行中...' : ''}
                    </span>
                  </button>
                  <button
                    onClick={() => maintenance('clean-logs')}
                    disabled={actionLoading !== ''}
                    className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
                  >
                    <span>🗑 一键清理过期日志（7天前）</span>
                    <span className="text-xs text-gray-400">
                      {actionLoading === 'clean-logs' ? '执行中...' : ''}
                    </span>
                  </button>
                  <button
                    onClick={() => maintenance('backup')}
                    disabled={actionLoading !== ''}
                    className="flex items-center justify-between rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700 hover:bg-green-100 disabled:opacity-50"
                  >
                    <span>💾 一键手动备份数据库</span>
                    <span className="text-xs text-green-400">
                      {actionLoading === 'backup' ? '执行中...' : ''}
                    </span>
                  </button>
                  <button
                    onClick={() => maintenance('test-all-channels')}
                    disabled={actionLoading !== ''}
                    className="flex items-center justify-between rounded-lg border border-purple-200 bg-purple-50 px-4 py-3 text-sm text-purple-700 hover:bg-purple-100 disabled:opacity-50"
                  >
                    <span>📨 一键测试所有推送渠道</span>
                    <span className="text-xs text-purple-400">
                      {actionLoading === 'test-all-channels' ? '执行中...' : ''}
                    </span>
                  </button>
                </div>
              </div>
            )}

            {canWrite && (
              <div className="rounded-lg border border-gray-200 bg-white p-5">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-base font-semibold text-gray-900">淘宝账号登录</h2>
                  {tbStatus && (
                    <span className={`text-xs px-2 py-0.5 rounded-full ${
                      tbStatus.logged_in ? 'bg-green-100 text-green-700' :
                      tbStatus.banned ? 'bg-red-100 text-red-700' :
                      'bg-gray-100 text-gray-500'
                    }`}>
                      {tbStatus.logged_in
                        ? `已登录${tbStatus.username ? `：${tbStatus.username}` : ''}`
                        : tbStatus.banned ? '账号受限' : '未登录'}
                    </span>
                  )}
                </div>

                {tbMsg && (
                  <div className={`mb-3 rounded-lg px-3 py-2 text-sm ${
                    tbMsg.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' :
                    tbMsg.type === 'error' ? 'bg-red-50 text-red-700 border border-red-200' :
                    'bg-yellow-50 text-yellow-700 border border-yellow-200'
                  }`}>
                    {tbMsg.text}
                  </div>
                )}

                {tbLogin?.qrcode && (!tbLogin.logged_in) && (
                  <div className="mb-3 flex justify-center rounded-lg border border-gray-100 bg-gray-50 p-2">
                    <img
                      src={tbLogin.qrcode}
                      alt="淘宝登录二维码"
                      className="max-h-64 w-auto rounded"
                    />
                  </div>
                )}

                <div className="flex gap-2">
                  <button
                    onClick={startTaobaoLogin}
                    disabled={tbLoading}
                    className="flex items-center gap-2 rounded-lg border border-orange-200 bg-orange-50 px-4 py-2.5 text-sm font-medium text-orange-700 hover:bg-orange-100 disabled:opacity-50"
                  >
                    {tbLoading ? (
                      <>
                        <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-orange-300 border-t-orange-600" />
                        打开浏览器中...
                      </>
                    ) : tbLogin?.qrcode && !tbLogin.logged_in ? (
                      <>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M23 4v6h-6"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                        重新获取二维码
                      </>
                    ) : (
                      '🔄 刷新淘宝登录'
                    )}
                  </button>

                  {tbLogin?.qrcode && !tbLogin.logged_in && (
                    <span className="flex items-center gap-1 text-xs text-gray-400">
                      <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-green-400" />
                      等待扫码中...
                    </span>
                  )}
                </div>

                <p className="mt-2 text-xs text-gray-400">
                  点击刷新登录，使用淘宝/天猫APP扫描上方二维码即可登录。登录状态会自动保存，后续抓取任务将使用该账号。
                </p>
              </div>
            )}

          </div>

          <div className="rounded-lg border border-gray-200 bg-white">
            <div className="border-b border-gray-200 px-5 py-3 flex items-center justify-between flex-wrap gap-2">
              <h2 className="text-base font-semibold text-gray-900">在线日志</h2>
              <div className="flex items-center gap-2 flex-wrap">
                {logFiles.map((f) => (
                  <button
                    key={f.key}
                    onClick={() => setLogFile(f.key)}
                    className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                      logFile === f.key ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="border-b border-gray-100 px-5 py-2 text-xs text-gray-400">
              总共 {logInfo.total_lines} 行 · 显示最近 {logInfo.showing} 行
              <button
                onClick={() => fetchLogs(logFile)}
                className="ml-3 text-blue-600 hover:text-blue-800"
              >
                刷新
              </button>
            </div>
            <div className="max-h-[500px] overflow-y-auto p-4 bg-gray-900 text-green-400 font-mono text-xs leading-relaxed" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
              {logLoading ? (
                <span className="text-gray-400">加载中...</span>
              ) : logLines.length === 0 ? (
                <span className="text-gray-500">暂无日志内容</span>
              ) : (
                logLines.map((line, i) => {
                  const isError = line.includes('[ERROR') || line.includes('ERROR') || line.includes('Error')
                  const isWarn = line.includes('[WARNING') || line.includes('WARN')
                  const isCron = line.includes('check_alerts') || line.includes('run_sku_crawl')
                  return (
                    <div
                      key={i}
                      className={
                        isError ? 'text-red-400' :
                        isWarn ? 'text-yellow-400' :
                        isCron ? 'text-cyan-300' : ''
                      }
                    >
                      {line}
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
