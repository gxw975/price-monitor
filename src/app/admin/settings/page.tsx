'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useState } from 'react'

type Tab = 'push' | 'wechat' | 'users' | 'maintenance'

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

  // Wechat push
  const [wechatEnabled, setWechatEnabled] = useState(false)
  const [wechatSendkey, setWechatSendkey] = useState('')
  const [wechatMasked, setWechatMasked] = useState('')
  const [wechatConfigured, setWechatConfigured] = useState(false)
  const [wechatTesting, setWechatTesting] = useState(false)

  // Users
  const [users, setUsers] = useState<any[]>([])
  const [usersLoading, setUsersLoading] = useState(false)
  const [showUserForm, setShowUserForm] = useState(false)
  const [editUserId, setEditUserId] = useState<number | null>(null)
  const [userForm, setUserForm] = useState({ username: '', password: '', role: 'staff' })
  const isAdmin = user?.role === 'admin'

  const fetchUsers = async () => { setUsersLoading(true)
    try { const r = await apiFetch('/api/users/list'); setUsers(r.items||[]) } catch { /**/ } finally { setUsersLoading(false) } }

  const saveUser = async () => {
    if (!userForm.username.trim()) return
    try {
      if (editUserId) {
        await apiFetch(`/api/users/${editUserId}`, { method: 'PUT', body: JSON.stringify({ username: userForm.username, role: userForm.role }) })
      } else {
        await apiFetch('/api/users/create', { method: 'POST', body: JSON.stringify(userForm) })
      }
      setShowUserForm(false); fetchUsers()
    } catch { /**/ }
  }

  const deleteUser = async (uid: number) => {
    if (!confirm('确定删除该用户？')) return
    try { await apiFetch(`/api/users/${uid}`, { method: 'DELETE' }); fetchUsers() } catch { /**/ }
  }

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
    // Also fetch wechat status
    try {
      const wr = await apiFetch('/api/wechat/status')
      setWechatEnabled(wr.data?.enabled || false)
      setWechatMasked(wr.data?.sendkey_masked || '')
      setWechatConfigured(wr.data?.sendkey_configured || false)
    } catch { /**/ }
  }, [])

  useEffect(() => { fetchSettings() }, [fetchSettings])
  useEffect(() => { if (tab === 'users') fetchUsers() }, [tab])

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
        {[{ key: 'push' as Tab, label: '推送设置' }, { key: 'wechat' as Tab, label: '微信推送' }, { key: 'users' as Tab, label: '用户管理' }, { key: 'maintenance' as Tab, label: '系统维护' }].map(t => (
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

      {tab === 'wechat' && (
        <div style={{ maxWidth: 600 }}>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>个人微信推送</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ padding: 12, border: '1px solid #e5e7eb', borderRadius: 8, background: '#f9fafb' }}>
              <p style={{ fontWeight: 500, marginBottom: 4 }}>使用 Server酱 推送</p>
              <p style={{ color: '#6b7280', fontSize: 13, marginBottom: 8 }}>
                1. 打开 <a href="https://sct.ftqq.com" target="_blank" style={{ color: '#1677ff' }}>sct.ftqq.com</a> 扫码关注公众号
                <br />2. 获取 SendKey 后填入下方
                <br />3. 免费额度：每天 5 条，预警场景足够使用
              </p>
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ fontWeight: 500 }}>启用微信推送</h3>
                <p style={{ color: '#6b7280', fontSize: 13 }}>开启后预警消息将同时推送到微信</p>
              </div>
              <label style={{ position: 'relative', display: 'inline-block', width: 44, height: 24 }}>
                <input type="checkbox" checked={wechatEnabled} onChange={async e => {
                  setWechatEnabled(e.target.checked)
                  try {
                    await apiFetch('/api/wechat/config', {
                      method: 'PUT', body: JSON.stringify({
                        wechat_push_enabled: e.target.checked,
                        wechat_sendkey: wechatSendkey,
                      }),
                    })
                  } catch { /**/ }
                }} style={{ opacity: 0, width: 0, height: 0 }} />
                <span style={{
                  position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0,
                  backgroundColor: wechatEnabled ? '#1677ff' : '#ccc', borderRadius: 24,
                  transition: '.3s',
                }}>
                  <span style={{
                    position: 'absolute', content: '', height: 18, width: 18,
                    left: wechatEnabled ? 23 : 3, bottom: 3,
                    backgroundColor: 'white', borderRadius: '50%', transition: '.3s',
                  }} />
                </span>
              </label>
            </div>

            <div>
              <label style={labelStyle}>Server酱 SendKey</label>
              <div style={{ display: 'flex', gap: 8 }}>
                <input value={wechatSendkey}
                  onChange={e => setWechatSendkey(e.target.value)}
                  onBlur={async () => {
                    if (wechatSendkey) {
                      try {
                        await apiFetch('/api/wechat/config', {
                          method: 'PUT', body: JSON.stringify({
                            wechat_push_enabled: wechatEnabled,
                            wechat_sendkey: wechatSendkey,
                          }),
                        })
                      } catch { /**/ }
                    }
                  }}
                  style={inputStyle} placeholder="SCT123456..." />
              </div>
              {wechatMasked && <p style={{ color: '#6b7280', fontSize: 12, marginTop: 4 }}>已配置: {wechatMasked}</p>}
            </div>

            <button onClick={async () => {
              setWechatTesting(true)
              try {
                const res = await apiFetch('/api/wechat/test', { method: 'POST' })
                setMsg({ type: 'success', text: res.msg || '测试消息发送成功' })
              } catch (err: any) {
                setMsg({ type: 'error', text: '发送失败，请检查 SendKey 是否正确' })
              } finally { setWechatTesting(false) }
            }} disabled={!wechatConfigured || wechatTesting} style={btnPrimary}>
              {wechatTesting ? '发送中...' : '发送测试消息'}
            </button>
          </div>
        </div>
      )}

      {tab === 'users' && (
        <div style={{ maxWidth: 700 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600 }}>用户管理</h3>
            <button onClick={() => { setEditUserId(null); setUserForm({ username: '', password: '', role: 'staff' }); setShowUserForm(true) }} style={btnPrimary}>新增用户</button>
          </div>
          {users.length === 0 ? (
            <p style={{ color: '#999', textAlign: 'center', padding: 40 }} onClick={fetchUsers}>点击加载用户列表</p>
          ) : usersLoading ? <p>加载中...</p> : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
              <thead><tr style={{ background: '#fafafa' }}><th style={thStyle}>用户名</th><th style={thStyle}>角色</th><th style={thStyle}>创建时间</th><th style={thStyle}>操作</th></tr></thead>
              <tbody>
                {users.map((u: any) => (
                  <tr key={u.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                    <td style={tdStyle}>{u.username}</td>
                    <td style={tdStyle}>
                      <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 12, background: u.role === 'admin' ? '#fee2e2' : u.role === 'manager' ? '#fef3c7' : '#e0e7ff', color: u.role === 'admin' ? '#dc2626' : u.role === 'manager' ? '#d97706' : '#3730a3' }}>
                        {u.role === 'admin' ? '管理员' : u.role === 'manager' ? '主管' : '员工'}
                      </span>
                    </td>
                    <td style={tdStyle}>{u.created_at ? new Date(u.created_at).toLocaleDateString('zh-CN') : '-'}</td>
                    <td style={tdStyle}>
                      <button onClick={() => { setEditUserId(u.id); setUserForm({ username: u.username, password: '', role: u.role }); setShowUserForm(true) }} style={{ ...btnSecondary, fontSize: 12, padding: '2px 8px', marginRight: 8 }}>编辑</button>
                      <button onClick={() => deleteUser(u.id)} style={{ fontSize: 12, padding: '2px 8px', color: '#dc2626', border: '1px solid #fecaca', borderRadius: 4, background: '#fff', cursor: 'pointer' }}>删除</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {showUserForm && (
            <div style={modalOverlay}>
              <div style={{ ...modalContent, width: 400 }}>
                <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 16 }}>{editUserId ? '编辑' : '新增'}用户</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <div><label style={labelStyle}>用户名</label><input value={userForm.username} onChange={e => setUserForm({ ...userForm, username: e.target.value })} style={inputStyle} /></div>
                  {!editUserId && <div><label style={labelStyle}>密码</label><input type="password" value={userForm.password} onChange={e => setUserForm({ ...userForm, password: e.target.value })} style={inputStyle} /></div>}
                  <div><label style={labelStyle}>角色</label><select value={userForm.role} onChange={e => setUserForm({ ...userForm, role: e.target.value })} style={{ ...inputStyle, width: '100%' }}>
                    <option value="admin">管理员</option><option value="manager">主管</option><option value="staff">员工</option>
                  </select></div>
                </div>
                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
                  <button onClick={() => setShowUserForm(false)} style={btnSecondary}>取消</button>
                  <button onClick={saveUser} style={btnPrimary}>保存</button>
                </div>
              </div>
            </div>
          )}
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
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '8px 12px', fontWeight: 600, fontSize: 13 }
const tdStyle: React.CSSProperties = { padding: '8px 12px', color: '#555', fontSize: 13 }
const modalOverlay: React.CSSProperties = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000 }
const modalContent: React.CSSProperties = { background: '#fff', borderRadius: 8, padding: 24, maxHeight: '85vh', overflow: 'auto' }
