'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useState } from 'react'

type Tab = 'push' | 'maintenance'

export default function SettingsPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'
  const [tab, setTab] = useState<Tab>('push')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  // Push settings
  const [feishuWebhook, setFeishuWebhook] = useState('')
  const [wechatWebhook, setWechatWebhook] = useState('')
  const [pushChannels, setPushChannels] = useState<string[]>(['feishu'])
  const [workStart, setWorkStart] = useState(9)
  const [workEnd, setWorkEnd] = useState(18)

  // Maintenance
  const [actionLoading, setActionLoading] = useState('')

  const fetchSettings = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/api/settings')
      const s = res.settings || res
      setFeishuWebhook(s.feishu_webhook || '')
      setWechatWebhook(s.wechat_webhook || '')
      try { setPushChannels(JSON.parse(s.push_enabled_channels || '["feishu"]')) } catch { setPushChannels(['feishu']) }
      setWorkStart(s.work_start_hour || 9)
      setWorkEnd(s.work_end_hour || 18)
    } catch { /**/ } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchSettings() }, [fetchSettings])

  const saveSettings = async () => {
    setSaving(true)
    try {
      await apiFetch('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({
          feishu_webhook: feishuWebhook, wechat_webhook: wechatWebhook,
          push_enabled_channels: JSON.stringify(pushChannels),
          work_start_hour: workStart, work_end_hour: workEnd,
        }),
      })
      setMsg({ type: 'success', text: '保存成功' })
    } catch { setMsg({ type: 'error', text: '保存失败' }) } finally { setSaving(false) }
  }

  const maintenanceAction = async (action: string) => {
    setActionLoading(action)
    try { await apiFetch(`/api/diagnostics/maintenance/${action}`, { method: 'POST' }); setMsg({ type: 'success', text: '操作成功' }) }
    catch { setMsg({ type: 'error', text: '操作失败' }) }
    finally { setActionLoading('') }
  }

  if (loading) return <div style={{ padding: 24, color: '#999' }}>加载中...</div>

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 20 }}>系统设置</h1>

      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid #e5e7eb', marginBottom: 20 }}>
        {[{ key: 'push' as Tab, label: '推送设置' }, { key: 'maintenance' as Tab, label: '系统维护' }].map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{
            padding: '10px 16px', border: 'none', background: 'none', cursor: 'pointer',
            borderBottom: tab === t.key ? '2px solid #1677ff' : '2px solid transparent',
            color: tab === t.key ? '#1677ff' : '#6b7280', fontWeight: tab === t.key ? 600 : 400, fontSize: 14,
          }}>{t.label}</button>
        ))}
      </div>

      {msg && (
        <div style={{ padding: '8px 12px', borderRadius: 6, marginBottom: 16, fontSize: 13,
          background: msg.type === 'success' ? '#f0fdf4' : '#fef2f2', color: msg.type === 'success' ? '#166534' : '#991b1b',
          border: `1px solid ${msg.type === 'success' ? '#bbf7d0' : '#fecaca'}` }}>
          {msg.text}
          <button onClick={() => setMsg(null)} style={{ marginLeft: 8, background: 'none', border: 'none', cursor: 'pointer' }}>×</button>
        </div>
      )}

      {tab === 'push' && (
        <div style={{ maxWidth: 600 }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>推送渠道配置</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div>
              <label style={labelStyle}>飞书 Webhook URL</label>
              <input value={feishuWebhook} onChange={e => setFeishuWebhook(e.target.value)} style={inputStyle} placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..." />
            </div>
            <div>
              <label style={labelStyle}>企业微信 Webhook URL</label>
              <input value={wechatWebhook} onChange={e => setWechatWebhook(e.target.value)} style={inputStyle} placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..." />
            </div>
            <div>
              <label style={labelStyle}>推送渠道</label>
              <div style={{ display: 'flex', gap: 16 }}>
                {['feishu', 'wechat'].map(ch => (
                  <label key={ch} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 14 }}>
                    <input type="checkbox" checked={pushChannels.includes(ch)}
                      onChange={() => setPushChannels(prev => prev.includes(ch) ? prev.filter(c => c !== ch) : [...prev, ch])} />
                    {ch === 'feishu' ? '飞书' : '企业微信'}
                  </label>
                ))}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 16 }}>
              <div>
                <label style={labelStyle}>工作开始时间</label>
                <input type="number" min={0} max={23} value={workStart} onChange={e => setWorkStart(parseInt(e.target.value) || 0)} style={{ ...inputStyle, width: 80 }} />
              </div>
              <div>
                <label style={labelStyle}>工作结束时间</label>
                <input type="number" min={0} max={23} value={workEnd} onChange={e => setWorkEnd(parseInt(e.target.value) || 0)} style={{ ...inputStyle, width: 80 }} />
              </div>
            </div>
            <p style={{ color: '#6b7280', fontSize: 12 }}>推送仅在工作日 {workStart}:00-{workEnd}:00 发送</p>
            <button onClick={saveSettings} disabled={saving} style={btnPrimary}>{saving ? '保存中...' : '保存设置'}</button>
          </div>
        </div>
      )}

      {tab === 'maintenance' && (
        <div style={{ maxWidth: 600 }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>系统维护</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {canWrite && (
              <>
                <div style={{ padding: 12, border: '1px solid #e5e7eb', borderRadius: 8 }}>
                  <p style={{ fontWeight: 500, marginBottom: 8 }}>数据库备份</p>
                  <button onClick={() => maintenanceAction('backup')} disabled={actionLoading === 'backup'} style={btnPrimary}>
                    {actionLoading === 'backup' ? '备份中...' : '立即备份'}
                  </button>
                </div>
                <div style={{ padding: 12, border: '1px solid #e5e7eb', borderRadius: 8 }}>
                  <p style={{ fontWeight: 500, marginBottom: 8 }}>清理日志</p>
                  <button onClick={() => maintenanceAction('clean-logs')} disabled={actionLoading === 'clean-logs'} style={btnPrimary}>
                    {actionLoading === 'clean-logs' ? '清理中...' : '清理旧日志'}
                  </button>
                </div>
                <div style={{ padding: 12, border: '1px solid #e5e7eb', borderRadius: 8 }}>
                  <p style={{ fontWeight: 500, marginBottom: 8 }}>重启服务</p>
                  <button onClick={() => { if (confirm('确定重启后端服务？')) maintenanceAction('restart') }} disabled={actionLoading === 'restart'} style={{ ...btnPrimary, background: '#dc2626' }}>
                    {actionLoading === 'restart' ? '重启中...' : '重启 FastAPI'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const btnPrimary: React.CSSProperties = { padding: '8px 16px', background: '#1677ff', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14 }
const inputStyle: React.CSSProperties = { padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, width: '100%' }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4, color: '#374151' }
