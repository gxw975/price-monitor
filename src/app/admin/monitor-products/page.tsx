'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useState } from 'react'

interface MonitorProduct {
  id: number
  name: string
  description: string | null
  import_count: number
  last_import_time: string | null
  unhandled_alert_count: number
  created_at: string
}

interface SkuCategory {
  id: number
  monitor_product_id: number
  name: string
  unit: string
  conversion_factor: number
}

export default function MonitorProductsPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'

  const [products, setProducts] = useState<MonitorProduct[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [formName, setFormName] = useState('')
  const [formDesc, setFormDesc] = useState('')
  const [saving, setSaving] = useState(false)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [categories, setCategories] = useState<SkuCategory[]>([])
  const [catLoading, setCatLoading] = useState(false)
  const [catName, setCatName] = useState('')
  const [catUnit, setCatUnit] = useState('')
  const [catFactor, setCatFactor] = useState('1.0')

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/api/monitor-products/')
      setProducts(res.items || [])
    } catch { /**/ } finally { setLoading(false) }
  }, [])

  useEffect(() => { fetchAll() }, [fetchAll])

  const openCreate = () => {
    setEditId(null); setFormName(''); setFormDesc(''); setShowForm(true)
  }
  const openEdit = (p: MonitorProduct) => {
    setEditId(p.id); setFormName(p.name); setFormDesc(p.description || ''); setShowForm(true)
  }

  const save = async () => {
    if (!formName.trim()) return
    setSaving(true)
    try {
      if (editId) {
        await apiFetch(`/api/monitor-products/${editId}`, {
          method: 'PUT', body: JSON.stringify({ name: formName, description: formDesc }),
        })
      } else {
        await apiFetch('/api/monitor-products/', {
          method: 'POST', body: JSON.stringify({ name: formName, description: formDesc }),
        })
      }
      setShowForm(false); fetchAll()
    } catch { /**/ } finally { setSaving(false) }
  }

  const deleteProduct = async (id: number) => {
    if (!confirm('确定删除此监控商品？')) return
    try { await apiFetch(`/api/monitor-products/${id}`, { method: 'DELETE' }); fetchAll() } catch { /**/ }
  }

  const toggleExpand = async (id: number) => {
    if (expandedId === id) { setExpandedId(null); return }
    setExpandedId(id); setCatLoading(true)
    try {
      const res = await apiFetch(`/api/monitor-products/${id}/sku-categories`)
      setCategories(res.items || [])
    } catch { /**/ } finally { setCatLoading(false) }
  }

  const addCategory = async () => {
    if (!catName.trim() || !expandedId) return
    try {
      await apiFetch(`/api/monitor-products/${expandedId}/sku-categories`, {
        method: 'POST',
        body: JSON.stringify({ name: catName, unit: catUnit, conversion_factor: parseFloat(catFactor) || 1 }),
      })
      setCatName(''); setCatUnit(''); setCatFactor('1.0'); toggleExpand(expandedId)
    } catch { /**/ }
  }

  const deleteCategory = async (catId: number) => {
    if (!expandedId) return
    try {
      await apiFetch(`/api/monitor-products/${expandedId}/sku-categories/${catId}`, { method: 'DELETE' })
      toggleExpand(expandedId)
    } catch { /**/ }
  }

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>监控商品</h1>
        {canWrite && (
          <button onClick={openCreate} style={btnPrimary}>新增监控商品</button>
        )}
      </div>

      {loading ? <p style={{ color: '#999' }}>加载中...</p> : products.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 60, color: '#999' }}>
          <p>暂无监控商品</p>
          {canWrite && <p style={{ marginTop: 8 }}>点击「新增监控商品」开始</p>}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {products.map(p => (
            <div key={p.id} style={{ border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff', overflow: 'hidden' }}>
              <div style={{ padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontWeight: 600, fontSize: 16 }}>{p.name}</span>
                    {p.unhandled_alert_count > 0 && (
                      <span style={{ background: '#fee2e2', color: '#dc2626', padding: '1px 8px', borderRadius: 10, fontSize: 12 }}>
                        {p.unhandled_alert_count}条未处理预警
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 13, color: '#6b7280' }}>
                    {p.description || '无描述'} · 导入{p.import_count}次
                    {p.last_import_time && ` · 最近: ${new Date(p.last_import_time).toLocaleDateString('zh-CN')}`}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <button onClick={() => toggleExpand(p.id)} style={btnSecondary}>
                    {expandedId === p.id ? '收起分类' : 'SKU分类'}
                  </button>
                  {canWrite && (
                    <>
                      <button onClick={() => openEdit(p)} style={btnSecondary}>编辑</button>
                      <button onClick={() => deleteProduct(p.id)} style={{ ...btnSecondary, color: '#dc2626' }}>删除</button>
                    </>
                  )}
                </div>
              </div>

              {expandedId === p.id && (
                <div style={{ borderTop: '1px solid #e5e7eb', padding: '16px 20px', background: '#f9fafb' }}>
                  <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>SKU 规格分类</h3>
                  {catLoading ? <p style={{ color: '#999' }}>加载中...</p> : categories.length === 0 ? (
                    <p style={{ color: '#999', fontSize: 13 }}>暂无分类，请添加</p>
                  ) : (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
                      {categories.map(c => (
                        <span key={c.id} style={{
                          padding: '4px 12px', background: '#e0e7ff', color: '#3730a3',
                          borderRadius: 16, fontSize: 13, display: 'flex', alignItems: 'center', gap: 6,
                        }}>
                          {c.name} ({c.unit || '无单位'}, ×{c.conversion_factor})
                          {canWrite && (
                            <button onClick={() => deleteCategory(c.id)} style={{
                              marginLeft: 4, color: '#ef4444', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14,
                            }}>×</button>
                          )}
                        </span>
                      ))}
                    </div>
                  )}
                  {canWrite && (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <input value={catName} onChange={e => setCatName(e.target.value)} placeholder="分类名(如袋装)"
                        style={inputStyle} />
                      <input value={catUnit} onChange={e => setCatUnit(e.target.value)} placeholder="单位(如袋)"
                        style={{ ...inputStyle, width: 100 }} />
                      <input value={catFactor} onChange={e => setCatFactor(e.target.value)} placeholder="折算系数"
                        style={{ ...inputStyle, width: 80 }} type="number" step="0.1" />
                      <button onClick={addCategory} style={btnPrimary}>添加</button>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {showForm && (
        <div style={modalOverlay}>
          <div style={modalContent}>
            <h2 style={{ fontSize: 18, fontWeight: 600, marginBottom: 16 }}>{editId ? '编辑' : '新增'}监控商品</h2>
            <label style={labelStyle}>名称</label>
            <input value={formName} onChange={e => setFormName(e.target.value)} style={{ ...inputStyle, width: '100%', marginBottom: 12 }} placeholder="如：蒙牛一米八八儿童奶粉" />
            <label style={labelStyle}>描述（可选）</label>
            <input value={formDesc} onChange={e => setFormDesc(e.target.value)} style={{ ...inputStyle, width: '100%', marginBottom: 16 }} placeholder="商品描述或备注" />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => setShowForm(false)} style={btnSecondary}>取消</button>
              <button onClick={save} disabled={saving} style={btnPrimary}>{saving ? '保存中...' : '保存'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const btnPrimary: React.CSSProperties = {
  padding: '8px 16px', backgroundColor: '#1677ff', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14,
}
const btnSecondary: React.CSSProperties = {
  padding: '6px 12px', backgroundColor: '#fff', border: '1px solid #d9d9d9', borderRadius: 6, cursor: 'pointer', fontSize: 13,
}
const inputStyle: React.CSSProperties = {
  padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, outline: 'none',
}
const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 4, color: '#374151',
}
const modalOverlay: React.CSSProperties = {
  position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.45)',
  display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000,
}
const modalContent: React.CSSProperties = {
  backgroundColor: '#fff', borderRadius: 8, padding: 24, width: 480, maxHeight: '80vh', overflow: 'auto',
}
