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
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

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
      setStep('preview'); setPage(1)
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

  // Pagination
  const totalItems = preview?.preview_data.length || 0
  const totalPages = Math.ceil(totalItems / pageSize)
  const pagedData = preview?.preview_data.slice((page - 1) * pageSize, page * pageSize) || []

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
          {/* Stats bar + action buttons in top right */}
          <div style={{ display: 'flex', gap: 20, marginBottom: 8, fontSize: 14, flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
              <span>📄 {preview.file_name}</span>
              <span>总计 <b>{preview.total_count}</b></span>
              <span style={{ color: '#fa8c16' }}>广告 <b>{preview.ad_count}</b></span>
              <span style={{ color: '#16a34a' }}>有效 <b>{preview.valid_count}</b></span>
              <span style={{ color: '#1677ff' }}>已选 <b>{selectedIds.size}</b></span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => { setPreview(null); setStep('upload') }} style={btnSecondary}>重新选择</button>
              <button onClick={confirmImport} disabled={confirming || selectedIds.size === 0} style={btnPrimary}>
                {confirming ? '导入中...' : `确认导入 (${selectedIds.size}条)`}
              </button>
            </div>
          </div>

          {/* Table */}
          <div style={{ maxHeight: 'calc(100vh - 260px)', overflow: 'auto', marginBottom: 8, border: '1px solid #e5e7eb', borderRadius: 8 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ background: '#fafafa', position: 'sticky', top: 0, zIndex: 1 }}>
                  <th style={thStyle}><input type="checkbox" checked={preview && selectedIds.size === preview.preview_data.length} onChange={toggleAll} /></th>
                  <th style={{ ...thStyle, width: 40 }}>#</th>
                  <th style={{ ...thStyle, width: 90 }}>图片</th>
                  <th style={{ ...thStyle, width: 120 }}>商品ID</th>
                  <th style={{ ...thStyle, minWidth: 200 }}>标题</th>
                  <th style={{ ...thStyle, width: 80 }}>现价</th>
                  <th style={{ ...thStyle, width: 70 }}>销量</th>
                  <th style={{ ...thStyle, width: 70 }}>平台</th>
                  <th style={{ ...thStyle, width: 80 }}>店铺类型</th>
                  <th style={{ ...thStyle, width: 90 }}>掌柜</th>
                  <th style={{ ...thStyle, width: 110 }}>店铺</th>
                  <th style={{ ...thStyle, width: 80 }}>地址</th>
                </tr>
              </thead>
              <tbody>
                {pagedData.map((p: any, i: number) => (
                  <tr key={p.product_id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                    <td style={tdStyle}><input type="checkbox" checked={selectedIds.has(p.product_id)} onChange={() => toggleOne(p.product_id)} /></td>
                    <td style={{ ...tdStyle, color: '#999', fontSize: 12 }}>{(page - 1) * pageSize + i + 1}</td>
                    <td style={tdStyle}>
                      {(p.image_url || p.main_image_url) ? (
                        <div style={{ position: 'relative', display: 'inline-block' }} className="img-preview-group">
                          <img src={p.image_url || p.main_image_url} alt=""
                            style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 6, border: '1px solid #f0f0f0', cursor: 'pointer' }}
                            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
                            onMouseEnter={(e) => {
                              const overlay = (e.target as HTMLElement).nextElementSibling as HTMLElement
                              if (overlay) overlay.style.display = 'block'
                            }}
                            onMouseLeave={(e) => {
                              const overlay = (e.target as HTMLElement).nextElementSibling as HTMLElement
                              if (overlay) overlay.style.display = 'none'
                            }} />
                          <div style={{
                            display: 'none', position: 'absolute', left: 80, top: -40, zIndex: 100,
                            border: '2px solid #e5e7eb', borderRadius: 8, background: '#fff',
                            boxShadow: '0 4px 16px rgba(0,0,0,0.15)', padding: 4,
                          }}>
                            <img src={p.image_url || p.main_image_url} alt=""
                              style={{ width: 240, height: 240, objectFit: 'contain', borderRadius: 4 }}
                              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
                          </div>
                        </div>
                      ) : <div style={{ width: 72, height: 72, background: '#f5f5f5', borderRadius: 6 }} />}
                    </td>
                    <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: 12 }}>{p.product_id}</td>
                    <td style={tdStyle}>
                      {p.url ? <a href={p.url.startsWith('http') ? p.url : 'https:' + p.url} target="_blank" rel="noreferrer" style={{ color: '#1677ff' }}>{p.title}</a> : p.title}
                    </td>
                    <td style={{ ...tdStyle, color: '#dc2626', fontWeight: 600 }}>¥{(p.price || 0).toFixed(2)}</td>
                    <td style={tdStyle}>{p.sales?.toLocaleString() || '-'}</td>
                    <td style={tdStyle}>{p.platform || '-'}</td>
                    <td style={tdStyle}>{p.shop_type || '-'}</td>
                    <td style={tdStyle}>{p.seller_name || '-'}</td>
                    <td style={{ ...tdStyle, fontSize: 12 }}>{p.shop_name || p.shop || '-'}</td>
                    <td style={{ ...tdStyle, fontSize: 11, color: '#999' }}>{p.location || '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination + page size at bottom */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
              <div style={{ display: 'flex', gap: 4 }}>
                <button onClick={() => setPage(1)} disabled={page <= 1} style={pageBtnStyle(page <= 1)}>«</button>
                <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1} style={pageBtnStyle(page <= 1)}>‹</button>
                {(() => {
                  const btns = []
                  const start = Math.max(1, page - 2)
                  const end = Math.min(totalPages, page + 2)
                  if (start > 1) { btns.push(<span key="s" style={{ padding: '0 2px', color: '#999' }}>…</span>) }
                  for (let i = start; i <= end; i++) {
                    btns.push(
                      <button key={i} onClick={() => setPage(i)}
                        style={i === page ? { ...pageBtnStyle(false), background: '#1677ff', color: '#fff', borderColor: '#1677ff' } : pageBtnStyle(false)}>
                        {i}
                      </button>
                    )
                  }
                  if (end < totalPages) { btns.push(<span key="e" style={{ padding: '0 2px', color: '#999' }}>…</span>) }
                  return btns
                })()}
                <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages} style={pageBtnStyle(page >= totalPages)}>›</button>
                <button onClick={() => setPage(totalPages)} disabled={page >= totalPages} style={pageBtnStyle(page >= totalPages)}>»</button>
              </div>
              <span style={{ fontSize: 12, color: '#999' }}>第 {page}/{totalPages || 1} 页 · 共 {totalItems} 条</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <span style={{ color: '#666' }}>每页</span>
              <select value={pageSize} onChange={e => { setPageSize(parseInt(e.target.value)); setPage(1) }}
                style={{ padding: '3px 6px', border: '1px solid #d9d9d9', borderRadius: 4, fontSize: 13 }}>
                {[20, 50, 100, 99999].map(s => <option key={s} value={s}>{s >= 99999 ? '全部' : s}</option>)}
              </select>
              <span style={{ color: '#666' }}>条</span>
            </div>
          </div>
        </>
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

const pageBtnStyle = (disabled: boolean): React.CSSProperties => ({
  padding: '3px 10px', border: '1px solid #d9d9d9', borderRadius: 4, background: '#fff',
  cursor: disabled ? 'not-allowed' : 'pointer', fontSize: 13, opacity: disabled ? 0.5 : 1,
  minWidth: 32, textAlign: 'center',
})
const btnPrimary: React.CSSProperties = { padding: '8px 16px', background: '#1677ff', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14 }
const btnSecondary: React.CSSProperties = { padding: '6px 12px', background: '#fff', border: '1px solid #d9d9d9', borderRadius: 6, cursor: 'pointer', fontSize: 13 }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '10px 12px', fontWeight: 600, fontSize: 12, color: '#666', whiteSpace: 'nowrap' }
const tdStyle: React.CSSProperties = { padding: '8px 12px', color: '#555', fontSize: 13 }
