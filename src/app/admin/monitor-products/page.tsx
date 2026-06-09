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
  const [catData, setCatData] = useState({ name: '', unit: '', factor: '1.0' })

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
  const deleteMp = async (id: number) => {
    if (!confirm('确定删除？')) return
    try { await apiFetch(`/api/monitor-products/${id}`, { method: 'DELETE' }); fetchAll() } catch { /**/ }
  }
  const toggleExpand = async (id: number) => {
    if (expandedId === id) { setExpandedId(null); return }
    setExpandedId(id); setCatLoading(true)
    try { const res = await apiFetch(`/api/monitor-products/${id}/sku-categories`); setCategories(res.items || []) }
    catch { alert('加载分类失败，请检查权限'); setExpandedId(null) }
    finally { setCatLoading(false) }
  }
  const addCat = async () => {
    if (!catData.name.trim() || !expandedId) { alert('请输入分类名称'); return }
    try {
      await apiFetch(`/api/monitor-products/${expandedId}/sku-categories`, {
        method: 'POST', body: JSON.stringify({ name: catData.name, unit: catData.unit, conversion_factor: parseFloat(catData.factor) || 1 }),
      })
      setCatData({ name: '', unit: '', factor: '1.0' })
      const res = await apiFetch(`/api/monitor-products/${expandedId}/sku-categories`); setCategories(res.items || [])
    } catch { alert('添加分类失败') }
  }
  const delCat = async (catId: number) => {
    if (!expandedId) return
    if (!confirm('确定删除该分类？')) return
    try { await apiFetch(`/api/monitor-products/${expandedId}/sku-categories/${catId}`, { method: 'DELETE' }); const res = await apiFetch(`/api/monitor-products/${expandedId}/sku-categories`); setCategories(res.items || []) } catch { alert('删除失败') }
  }

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
                <th style={thStyle}>名称</th><th style={thStyle}>品牌</th>
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
                      {canWrite && <button onClick={() => deleteMp(p.id)} style={{ ...btnSmall, color: '#dc2626' }}>删除</button>}
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
