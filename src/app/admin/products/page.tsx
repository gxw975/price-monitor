'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useState } from 'react'

interface MonitorProduct { id: number; name: string }
interface Product {
  product_id: string; title: string; shop_name: string; main_image_url: string
  price: number; sales: number; shop: string; url: string
  placeholder_type?: string; is_approved: boolean
}
interface PreviewData {
  file_name: string; total_count: number; ad_count: number; valid_count: number
  preview_data: Product[]
}

export default function ProductsPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'

  const [monitorProducts, setMonitorProducts] = useState<MonitorProduct[]>([])
  const [selectedMp, setSelectedMp] = useState<number | null>(null)
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)

  // 导入流程状态
  const [uploadVisible, setUploadVisible] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState(false)
  const [importResult, setImportResult] = useState<string | null>(null)

  const fetchMonitorProducts = useCallback(async () => {
    try { const res = await apiFetch('/api/monitor-products/'); setMonitorProducts(res.items || []) } catch { /**/ }
  }, [])

  const fetchProducts = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/api/product-keywords/products?limit=200')
      setProducts(res.items || [])
    } catch { /**/ } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchMonitorProducts(); fetchProducts() }, [fetchMonitorProducts, fetchProducts])

  const handleUpload = async (file: File) => {
    if (!selectedMp) { alert('请先选择监控商品'); return }
    setUploading(true); setImportResult(null)
    const formData = new FormData(); formData.append('file', file)
    try {
      const token = localStorage.getItem('token')
      const res = await fetch(`/api/products/import-excel/${selectedMp}`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: formData,
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || '解析失败')
      const data = json.data as PreviewData
      setPreview(data)
      setSelectedIds(new Set(data.preview_data.map(p => p.product_id)))
    } catch (err: any) { alert(err.message) } finally { setUploading(false) }
  }

  const toggleProduct = (pid: string) => {
    const next = new Set(selectedIds)
    if (next.has(pid)) next.delete(pid) else next.add(pid)
    setSelectedIds(next)
  }
  const toggleAll = () => {
    if (!preview) return
    if (selectedIds.size === preview.preview_data.length) setSelectedIds(new Set())
    else setSelectedIds(new Set(preview.preview_data.map(p => p.product_id)))
  }

  const confirmImport = async () => {
    if (!selectedMp || !preview || selectedIds.size === 0) return
    setConfirming(true)
    try {
      const token = localStorage.getItem('token')
      const res = await fetch(`/api/products/confirm-import/${selectedMp}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          file_name: preview.file_name,
          selected_product_ids: Array.from(selectedIds),
        }),
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || '导入失败')
      const d = json.data
      setImportResult(`导入完成！成功 ${d.import_result.success_count} 条，预警 ${d.alert_result.sent} 条`)
      setPreview(null); setUploadVisible(false); fetchProducts()
    } catch (err: any) { alert(err.message) } finally { setConfirming(false) }
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>商品管理</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          {canWrite && (
            <button onClick={() => { setUploadVisible(true); setPreview(null); setImportResult(null) }} style={btnPrimary}>
              导入 DTS Excel
            </button>
          )}
          <button onClick={fetchProducts} style={btnSecondary}>刷新</button>
        </div>
      </div>

      {/* 导入弹窗 */}
      {uploadVisible && (
        <div style={modalOverlay}>
          <div style={{ ...modalContent, width: preview ? 900 : 480 }}>
            <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }}>导入商品数据</h2>

            {!preview ? (
              <>
                <div style={{ marginBottom: 16 }}>
                  <label style={labelStyle}>选择监控商品</label>
                  <select value={selectedMp || ''} onChange={e => setSelectedMp(parseInt(e.target.value) || null)}
                    style={{ ...selectStyle, width: '100%' }}>
                    <option value="">请选择...</option>
                    {monitorProducts.map(mp => <option key={mp.id} value={mp.id}>{mp.name}</option>)}
                  </select>
                </div>
                <p style={{ color: '#666', fontSize: 13, marginBottom: 8 }}>请上传店透视（DTS）导出的Excel文件</p>
                <p style={{ color: '#fa8c16', fontSize: 12, marginBottom: 16 }}>仅支持.xlsx/.xls，大小不超过10MB</p>
                <input type="file" accept=".xlsx,.xls" disabled={uploading} onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f) }}
                  style={{ display: 'block', marginBottom: 12 }} />
                {uploading && <p style={{ color: '#1677ff' }}>正在解析文件...</p>}
              </>
            ) : (
              <>
                <div style={{ display: 'flex', gap: 20, marginBottom: 16, fontSize: 14 }}>
                  <span>📄 {preview.file_name}</span>
                  <span>📊 总计 <b>{preview.total_count}</b> 条</span>
                  <span style={{ color: '#fa8c16' }}>🚫 广告 <b>{preview.ad_count}</b> 条</span>
                  <span style={{ color: '#16a34a' }}>✅ 有效 <b>{preview.valid_count}</b> 条</span>
                  <span>☑ 已选 <b>{selectedIds.size}</b> 条</span>
                </div>
                <div style={{ maxHeight: 400, overflow: 'auto', marginBottom: 12 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead>
                      <tr style={{ background: '#fafafa', borderBottom: '2px solid #e5e7eb', position: 'sticky', top: 0 }}>
                        <th style={thStyle}><input type="checkbox" checked={selectedIds.size === preview.preview_data.length}
                          onChange={toggleAll} /></th>
                        <th style={thStyle}>图片</th><th style={thStyle}>标题</th>
                        <th style={thStyle}>价格</th><th style={thStyle}>销量</th><th style={thStyle}>店铺</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.preview_data.map(p => (
                        <tr key={p.product_id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                          <td style={tdStyle}><input type="checkbox" checked={selectedIds.has(p.product_id)}
                            onChange={() => toggleProduct(p.product_id)} /></td>
                          <td style={tdStyle}>
                            {p.main_image_url ? <img src={p.main_image_url} alt="" style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 4 }} />
                              : <div style={{ width: 40, height: 40, background: '#f5f5f5', borderRadius: 4 }} />}
                          </td>
                          <td style={{ ...tdStyle, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.title}</td>
                          <td style={{ ...tdStyle, color: '#dc2626', fontWeight: 600 }}>¥{(p.price || 0).toFixed(2)}</td>
                          <td style={tdStyle}>{p.sales?.toLocaleString() || '-'}</td>
                          <td style={tdStyle}>{p.shop_name || p.shop || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                  <button onClick={() => setPreview(null)} style={btnSecondary} disabled={confirming}>返回</button>
                  <button onClick={confirmImport} disabled={confirming || selectedIds.size === 0} style={btnPrimary}>
                    {confirming ? '导入中...' : `确认导入 (${selectedIds.size}条)`}
                  </button>
                </div>
              </>
            )}

            {importResult && (
              <div style={{ marginTop: 12, padding: 10, background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 6, color: '#166534', fontSize: 14 }}>
                {importResult}
              </div>
            )}

            <div style={{ marginTop: 16, textAlign: 'right' }}>
              <button onClick={() => { setUploadVisible(false); setPreview(null); setImportResult(null) }} style={btnSecondary}>关闭</button>
            </div>
          </div>
        </div>
      )}

      {/* 商品列表 */}
      {loading ? <p style={{ color: '#999' }}>加载中...</p> : products.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
          <p>暂无商品数据</p>
          {canWrite && <p style={{ marginTop: 8 }}>请创建监控商品并导入 DTS Excel</p>}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ background: '#fafafa', borderBottom: '1px solid #f0f0f0' }}>
                <th style={thStyle}>图片</th><th style={thStyle}>商品ID</th><th style={thStyle}>标题</th>
                <th style={thStyle}>店铺</th><th style={thStyle}>审核</th>
              </tr>
            </thead>
            <tbody>
              {products.map(p => (
                <tr key={p.product_id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                  <td style={tdStyle}>
                    {p.main_image_url ? <img src={p.main_image_url} alt="" style={{ width: 50, height: 50, objectFit: 'cover', borderRadius: 4 }} />
                      : <div style={{ width: 50, height: 50, background: '#f5f5f5', borderRadius: 4 }} />}
                  </td>
                  <td style={tdStyle}><a href={`/admin/products/${p.product_id}`} style={{ color: '#1677ff' }}>{p.product_id}</a></td>
                  <td style={{ ...tdStyle, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.title}</td>
                  <td style={tdStyle}>{p.shop_name}</td>
                  <td style={tdStyle}>
                    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 12, background: p.is_approved ? '#f6ffed' : '#fff7e6',
                      color: p.is_approved ? '#52c41a' : '#fa8c16', border: `1px solid ${p.is_approved ? '#b7eb8f' : '#ffd591'}` }}>
                      {p.is_approved ? '已审核' : '未审核'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const btnPrimary: React.CSSProperties = { padding: '8px 16px', backgroundColor: '#1677ff', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14 }
const btnSecondary: React.CSSProperties = { padding: '6px 12px', backgroundColor: '#fff', border: '1px solid #d9d9d9', borderRadius: 6, cursor: 'pointer', fontSize: 13 }
const selectStyle: React.CSSProperties = { padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, outline: 'none' }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4, color: '#374151' }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '10px 14px', fontWeight: 600, color: '#333' }
const tdStyle: React.CSSProperties = { padding: '10px 14px', color: '#555' }
const modalOverlay: React.CSSProperties = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.45)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000 }
const modalContent: React.CSSProperties = { backgroundColor: '#fff', borderRadius: 8, padding: 24, maxHeight: '85vh', overflow: 'auto' }
