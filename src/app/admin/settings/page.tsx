'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useState } from 'react'

interface ServiceInfo {
  status: string
  details: string
}

interface ServicesStatus {
  [key: string]: ServiceInfo
}

interface Settings {
  id: number
  alert_price: number
  work_start_hour: number
  work_end_hour: number
  sales_growth_threshold: number
  alert_dedup_hours: number
  sku_crawl_limit: number
  sku_crawl_interval: number
  crawl_schedule_type: string
  crawl_fixed_times: string | null
  crawl_daily_limit: number
  check_alert_interval: number
  feishu_webhook: string | null
  wechat_webhook: string | null
  push_enabled_channels: string
  updated_at: string | null
}

type Tab = 'service' | 'cron' | 'alert' | 'push'

export default function SettingsPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'

  const [tab, setTab] = useState<Tab>('service')
  const [services, setServices] = useState<ServicesStatus>({})
  const [settings, setSettings] = useState<Settings | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [actionLoading, setActionLoading] = useState('')
  const [testResults, setTestResults] = useState<Record<string, string | null>>({})
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const fetchServices = useCallback(async () => {
    try {
      const data = await apiFetch('/api/service/status')
      setServices(data.services)
      setMsg(null)
    } catch {
      setServices({})
    }
  }, [])

  const fetchSettings = useCallback(async () => {
    try {
      const data = await apiFetch('/api/settings')
      setSettings(data)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchServices()
    fetchSettings()
  }, [fetchServices, fetchSettings])

  useEffect(() => {
    if (tab === 'service') {
      const interval = setInterval(fetchServices, 5000)
      return () => clearInterval(interval)
    }
  }, [tab, fetchServices])

  const serviceAction = async (action: string) => {
    setActionLoading(action)
    setMsg(null)
    try {
      const data = await apiFetch(`/api/service/${action}`, { method: 'POST' })
      if (data.success) {
        setMsg({ type: 'success', text: `服务${action === 'restart' ? '重启' : action === 'start' ? '启动' : '停止'}成功` })
      } else {
        setMsg({ type: 'error', text: data.message || '操作失败' })
      }
      setTimeout(fetchServices, 2000)
    } catch (err: any) {
      setMsg({ type: 'error', text: err.message || '操作失败' })
    } finally {
      setActionLoading('')
    }
  }

  const testPush = async (channel: string, url: string) => {
    if (!url.trim()) {
      setTestResults({ ...testResults, [channel]: '请先输入 Webhook 地址' })
      return
    }
    setTestResults({ ...testResults, [channel]: null })
    setMsg(null)
    try {
      const data = await apiFetch('/api/push/test', {
        method: 'POST',
        body: JSON.stringify({ channel, webhook_url: url.trim() }),
      })
      setTestResults({
        ...testResults,
        [channel]: data.success ? 'success' : (data.message || '发送失败'),
      })
      if (data.success) {
        setMsg({ type: 'success', text: `${channel === 'feishu' ? '飞书' : '微信'} 测试消息发送成功` })
      } else {
        setMsg({ type: 'error', text: data.message || '发送失败' })
      }
    } catch (err: any) {
      setTestResults({ ...testResults, [channel]: err.message || '请求失败' })
      setMsg({ type: 'error', text: err.message || '请求失败' })
    }
  }

  const togglePushChannel = (channel: string) => {
    if (!settings || !canWrite) return
    let channels: string[] = []
    try {
      channels = JSON.parse(settings.push_enabled_channels)
    } catch {
      channels = ['feishu']
    }
    if (channels.includes(channel)) {
      channels = channels.filter((c: string) => c !== channel)
    } else {
      channels = [...channels, channel]
    }
    const updated = { ...settings, push_enabled_channels: JSON.stringify(channels) }
    setSaving(true)
    setMsg(null)
    apiFetch('/api/settings', { method: 'PUT', body: JSON.stringify(updated) })
      .then(() => {
        setSettings(updated)
        setMsg({ type: 'success', text: '推送渠道已更新' })
      })
      .catch((err: any) => setMsg({ type: 'error', text: err.message }))
      .finally(() => setSaving(false))
  }

  const updateSettings = async (changes: Partial<Settings>) => {
    if (!settings || !canWrite) return
    const updated = { ...settings, ...changes }
    setSaving(true)
    setMsg(null)
    try {
      await apiFetch('/api/settings', {
        method: 'PUT',
        body: JSON.stringify(updated),
      })
      setSettings(updated)
      setMsg({ type: 'success', text: '设置已保存' })
    } catch (err: any) {
      setMsg({ type: 'error', text: err.message || '保存失败' })
    } finally {
      setSaving(false)
    }
  }

  const updateCron = async () => {
    if (!canWrite) return
    setActionLoading('cron')
    setMsg(null)
    try {
      await apiFetch('/api/cron/update', { method: 'POST' })
      setMsg({ type: 'success', text: '定时任务已更新' })
    } catch (err: any) {
      setMsg({ type: 'error', text: err.message || '更新失败' })
    } finally {
      setActionLoading('')
    }
  }

  if (loading || !settings) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-gray-400">加载中...</p>
      </div>
    )
  }

  const tabs: { key: Tab; label: string }[] = [
    { key: 'service', label: '服务控制' },
    { key: 'cron', label: '定时任务' },
    { key: 'alert', label: '报警阈值' },
    { key: 'push', label: '推送设置' },
  ]

  const serviceLabels: Record<string, string> = {
    'fastapi-backend': '后端 API',
    'nextjs-frontend': '前端服务',
  }

  const intervalHours = Math.max(1, Math.round(settings.sku_crawl_interval / 60 * 10) / 10)
  const alertIntervalHours = Math.max(0.5, Math.round(settings.check_alert_interval / 60 * 10) / 10)

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-4xl">
        <h1 className="mb-6 text-2xl font-bold text-gray-900">系统设置</h1>

        {msg && (
          <div className={`mb-4 rounded-lg px-4 py-3 text-sm ${
            msg.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' :
            'bg-red-50 text-red-700 border border-red-200'
          }`}>
            {msg.text}
          </div>
        )}

        <div className="mb-6 flex gap-1 rounded-lg bg-gray-100 p-1">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex-1 rounded-md py-2 text-sm font-medium transition-colors ${
                tab === t.key ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        {tab === 'service' && (
          <div className="space-y-4">
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="mb-4 text-base font-semibold text-gray-900">服务状态</h2>
              <div className="space-y-3">
                {['fastapi-backend', 'nextjs-frontend'].map((name) => {
                  const svc = services[name]
                  const running = svc?.status === 'RUNNING'
                  return (
                    <div key={name} className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
                      <div className="flex items-center gap-3">
                        <span className={`h-2.5 w-2.5 rounded-full ${running ? 'bg-green-500 animate-pulse' : 'bg-red-400'}`} />
                        <span className="text-sm font-medium text-gray-700">
                          {serviceLabels[name] || name}
                        </span>
                      </div>
                      <span className={`text-sm ${running ? 'text-green-600' : 'text-red-500'}`}>
                        {running ? '运行中' : svc?.status || '未知'}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>

            {canWrite && (
              <div className="rounded-lg border border-gray-200 bg-white p-6">
                <h2 className="mb-4 text-base font-semibold text-gray-900">服务操作</h2>
                <div className="flex gap-3">
                  <button
                    onClick={() => serviceAction('start')}
                    disabled={actionLoading !== ''}
                    className="rounded-md bg-green-600 px-5 py-2 text-sm text-white hover:bg-green-700 disabled:opacity-50"
                  >
                    {actionLoading === 'start' ? '启动中...' : '启动服务'}
                  </button>
                  <button
                    onClick={() => serviceAction('stop')}
                    disabled={actionLoading !== ''}
                    className="rounded-md bg-red-600 px-5 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-50"
                  >
                    {actionLoading === 'stop' ? '停止中...' : '停止服务'}
                  </button>
                  <button
                    onClick={() => serviceAction('restart')}
                    disabled={actionLoading !== ''}
                    className="rounded-md bg-blue-600 px-5 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {actionLoading === 'restart' ? '重启中...' : '重启服务'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {tab === 'cron' && (
          <div className="space-y-4">
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="mb-4 text-base font-semibold text-gray-900">抓取任务设置</h2>

              <div className="space-y-5">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">调度模式</label>
                  <div className="flex gap-3">
                    <label className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 cursor-pointer text-sm ${
                      settings.crawl_schedule_type === 'interval' ? 'border-blue-400 bg-blue-50' : 'border-gray-200'
                    }`}>
                      <input
                        type="radio"
                        name="scheduleType"
                        checked={settings.crawl_schedule_type === 'interval'}
                        onChange={() => updateSettings({ crawl_schedule_type: 'interval' })}
                        disabled={!canWrite}
                      />
                      按间隔执行
                    </label>
                    <label className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 cursor-pointer text-sm ${
                      settings.crawl_schedule_type === 'fixed_time' ? 'border-blue-400 bg-blue-50' : 'border-gray-200'
                    }`}>
                      <input
                        type="radio"
                        name="scheduleType"
                        checked={settings.crawl_schedule_type === 'fixed_time'}
                        onChange={() => updateSettings({ crawl_schedule_type: 'fixed_time' })}
                        disabled={!canWrite}
                      />
                      按固定时间
                    </label>
                  </div>
                </div>

                {settings.crawl_schedule_type === 'interval' ? (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      抓取间隔（小时）
                    </label>
                    <div className="flex items-center gap-3">
                      <input
                        type="range"
                        min="1"
                        max="24"
                        step="1"
                        value={Math.round(settings.sku_crawl_interval / 60)}
                        onChange={(e) => updateSettings({ sku_crawl_interval: parseInt(e.target.value) * 60 })}
                        disabled={!canWrite}
                        className="flex-1"
                      />
                      <span className="w-20 rounded-md border border-gray-300 px-3 py-1.5 text-center text-sm tabular-nums">
                        {Math.round(settings.sku_crawl_interval / 60)} 小时
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-gray-400">当前: {intervalHours} 小时 = {settings.sku_crawl_interval} 分钟</p>
                  </div>
                ) : (
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      固定时间点（逗号分隔，如 02:00,14:00）
                    </label>
                    <input
                      type="text"
                      value={settings.crawl_fixed_times || ''}
                      onChange={(e) => {
                        const val = e.target.value
                        setSettings({ ...settings, crawl_fixed_times: val })
                      }}
                      onBlur={() => {
                        if (settings.crawl_fixed_times !== undefined && canWrite) {
                          updateSettings({ crawl_fixed_times: settings.crawl_fixed_times })
                        }
                      }}
                      disabled={!canWrite}
                      placeholder="02:00,10:00,18:00"
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                  </div>
                )}

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    每日最大抓取次数
                  </label>
                  <input
                    type="number"
                    min="1"
                    max="1000"
                    value={settings.crawl_daily_limit}
                    onChange={(e) => {
                      setSettings({ ...settings, crawl_daily_limit: parseInt(e.target.value) || 100 })
                    }}
                    onBlur={() => updateSettings({ crawl_daily_limit: settings.crawl_daily_limit })}
                    disabled={!canWrite}
                    className="w-32 rounded-md border border-gray-300 px-3 py-2 text-sm"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    预警检测间隔（小时）
                  </label>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min="1"
                      max="12"
                      step="1"
                      value={Math.round(settings.check_alert_interval / 60)}
                      onChange={(e) => updateSettings({ check_alert_interval: parseInt(e.target.value) * 60 })}
                      disabled={!canWrite}
                      className="flex-1"
                    />
                    <span className="w-20 rounded-md border border-gray-300 px-3 py-1.5 text-center text-sm tabular-nums">
                      {Math.round(settings.check_alert_interval / 60)} 小时
                    </span>
                  </div>
                </div>
              </div>

              {canWrite && (
                <div className="mt-6 border-t pt-4">
                  <button
                    onClick={updateCron}
                    disabled={actionLoading === 'cron'}
                    className="rounded-md bg-blue-600 px-5 py-2 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                  >
                    {actionLoading === 'cron' ? '更新中...' : '应用定时任务'}
                  </button>
                  <span className="ml-3 text-xs text-gray-400">修改设置后点击此按钮生效</span>
                </div>
              )}
            </div>
          </div>
        )}

        {tab === 'alert' && (
          <div className="space-y-4">
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="mb-4 text-base font-semibold text-gray-900">推送时段</h2>
              <div className="flex items-center gap-4 flex-wrap">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">开始时间</label>
                  <select
                    value={settings.work_start_hour}
                    onChange={(e) => updateSettings({ work_start_hour: parseInt(e.target.value) })}
                    disabled={!canWrite}
                    className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                  >
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={i}>{String(i).padStart(2, '0')}:00</option>
                    ))}
                  </select>
                </div>
                <span className="text-gray-400 pt-5">至</span>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">结束时间</label>
                  <select
                    value={settings.work_end_hour}
                    onChange={(e) => updateSettings({ work_end_hour: parseInt(e.target.value) })}
                    disabled={!canWrite}
                    className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                  >
                    {Array.from({ length: 24 }, (_, i) => (
                      <option key={i} value={i}>{String(i).padStart(2, '0')}:00</option>
                    ))}
                  </select>
                </div>
              </div>
              <p className="mt-2 text-xs text-gray-400">
                飞书推送仅在工作时段 {settings.work_start_hour}:00-{settings.work_end_hour}:00 进行，周末自动跳过
              </p>
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="mb-4 text-base font-semibold text-gray-900">预警去重</h2>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  同一商品重复推送间隔（小时）
                </label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="1"
                    max="72"
                    step="1"
                    value={settings.alert_dedup_hours}
                    onChange={(e) => updateSettings({ alert_dedup_hours: parseInt(e.target.value) })}
                    disabled={!canWrite}
                    className="flex-1"
                  />
                  <span className="w-20 rounded-md border border-gray-300 px-3 py-1.5 text-center text-sm tabular-nums">
                    {settings.alert_dedup_hours} 小时
                  </span>
                </div>
                <p className="mt-1 text-xs text-gray-400">
                  同一商品在 {settings.alert_dedup_hours} 小时内不重复推送同类预警
                </p>
              </div>
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="mb-4 text-base font-semibold text-gray-900">预警阈值</h2>

              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    低价预警线（元）
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={settings.alert_price}
                    onChange={(e) => {
                      setSettings({ ...settings, alert_price: parseFloat(e.target.value) || 0 })
                    }}
                    onBlur={() => updateSettings({ alert_price: settings.alert_price })}
                    disabled={!canWrite}
                    className="w-32 rounded-md border border-gray-300 px-3 py-2 text-sm"
                  />
                  <span className="ml-2 text-xs text-gray-400">商品价格低于此值触发预警</span>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    销量激增阈值（件）
                  </label>
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={settings.sales_growth_threshold}
                    onChange={(e) => {
                      setSettings({ ...settings, sales_growth_threshold: parseInt(e.target.value) || 0 })
                    }}
                    onBlur={() => updateSettings({ sales_growth_threshold: settings.sales_growth_threshold })}
                    disabled={!canWrite}
                    className="w-32 rounded-md border border-gray-300 px-3 py-2 text-sm"
                  />
                  <span className="ml-2 text-xs text-gray-400">销量增长超过此值触发预警</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {tab === 'push' && (
          <div className="space-y-4">
            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="mb-4 text-base font-semibold text-gray-900">推送渠道</h2>

              {(() => {
                let channels: string[] = []
                try { channels = JSON.parse(settings.push_enabled_channels) } catch {}

                return (
                  <div className="flex items-center gap-6 mb-6">
                    <label className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm ${canWrite ? 'cursor-pointer' : 'cursor-default'} ${
                      channels.includes('feishu') ? 'border-blue-400 bg-blue-50' : 'border-gray-200'
                    }`}>
                      <input
                        type="checkbox"
                        checked={channels.includes('feishu')}
                        onChange={() => togglePushChannel('feishu')}
                        disabled={!canWrite}
                        className="rounded"
                      />
                      <span className="font-medium">飞书</span>
                      <span className="text-xs text-gray-400">卡片消息</span>
                    </label>
                    <label className={`flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm ${canWrite ? 'cursor-pointer' : 'cursor-default'} ${
                      channels.includes('wechat') ? 'border-blue-400 bg-blue-50' : 'border-gray-200'
                    }`}>
                      <input
                        type="checkbox"
                        checked={channels.includes('wechat')}
                        onChange={() => togglePushChannel('wechat')}
                        disabled={!canWrite}
                        className="rounded"
                      />
                      <span className="font-medium">企业微信</span>
                      <span className="text-xs text-gray-400">Markdown</span>
                    </label>
                  </div>
                )
              })()}
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="mb-4 text-base font-semibold text-gray-900">飞书配置</h2>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Webhook 地址</label>
                  <div className="flex gap-3">
                    <input
                      type="text"
                      value={settings.feishu_webhook || ''}
                      onChange={(e) => setSettings({ ...settings, feishu_webhook: e.target.value })}
                      onBlur={() => {
                        if (settings.feishu_webhook !== undefined && canWrite) {
                          updateSettings({ feishu_webhook: settings.feishu_webhook })
                        }
                      }}
                      disabled={!canWrite}
                      placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."
                      className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    {canWrite && (
                      <button
                        onClick={() => testPush('feishu', settings.feishu_webhook || '')}
                        className="rounded-md border border-blue-300 px-4 py-2 text-sm text-blue-600 hover:bg-blue-50"
                      >
                        测试连接
                      </button>
                    )}
                  </div>
                  {testResults.feishu === 'success' && (
                    <p className="mt-1 text-xs text-green-600">✓ 飞书连接测试成功</p>
                  )}
                  {testResults.feishu && testResults.feishu !== 'success' && (
                    <p className="mt-1 text-xs text-red-500">{testResults.feishu}</p>
                  )}
                </div>
              </div>
            </div>

            <div className="rounded-lg border border-gray-200 bg-white p-6">
              <h2 className="mb-4 text-base font-semibold text-gray-900">企业微信配置</h2>
              <div className="space-y-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Webhook 地址</label>
                  <div className="flex gap-3">
                    <input
                      type="text"
                      value={settings.wechat_webhook || ''}
                      onChange={(e) => setSettings({ ...settings, wechat_webhook: e.target.value })}
                      onBlur={() => {
                        if (settings.wechat_webhook !== undefined && canWrite) {
                          updateSettings({ wechat_webhook: settings.wechat_webhook })
                        }
                      }}
                      disabled={!canWrite}
                      placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
                      className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
                    />
                    {canWrite && (
                      <button
                        onClick={() => testPush('wechat', settings.wechat_webhook || '')}
                        className="rounded-md border border-blue-300 px-4 py-2 text-sm text-blue-600 hover:bg-blue-50"
                      >
                        测试连接
                      </button>
                    )}
                  </div>
                  {testResults.wechat === 'success' && (
                    <p className="mt-1 text-xs text-green-600">✓ 微信连接测试成功</p>
                  )}
                  {testResults.wechat && testResults.wechat !== 'success' && (
                    <p className="mt-1 text-xs text-red-500">{testResults.wechat}</p>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
