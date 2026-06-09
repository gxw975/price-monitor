'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useParams, useRouter } from 'next/navigation'
import { useState } from 'react'

interface PreviewData { file_name: string; total_count: number; ad_count: number; valid_count: number; preview_data: any[] }

export default function ImportPage() {
  const params = useParams(); const router = useRouter()
  const mpId = parseInt(params.id as string)
  const { user } = useAuth()

  const [uploading, setUploading] = useState(false)
  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [step, setStep] = useState<'upload' | 'preview' | 'login' | 'done'>('upload')

  const handleUpload = async (file: File) => {
    setUploading(true); setResult(null)
    const fd = new FormData(); fd.append('file', file)
    try {
      const token = localStorage.getItem('auth_token')
      const res = await fetch(`/api/monitor-products/${mpId}/import`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd,
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || '解析失败')
      const d = json.data as PreviewData
      setPreview(d); setSelectedIds(new Set(d.preview_data.map(p => p.product_id)))
      setStep('preview')
    } catch (err: any) { alert(err.message) } finally { setUploading(false) }
  }

  const toggleAll = () => {
    if (!preview) return
    if (selectedIds.size === preview.preview_data.length) setSelectedIds(new Set())
    else setSelectedIds(new Set(preview.preview_data.map(p => p.product_id)))
  }

  const toggleOne = (pid: string) => {
    const next = new Set(selectedIds); next.has(pid) ? next.delete(pid) : next.add(pid); setSelectedIds(next)
  }

  const confirmImport = async () => {
    if (!preview || selectedIds.size === 0) return
    setConfirming(true)

    // Check login status
    try {
      const token = localStorage.getItem('auth_token')
      const statusRes = await fetch('/api/taobao/status', { headers: { Authorization: `Bearer ${token}` } })
      const statusJson = await statusRes.json()
      if (!statusJson.logged_in) {
        if (confirm('淘宝未登录，是否打开登录页扫码登录？')) {
          await fetch('/api/taobao/login/start', { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
          setStep('login')
        }
        setConfirming(false)
        return
      }
    } catch { /* continue even if status check fails */ }

    // Confirm import
    try {
      const token = localStorage.getItem('auth_token')
      const res = await fetch(`/api/monitor-products/${mpId}/import/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ file_name: preview.file_name, selected_product_ids: Array.from(selectedIds) }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || '导入失败')
      setResult(`导入完成！成功 ${json.data.import_result.success_count} 条，预警 ${json.data.alert_result.sent} 条`)
      setStep('done')
    } catch (err: any) { alert(err.message) } finally { setConfirming(false) }
  }

  const checkLogin = async () => {
    try {
      const token = localStorage.getItem('auth_token')
      const res = await fetch('/api/taobao/status', { headers: { Authorization: `Bearer ${token}` } })
      const json = await res.json()
      if (json.logged_in) { setStep('preview'); alert('登录成功！请点击确认导入') }
      else alert('尚未登录，请在Chrome窗口中完成扫码')
    } catch { alert('检查登录状态失败') }
  }

  return (
    <div style={{ padding: 24 }}>
      <a href={`/admin/monitor-products/${mpId}`} style={{ color: '#1677ff', fontSize: 13 }}>← 返回商品详情</a>
      <h1 style={{ fontSize: 22, fontWeight: 700, marginTop: 4, marginBottom: 20 }}>导入数据</h1>

      {step === 'upload' && (
        <div style={{ maxWidth: 500 }}>
          <p style={{ color: '#666', fontSize: 14, marginBottom: 16 }}>上传店透视（DTS）导出的 Excel 文件，系统将自动清洗广告数据。</p>
          <input type="file" accept=".xlsx,.xls" disabled={uploading}
            onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f) }}
            style={{ display: 'block', marginBottom: 12 }} />
          {uploading && <p style={{ color: '#1677ff' }}>正在解析文件...</p>}
        </div>
      )}

      {step === 'preview' && preview && (
        <>
          <div style={{ display: 'flex', gap: 20, marginBottom: 12, fontSize: 14, flexWrap: 'wrap' }}>
            <span>📄 {preview.file_name}</span>
            <span>总计 <b>{preview.total_count}</b></span>
            <span style={{ color: '#fa8c16' }}>广告 <b>{preview.ad_count}</b></span>
            <span style={{ color: '#16a34a' }}>有效 <b>{preview.valid_count}</b></span>
            <span>已选 <b>{selectedIds.size}</b></span>
          </div>
          <div style={{ maxHeight: 400, overflow: 'auto', marginBottom: 12 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#fafafa', position: 'sticky', top: 0 }}>
                  <th style={thStyle}><input type="checkbox" checked={selectedIds.size === preview.preview_data.length} onChange={toggleAll} /></th>
                  <th style={thStyle}>图片</th><th style={thStyle}>商品ID</th><th style={thStyle}>标题</th><th style={thStyle}>价格</th><th style={thStyle}>销量</th><th style={thStyle}>掌柜</th><th style={thStyle}>店铺</th><th style={thStyle}>地址</th>
                </tr>
              </thead>
              <tbody>
                {preview.preview_data.map((p: any) => (
                  <tr key={p.product_id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                    <td style={tdStyle}><input type="checkbox" checked={selectedIds.has(p.product_id)} onChange={() => toggleOne(p.product_id)} /></td>
                    <td style={tdStyle}>{(p.image_url || p.main_image_url) ? <img src={p.image_url || p.main_image_url} alt="" style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 4 }} onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} /> : <div style={{ width: 40, height: 40, background: '#f5f5f5' }} />}</td>
                    <td style={tdStyle}><span style={{ fontSize: 12, color: '#999' }}>{p.product_id}</span></td>
                    <td style={{ ...tdStyle, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {p.url ? <a href={p.url.startsWith('http') ? p.url : 'https:' + p.url} target="_blank" rel="noreferrer" style={{ color: '#1677ff' }}>{p.title}</a> : p.title}
                    </td>
                    <td style={{ ...tdStyle, color: '#dc2626', fontWeight: 600 }}>¥{(p.price || 0).toFixed(2)}</td>
                    <td style={tdStyle}>{p.sales?.toLocaleString() || '-'}</td>
                    <td style={tdStyle}>{p.seller_name || '-'}</td>
                    <td style={tdStyle}>{p.shop_name || p.shop || '-'}</td>
                    <td style={{ ...tdStyle, fontSize: 11, color: '#999' }}>{p.location || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button onClick={() => { setPreview(null); setStep('upload') }} style={btnSecondary}>重新选择</button>
            <button onClick={confirmImport} disabled={confirming || selectedIds.size === 0} style={btnPrimary}>
              {confirming ? '导入中...' : `确认导入 (${selectedIds.size}条)`}
            </button>
          </div>
        </>
      )}

      {step === 'login' && (
        <div style={{ maxWidth: 500, textAlign: 'center' }}>
          <p style={{ fontSize: 16, marginBottom: 12 }}>请在 Chrome 窗口中完成淘宝扫码登录</p>
          <p style={{ color: '#666', fontSize: 13, marginBottom: 16 }}>点击下方按钮检查登录状态</p>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
            <button onClick={checkLogin} style={btnPrimary}>检查登录状态</button>
            <button onClick={() => setStep('preview')} style={btnSecondary}>跳过</button>
          </div>
        </div>
      )}

      {step === 'done' && (
        <div style={{ maxWidth: 500, textAlign: 'center' }}>
          <p style={{ fontSize: 18, color: '#16a34a', marginBottom: 12 }}>✅ 导入完成</p>
          <p style={{ color: '#666', marginBottom: 16 }}>{result}</p>
          <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
            <button onClick={() => router.push(`/admin/monitor-products/${mpId}`)} style={btnPrimary}>查看商品详情</button>
            <button onClick={() => { setPreview(null); setResult(null); setStep('upload') }} style={btnSecondary}>继续导入</button>
          </div>
        </div>
      )}
    </div>
  )
}

const btnPrimary: React.CSSProperties = { padding: '8px 16px', background: '#1677ff', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14 }
const btnSecondary: React.CSSProperties = { padding: '6px 12px', background: '#fff', border: '1px solid #d9d9d9', borderRadius: 6, cursor: 'pointer', fontSize: 13 }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '10px 14px', fontWeight: 600, fontSize: 13 }
const tdStyle: React.CSSProperties = { padding: '10px 14px', color: '#555', fontSize: 13 }
