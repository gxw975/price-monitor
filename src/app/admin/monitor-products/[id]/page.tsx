'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

interface MonitorProduct { id: number; name: string; brand: string | null; description: string | null
  price_threshold_bag: number | null; price_threshold_can: number | null
  price_threshold_mix: number | null; sales_threshold: number | null
  import_count: number; unhandled_alert_count: number
}

interface ImportBatch { id: number; file_name: string; import_time: string; total_count: number; ad_count: number; valid_count: number; imported_by_name: string }
interface Product { product_id: string; title: string; shop_name: string; main_image_url: string; price: number; is_approved: boolean }
interface SkuCategory { id: number; name: string; unit: string; conversion_factor: number }
interface Alert { id: number; product_id: string; product_title: string; alert_type: string; message: string; is_handled: boolean; created_at: string }

type Tab = 'info' | 'imports' | 'products' | 'skus' | 'alerts'

export default function MonitorProductDetail() {
  const params = useParams(); const router = useRouter()
  const id = parseInt(params.id as string)
  const { user } = useAuth(); const canWrite = user?.role === 'admin' || user?.role === 'manager'
  const [tab, setTab] = useState<Tab>('info')
  const [mp, setMp] = useState<MonitorProduct | null>(null)
  const [loading, setLoading] = useState(true)

  // Tab data
  const [imports, setImports] = useState<ImportBatch[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [categories, setCategories] = useState<SkuCategory[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])

  // Edit state
  const [editing, setEditing] = useState(false)
  const [editData, setEditData] = useState<Record<string, any>>({})

  const fetchMp = useCallback(async () => {
    try {
      const res = await apiFetch('/api/monitor-products/')
      const found = (res.items || []).find((m: any) => m.id === id)
      if (found) { setMp(found); setEditData(found) }
    } catch { /**/ } finally { setLoading(false) }
  }, [id])

  useEffect(() => { fetchMp() }, [fetchMp])
  useEffect(() => {
    if (!id) return
    const fetchers: Record<Tab, () => Promise<void>> = {
      info: async () => {},
      imports: async () => { const r = await apiFetch(`/api/monitor-products/${id}/imports`); setImports(r.items||[]) },
      products: async () => { const r = await apiFetch(`/api/monitor-products/${id}/products?limit=200`); setProducts(r.items||[]) },
      skus: async () => { const r = await apiFetch(`/api/monitor-products/${id}/sku-categories`); setCategories(r.items||[]) },
      alerts: async () => { const r = await apiFetch(`/api/monitor-products/${id}/alerts?limit=100`); setAlerts(r.items||[]) },
    }
    fetchers[tab]().catch(()=>{})
  }, [id, tab])

  const saveEdit = async () => {
    try {
      const clean: Record<string, any> = {}
      for (const [k, v] of Object.entries(editData)) {
        if (v === '' || v === undefined || v === null) { clean[k] = null; continue }
        if (['price_threshold_bag','price_threshold_can','price_threshold_mix','sales_threshold'].includes(k)) {
          clean[k] = parseFloat(v as string) || null
        } else { clean[k] = v }
      }
      await apiFetch(`/api/monitor-products/${id}`, { method: 'PUT', body: JSON.stringify(clean) })
      setEditing(false); fetchMp()
    } catch { /**/ }
  }

  const handleAlert = async (alertIds: number[]) => {
    try {
      await apiFetch('/api/alerts/batch-handle', { method: 'POST', body: JSON.stringify(alertIds) })
      const r = await apiFetch(`/api/monitor-products/${id}/alerts?limit=100`); setAlerts(r.items||[])
    } catch { /**/ }
  }

  if (loading || !mp) return <div style={{ padding: 24, color: '#999' }}>加载中...</div>

  const tabs: { key: Tab; label: string }[] = [
    { key: 'info', label: '基本信息' }, { key: 'imports', label: '导入历史' },
    { key: 'products', label: '商品列表' }, { key: 'skus', label: 'SKU管理' },
    { key: 'alerts', label: `预警记录${mp.unhandled_alert_count ? ` (${mp.unhandled_alert_count})` : ''}` },
  ]

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <a href="/admin/monitor-products" style={{ color: '#1677ff', fontSize: 13 }}>← 返回列表</a>
          <h1 style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{mp.name}</h1>
          {mp.brand && <span style={{ color: '#6b7280', fontSize: 14 }}>{mp.brand}</span>}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {canWrite && (
            <button onClick={() => router.push(`/admin/monitor-products/${id}/import`)} style={btnPrimary}>导入数据</button>
          )}
          {canWrite && !editing && (
            <button onClick={() => setEditing(true)} style={btnSecondary}>编辑</button>
          )}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid #e5e7eb', marginBottom: 20 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{
            padding: '10px 16px', border: 'none', background: 'none', cursor: 'pointer',
            borderBottom: tab === t.key ? '2px solid #1677ff' : '2px solid transparent',
            color: tab === t.key ? '#1677ff' : '#6b7280', fontWeight: tab === t.key ? 600 : 400, fontSize: 14,
          }}>{t.label}</button>
        ))}
      </div>

      {/* Info Tab */}
      {tab === 'info' && (
        <div style={{ maxWidth: 600 }}>
          {editing ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {[
                ['name', '商品名称'], ['brand', '品牌'], ['description', '描述'],
                ['price_threshold_bag', '袋装价格红线'], ['price_threshold_can', '罐装价格红线'],
                ['price_threshold_mix', '混合装价格红线'], ['sales_threshold', '日均销量红线'],
              ].map(([k, label]) => (
                <div key={k}>
                  <label style={labelStyle}>{label}</label>
                  <input value={editData[k] ?? ''} onChange={e => setEditData({...editData, [k]: e.target.value})}
                    style={inputStyle} type={k.includes('price') || k.includes('sales') ? 'number' : 'text'} />
                </div>
              ))}
              <div style={{ display: 'flex', gap: 8 }}>
                <button onClick={saveEdit} style={btnPrimary}>保存</button>
                <button onClick={() => { setEditing(false); setEditData(mp as any) }} style={btnSecondary}>取消</button>
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 14 }}>
              <InfoRow label="品牌" value={mp.brand} />
              <InfoRow label="描述" value={mp.description} />
              <InfoRow label="袋装价格红线" value={mp.price_threshold_bag != null ? `¥${mp.price_threshold_bag}` : null} />
              <InfoRow label="罐装价格红线" value={mp.price_threshold_can != null ? `¥${mp.price_threshold_can}` : null} />
              <InfoRow label="混合装价格红线" value={mp.price_threshold_mix != null ? `¥${mp.price_threshold_mix}` : null} />
              <InfoRow label="日均销量红线" value={mp.sales_threshold != null ? `${mp.sales_threshold}/天` : null} />
              <InfoRow label="导入次数" value={String(mp.import_count)} />
              <InfoRow label="未处理预警" value={String(mp.unhandled_alert_count)} />
            </div>
          )}
        </div>
      )}

      {/* Imports Tab */}
      {tab === 'imports' && (
        <table style={tableStyle}>
          <thead><tr style={{ background: '#fafafa' }}><th style={thStyle}>时间</th><th style={thStyle}>文件名</th><th style={thStyle}>总数</th><th style={thStyle}>广告</th><th style={thStyle}>有效</th><th style={thStyle}>操作人</th></tr></thead>
          <tbody>{imports.map(i => (
            <tr key={i.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
              <td style={tdStyle}>{i.import_time ? new Date(i.import_time).toLocaleString('zh-CN') : '-'}</td>
              <td style={tdStyle}>{i.file_name}</td>
              <td style={tdStyle}>{i.total_count}</td><td style={tdStyle}>{i.ad_count}</td><td style={tdStyle}>{i.valid_count}</td>
              <td style={tdStyle}>{i.imported_by_name || '-'}</td>
            </tr>
          ))}</tbody>
        </table>
      )}

      {/* Products Tab */}
      {tab === 'products' && (
        <table style={tableStyle}>
          <thead><tr style={{ background: '#fafafa' }}><th style={thStyle}>图片</th><th style={thStyle}>商品ID</th><th style={thStyle}>标题</th><th style={thStyle}>店铺</th><th style={thStyle}>价格</th><th style={thStyle}>审核</th></tr></thead>
          <tbody>{products.map(p => (
            <tr key={p.product_id} style={{ borderBottom: '1px solid #f0f0f0' }}>
              <td style={tdStyle}>{p.main_image_url ? <img src={p.main_image_url} alt="" style={{ width: 40, height: 40, objectFit: 'cover', borderRadius: 4 }} /> : <div style={{ width: 40, height: 40, background: '#f5f5f5', borderRadius: 4 }} />}</td>
              <td style={tdStyle}><a href={`/admin/products/${p.product_id}`} style={{ color: '#1677ff' }}>{p.product_id}</a></td>
              <td style={{ ...tdStyle, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.title}</td>
              <td style={tdStyle}>{p.shop_name}</td>
              <td style={{ ...tdStyle, color: '#dc2626', fontWeight: 600 }}>{p.price ? `¥${Number(p.price).toFixed(2)}` : '-'}</td>
              <td style={tdStyle}><span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 12, background: p.is_approved ? '#f6ffed' : '#fff7e6', color: p.is_approved ? '#52c41a' : '#fa8c16' }}>{p.is_approved ? '已审核' : '未审核'}</span></td>
            </tr>
          ))}</tbody>
        </table>
      )}

      {/* SKUs Tab */}
      {tab === 'skus' && (
        <div>
          <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>SKU 规格分类</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {categories.map(c => (
              <span key={c.id} style={{ padding: '4px 12px', background: '#e0e7ff', color: '#3730a3', borderRadius: 16, fontSize: 13 }}>
                {c.name} ({c.unit || '—'}, ×{c.conversion_factor})
              </span>
            ))}
          </div>
          <p style={{ color: '#6b7280', fontSize: 13, marginTop: 16 }}>
            SKU 分类在监控商品列表页的「SKU分类」展开面板中管理
          </p>
        </div>
      )}

      {/* Alerts Tab */}
      {tab === 'alerts' && (
        <div>
          {canWrite && alerts.some(a => !a.is_handled) && (
            <button onClick={() => handleAlert(alerts.filter(a => !a.is_handled).map(a => a.id))}
              style={{ ...btnPrimary, marginBottom: 12, background: '#16a34a' }}>
              全部标记已处理
            </button>
          )}
          <table style={tableStyle}>
            <thead><tr style={{ background: '#fafafa' }}><th style={thStyle}>时间</th><th style={thStyle}>商品</th><th style={thStyle}>类型</th><th style={thStyle}>消息</th><th style={thStyle}>状态</th></tr></thead>
            <tbody>{alerts.map(a => (
              <tr key={a.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                <td style={tdStyle}>{a.created_at ? new Date(a.created_at).toLocaleString('zh-CN') : '-'}</td>
                <td style={tdStyle}>{a.product_title || a.product_id}</td>
                <td style={tdStyle}>{a.alert_type === 'price' ? '💰价格' : '📈销量'}</td>
                <td style={tdStyle}>{a.message}</td>
                <td style={tdStyle}>{a.is_handled ? <span style={{ color: '#16a34a' }}>已处理</span> : <span style={{ color: '#fa8c16' }}>待处理</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  )
}

const InfoRow = ({ label, value }: { label: string; value: string | null }) => (
  <div style={{ display: 'flex' }}><span style={{ color: '#6b7280', width: 140 }}>{label}</span><span>{value || '-'}</span></div>
)
const btnPrimary: React.CSSProperties = { padding: '8px 16px', background: '#1677ff', color: '#fff', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 14 }
const btnSecondary: React.CSSProperties = { padding: '6px 12px', background: '#fff', border: '1px solid #d9d9d9', borderRadius: 6, cursor: 'pointer', fontSize: 13 }
const inputStyle: React.CSSProperties = { padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, width: '100%' }
const labelStyle: React.CSSProperties = { display: 'block', fontSize: 13, fontWeight: 500, marginBottom: 2, color: '#374151' }
const tableStyle: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 14 }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '10px 14px', fontWeight: 600 }
const tdStyle: React.CSSProperties = { padding: '10px 14px', color: '#555' }
