'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

interface MonitorProduct {
  id: number; name: string; brand: string | null; description: string | null
  price_threshold_bag: number | null; price_threshold_can: number | null
  price_threshold_mix: number | null; sales_threshold: number | null
  import_count: number; last_import_time: string | null; unhandled_alert_count: number
  platform: string
}

interface SkuCategory { id: number; monitor_product_id: number; name: string; unit: string; conversion_factor: number }

export default function MonitorProductsPage() {
  const { user } = useAuth(); const router = useRouter()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'
  const [products, setProducts] = useState<MonitorProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [showForm, setShowForm] = useState(false); const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState<Record<string, any>>({})
  const [saving, setSaving] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [catLoading, setCatLoading] = useState(false)
  const [catName, setCatName] = useState('')
  const [catUnit, setCatUnit] = useState('')
  const [catFactor, setCatFactor] = useState('1.0')
  const [categories, setCategories] = useState<SkuCategory[]>([])
  const [deleteTarget, setDeleteTarget] = useState<{id: number; name: string} | null>(null)

  // Batch import
  const [batchVisible, setBatchVisible] = useState(false)
  const [batchStep, setBatchStep] = useState<'select' | 'parse' | 'importing'>('select')
  const [batchFiles, setBatchFiles] = useState<File[]>([])
  const [batchParsing, setBatchParsing] = useState(false)
  const [batchFileInfos, setBatchFileInfos] = useState<any[]>([])
  const [batchMapping, setBatchMapping] = useState<Record<number, number>>({})
  const [batchImporting, setBatchImporting] = useState(false)
  const [batchProgress, setBatchProgress] = useState({ current: 0, total: 0 })
  const [batchResults, setBatchResults] = useState<any[]>([])

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try { const res = await apiFetch('/api/monitor-products/'); setProducts(res.items || []) } catch { /**/ } finally { setLoading(false) }
  }, [])
  useEffect(() => { fetchAll() }, [fetchAll])

  const openCreate = () => { setEditId(null); setForm({}); setShowForm(true) }
  const openEdit = (p: MonitorProduct) => { setEditId(p.id); setForm(p as any); setShowForm(true) }
  const save = async () => {
    if (!form.name?.trim()) { alert('请输入商品名称'); return }
    setSaving(true)
    try {
      // Clean form data: empty string → null, number fields → float
      const clean: Record<string, any> = {}
      for (const [k, v] of Object.entries(form)) {
        if (v === '' || v === undefined || v === null) { clean[k] = null; continue }
        if (['price_threshold_bag','price_threshold_can','price_threshold_mix','sales_threshold'].includes(k)) {
          clean[k] = parseFloat(v as string) || null
        } else { clean[k] = v }
      }
      const url = editId ? `/api/monitor-products/${editId}` : '/api/monitor-products'
      const method = editId ? 'PUT' : 'POST'
      const res = await apiFetch(url, { method, body: JSON.stringify(clean) })
      if (!res.success) { alert('保存失败: ' + (res.detail || JSON.stringify(res))); return }
      setShowForm(false); fetchAll()
    } catch (err: any) { alert('保存失败: ' + (err?.message || err)) } finally { setSaving(false) }
  }
  const deleteMp = async () => {
    if (!deleteTarget) return
    const id = deleteTarget.id
    try { await apiFetch(`/api/monitor-products/${id}`, { method: 'DELETE' }); fetchAll(); setDeleteTarget(null) } catch { /**/ }
  }
  const toggleExpand = async (id: number) => {
    if (expandedId === id) { setExpandedId(null); return }
    setExpandedId(id); setCatLoading(true)
    try { const res = await apiFetch(`/api/monitor-products/${id}/sku-categories`); setCategories(res.items || []) }
    catch { alert('加载分类失败，请检查权限'); setExpandedId(null) }
    finally { setCatLoading(false) }
  }
  const addCat = async () => {
    if (!catName.trim() || !expandedId) { alert('请输入分类名称'); return }
    try {
      await apiFetch(`/api/monitor-products/${expandedId}/sku-categories`, {
        method: 'POST', body: JSON.stringify({ name: catName.trim(), unit: catUnit.trim(), conversion_factor: parseFloat(catFactor) || 1 }),
      })
      setCatName(''); setCatUnit(''); setCatFactor('1.0')
      const res = await apiFetch(`/api/monitor-products/${expandedId}/sku-categories`); setCategories(res.items || [])
    } catch { alert('添加分类失败') }
  }
  const delCat = async (catId: number) => {
    if (!expandedId) return
    if (!confirm('确定删除该分类？')) return
    try { await apiFetch(`/api/monitor-products/${expandedId}/sku-categories/${catId}`, { method: 'DELETE' }); const res = await apiFetch(`/api/monitor-products/${expandedId}/sku-categories`); setCategories(res.items || []) } catch { alert('删除失败') }
  }

  // ── Batch Import Handlers ──
  const handleBatchFiles = (fl: FileList | null) => {
    if (!fl || fl.length === 0) return
    const arr = Array.from(fl).filter(f => f.name.endsWith('.xlsx') || f.name.endsWith('.xls'))
    setBatchFiles(arr); setBatchMapping({})
    arr.forEach((f, i) => {
      const name = f.name.replace(/\.[^.]+$/, '').replace(/[_\-]+/g, ' ')
      const match = products.find(p => name.includes(p.name) || p.name.includes(name))
      if (match) setBatchMapping(prev => ({ ...prev, [i]: match.id }))
    })
  }

  const handleBatchParse = async () => {
    if (batchFiles.length === 0) { alert('请先选择文件'); return }
    setBatchParsing(true); setBatchFileInfos([])
    const infos: any[] = []
    const token = localStorage.getItem('auth_token')
    for (let i = 0; i < batchFiles.length; i++) {
      const file = batchFiles[i]
      const fd = new FormData(); fd.append('file', file)
      try {
        const res = await fetch(`/api/monitor-products/${batchMapping[i] || products[0]?.id || 1}/import`, {
          method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd,
        })
        const json = await res.json()
        infos.push({ index: i, name: file.name, size: file.size, data: json.data, error: null })
      } catch (e: any) {
        infos.push({ index: i, name: file.name, size: file.size, data: null, error: e.message || '解析失败' })
      }
    }
    setBatchFileInfos(infos); setBatchParsing(false); setBatchStep('parse')
  }

  const handleBatchImport = async () => {
    setBatchImporting(true); setBatchStep('importing')
    setBatchProgress({ current: 0, total: batchFiles.length })
    setBatchResults([])
    const token = localStorage.getItem('auth_token')
    const mappings = batchFiles.map((_, i) => ({ file_index: i, monitor_product_id: batchMapping[i] || 0 }))
    const fd = new FormData()
    batchFiles.forEach(f => fd.append('files', f))
    fd.append('mappings_json', JSON.stringify(mappings))

    try {
      const res = await fetch('/api/monitor-products/batch-import', {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: fd,
      })
      const json = await res.json()
      setBatchResults(json.data?.results || [])
      setBatchProgress({ current: batchFiles.length, total: batchFiles.length })
    } catch (e: any) {
      alert('批量导入失败: ' + (e.message || '网络错误'))
    } finally { setBatchImporting(false) }
  }

  const closeBatch = () => { setBatchVisible(false); setBatchStep('select'); setBatchFiles([]); setBatchFileInfos([]); setBatchResults([]); fetchAll() }

  const filtered = products.filter(p => {
    if (!search) return true
    const s = search.toLowerCase()
    return p.name.toLowerCase().includes(s) || (p.brand || '').toLowerCase().includes(s)
  })

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>商品监控</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索名称/品牌..."
            style={{ padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, width: 180 }} />
          {canWrite && <button onClick={openCreate} style={btnPrimary}>新增监控商品</button>}
          {canWrite && <button onClick={() => { setBatchVisible(true); setBatchStep('select') }} style={btnSecondary}>批量导入</button>}
        </div>
      </div>

      {loading ? <p style={{ color: '#999' }}>加载中...</p> : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
          <p>暂无监控商品</p>
          {canWrite && <p style={{ marginTop: 8 }}>点击「新增监控商品」开始</p>}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: '#fafafa', borderBottom: '2px solid #e5e7eb' }}>
                <th style={thStyle}>名称</th><th style={thStyle}>平台</th><th style={thStyle}>品牌</th>
                <th style={thStyle}>袋装红线</th><th style={thStyle}>罐装红线</th><th style={thStyle}>混合装红线</th>
                <th style={thStyle}>销量红线</th><th style={thStyle}>导入</th><th style={thStyle}>预警</th>
                <th style={thStyle}>操作</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(p => (<>{/* Fragment wrapper */}
                <tr key={p.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                  <td style={tdStyle}>
                    <a href={`/admin/monitor-products/${p.id}`} style={{ color: '#1677ff', fontWeight: 500 }}>{p.name}</a>
                  </td>
                  <td style={tdStyle}>
                    <span style={{ padding: '1px 8px', borderRadius: 10, fontSize: 11, fontWeight: 500,
                      background: (p.platform || 'taobao') === 'jd' ? '#fee2e2' : '#fff7ed',
                      color: (p.platform || 'taobao') === 'jd' ? '#dc2626' : '#ea580c',
                    }}>{(p.platform || 'taobao') === 'jd' ? '京东' : '淘天'}</span>
                  </td>
                  <td style={tdStyle}>{p.brand || '-'}</td>
                  <td style={tdStyle}>{p.price_threshold_bag != null ? `¥${p.price_threshold_bag}` : '-'}</td>
                  <td style={tdStyle}>{p.price_threshold_can != null ? `¥${p.price_threshold_can}` : '-'}</td>
                  <td style={tdStyle}>{p.price_threshold_mix != null ? `¥${p.price_threshold_mix}` : '-'}</td>
                  <td style={tdStyle}>{p.sales_threshold != null ? `${p.sales_threshold}/天` : '-'}</td>
                  <td style={tdStyle}>{p.import_count}</td>
                  <td style={tdStyle}>
                    {p.unhandled_alert_count > 0 ? <span style={{ color: '#dc2626', fontWeight: 600 }}>{p.unhandled_alert_count}</span> : '0'}
                  </td>
                  <td style={tdStyle}>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      <button onClick={() => router.push(`/admin/monitor-products/${p.id}/import`)} style={{ ...btnSmall, background: '#16a34a', color: '#fff' }}>导入</button>
                      <button onClick={() => router.push(`/admin/monitor-products/${p.id}`)} style={btnSmall}>详情</button>
                      <button onClick={() => toggleExpand(p.id)} style={btnSmall}>分类</button>
                      {canWrite && <button onClick={() => openEdit(p)} style={btnSmall}>编辑</button>}
                      {canWrite && <button onClick={() => setDeleteTarget({id: p.id, name: p.name})} style={{ ...btnSmall, color: '#dc2626' }}>删除</button>}
                    </div>
                  </td>
                </tr>
                {expandedId === p.id && (
                  <tr key={'cat-'+p.id}><td colSpan={9} style={{padding:0}}>
                    <div style={{ padding: '14px 20px', background: '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
                      <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 4 }}>📦 SKU 规格分类 — {p.name}</h4>
                      <p style={{ fontSize: 11, color: '#6b7280', marginBottom: 10 }}>定义规格（袋装/罐装等），导入时系统自动归类并计算单单位价格</p>
                      {catLoading ? <span style={{ color: '#999', fontSize: 12 }}>加载中...</span> :
                       categories.length === 0 ? <span style={{ color: '#999', fontSize: 12 }}>暂无分类</span> :
                       <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
                         {categories.map(c => <span key={c.id} style={{ padding: '3px 10px', background: '#e0e7ff', color: '#3730a3', borderRadius: 14, fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
                           {c.name}({c.unit||'—'},×{c.conversion_factor})
                           {canWrite && <button onClick={() => delCat(c.id)} style={{ marginLeft: 2, color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}>×</button>}
                         </span>)}
                       </div>}
                      {canWrite && <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <input value={catName} onChange={e => setCatName(e.target.value)} placeholder="分类名" style={{ padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, width: 100 }} />
                        <input value={catUnit} onChange={e => setCatUnit(e.target.value)} placeholder="单位" style={{ padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, width: 70 }} />
                        <input value={catFactor} onChange={e => setCatFactor(e.target.value)} placeholder="系数" style={{ padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, width: 60 }} type="number" step="0.1" />
                        <button onClick={addCat} style={{ padding: '8px 16px', background: '#1677ff', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12 }}>添加</button>
                      </div>}
                    </div>
                  </td></tr>
                )}
              </>))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <div style={modalOverlay}>
          <div style={modalContent}>
            <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }}>{editId ? '编辑' : '新增'}监控商品</h2>
            <div key="platform" style={{ marginBottom: 10 }}>
              <label style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 2, color: '#374151' }}>平台</label>
              <select value={form['platform'] || 'taobao'} onChange={e => setForm({...form, platform: e.target.value})}
                style={{ ...inputFull }}>
                <option value="taobao">淘天（淘宝/天猫）</option>
                <option value="jd">京东</option>
              </select>
            </div>
            {[['name','商品名称','text'],['brand','品牌','text'],['description','描述','text'],
              ['price_threshold_bag','袋装价格红线','number'],['price_threshold_can','罐装价格红线','number'],
              ['price_threshold_mix','混合装价格红线','number'],['sales_threshold','日均销量红线','number'],
            ].map(([k,label,type]) => (
              <div key={k} style={{ marginBottom: 10 }}>
                <label style={{ display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 2, color: '#374151' }}>{label}</label>
                <input value={form[k] ?? ''} onChange={e => setForm({...form, [k]: e.target.value})}
                  type={type} style={{ ...inputFull }} />
              </div>
            ))}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 16 }}>
              <button onClick={() => setShowForm(false)} style={btnSecondary}>取消</button>
              <button onClick={save} disabled={saving} style={btnPrimary}>{saving ? '保存中...' : '保存'}</button>
            </div>
          </div>
        </div>
      )}

      {/* ── 批量导入弹窗 ── */}
      {batchVisible && (
        <div style={modalOverlay}>
          <div style={{ ...modalContent, width: 700, maxWidth: '90vw' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h2 style={{ fontSize: 18, fontWeight: 600 }}>批量导入</h2>
              <button onClick={closeBatch} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: '#999' }}>×</button>
            </div>

            {/* Step 1: Select files */}
            {batchStep === 'select' && (
              <>
                <p style={{ color: '#666', fontSize: 14, marginBottom: 12 }}>选择多个 DTS Excel 文件，系统将自动解析并导入到对应监控商品。</p>
                <input type="file" multiple accept=".xlsx,.xls"
                  onChange={e => handleBatchFiles(e.target.files)}
                  style={{ display: 'block', marginBottom: 12 }} />
                {batchFiles.length > 0 && (
                  <>
                    <p style={{ fontSize: 13, color: '#374151', marginBottom: 8 }}>已选择 <b>{batchFiles.length}</b> 个文件：</p>
                    <div style={{ maxHeight: 200, overflow: 'auto', marginBottom: 12, border: '1px solid #e5e7eb', borderRadius: 6 }}>
                      {batchFiles.map((f, i) => (
                        <div key={i} style={{ padding: '6px 10px', fontSize: 13, borderBottom: '1px solid #f0f0f0', display: 'flex', justifyContent: 'space-between' }}>
                          <span>{f.name}</span>
                          <span style={{ color: '#999' }}>{(f.size / 1024).toFixed(1)} KB</span>
                        </div>
                      ))}
                    </div>
                    <button onClick={handleBatchParse} disabled={batchParsing} style={btnPrimary}>
                      {batchParsing ? '解析中...' : '解析文件'}
                    </button>
                  </>
                )}
              </>
            )}

            {/* Step 2: Review mappings */}
            {batchStep === 'parse' && (
              <>
                <p style={{ fontSize: 13, color: '#374151', marginBottom: 12 }}>为每个文件选择对应的监控商品，然后开始导入：</p>
                <div style={{ maxHeight: 350, overflow: 'auto', marginBottom: 12 }}>
                  {batchFileInfos.map((info, i) => (
                    <div key={i} style={{ padding: 10, marginBottom: 8, border: '1px solid #e5e7eb', borderRadius: 6, background: info.data ? '#fff' : '#fef2f2' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 13 }}>
                        <span style={{ fontWeight: 500, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{info.name}</span>
                        <span>{info.data ? `🟢 ${info.data.valid_count} 条有效` : '🔴 解析失败'}</span>
                      </div>
                      <select value={batchMapping[info.index] || ''}
                        onChange={e => setBatchMapping(prev => ({ ...prev, [info.index]: parseInt(e.target.value) }))}
                        style={{ padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 4, fontSize: 13, width: '100%' }}>
                        <option value="">-- 选择监控商品 --</option>
                        {products.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    </div>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                  <button onClick={() => { setBatchStep('select'); setBatchFileInfos([]) }} style={btnSecondary}>重新选择</button>
                  <button onClick={handleBatchImport}
                    disabled={batchImporting || batchFileInfos.some(info => info.data && !batchMapping[info.index])}
                    style={btnPrimary}>
                    {batchImporting ? '导入中...' : `开始批量导入 (${batchFileInfos.length}个文件)`}
                  </button>
                </div>
              </>
            )}

            {/* Step 3: Progress/Results */}
            {batchStep === 'importing' && (
              <>
                <div style={{ marginBottom: 16 }}>
                  <div style={{ background: '#e5e7eb', borderRadius: 10, height: 12, overflow: 'hidden' }}>
                    <div style={{ background: '#1677ff', height: '100%', width: `${batchProgress.total > 0 ? (batchProgress.current / batchProgress.total) * 100 : 0}%`, transition: 'width 0.3s' }} />
                  </div>
                  <p style={{ textAlign: 'center', color: '#666', fontSize: 13, marginTop: 4 }}>
                    {batchImporting ? `导入中... ${batchProgress.current}/${batchProgress.total}` : `完成 ${batchProgress.current}/${batchProgress.total}`}
                  </p>
                </div>
                <div style={{ maxHeight: 350, overflow: 'auto', marginBottom: 12 }}>
                  {batchResults.map((r, i) => (
                    <div key={i} style={{ padding: '8px 12px', marginBottom: 6, borderRadius: 6, fontSize: 13, border: '1px solid', borderColor: r.status === 'success' ? '#bbf7d0' : '#fecaca', background: r.status === 'success' ? '#f0fdf4' : '#fef2f2' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span style={{ fontWeight: 500, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.file_name}</span>
                        <span>{r.status === 'success' ? `✅ ${r.inserted}条` : `❌ ${r.error || '失败'}`}</span>
                      </div>
                      {r.status === 'success' && <span style={{ color: '#666', fontSize: 12 }}>新增 {r.new_count} 条</span>}
                    </div>
                  ))}
                </div>
                {!batchImporting && (
                  <div style={{ textAlign: 'right' }}>
                    <button onClick={closeBatch} style={btnPrimary}>关闭</button>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
      {/* ── 删除确认弹窗 ── */}
      {deleteTarget && (
        <div style={modalOverlay}>
          <div style={{ ...modalContent, width: 400 }}>
            <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>确认删除</h3>
            <p style={{ fontSize: 14, color: '#6b7280', marginBottom: 16 }}>
              确定要删除监控商品「<b>{deleteTarget.name}</b>」吗？此操作不可撤销。
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setDeleteTarget(null)} style={btnSecondary}>取消</button>
              <button onClick={deleteMp} style={{ ...btnPrimary, background: '#dc2626' }}>确认删除</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const btnPrimary: React.CSSProperties = { padding: '8px 16px', background: '#1677ff', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14 }
const btnSecondary: React.CSSProperties = { padding: '6px 12px', background: '#fff', border: '1px solid #d9d9d9', borderRadius: 6, cursor: 'pointer', fontSize: 13 }
const btnSmall: React.CSSProperties = { padding: '2px 8px', background: '#f0f0f0', border: '1px solid #d9d9d9', borderRadius: 4, cursor: 'pointer', fontSize: 12 }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '8px 10px', fontWeight: 600, color: '#333', whiteSpace: 'nowrap' }
const tdStyle: React.CSSProperties = { padding: '8px 10px', color: '#555' }
const inputFull: React.CSSProperties = { padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, width: '100%' }
const modalOverlay: React.CSSProperties = { position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.45)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000 }
const modalContent: React.CSSProperties = { background: '#fff', borderRadius: 8, padding: 24, width: 500, maxHeight: '85vh', overflow: 'auto' }
