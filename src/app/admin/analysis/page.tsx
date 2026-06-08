'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useState } from 'react'

interface MonitorProduct { id: number; name: string }
interface SkuCategory { id: number; name: string; unit: string; conversion_factor: number }
interface ProductItem {
  product_id: string; title: string; shop_name: string; seller_name: string
  main_image_url: string; price: number; sales_volume: number; daily_sales: number
}

export default function AnalysisPage() {
  const { user } = useAuth()
  const [monitorProducts, setMonitorProducts] = useState<MonitorProduct[]>([])
  const [categories, setCategories] = useState<SkuCategory[]>([])
  const [selectedMp, setSelectedMp] = useState<number | null>(null)
  const [selectedCat, setSelectedCat] = useState<number | null>(null)
  const [products, setProducts] = useState<ProductItem[]>([])
  const [loading, setLoading] = useState(false)
  const [shopFilter, setShopFilter] = useState('')
  const [sellerFilter, setSellerFilter] = useState('')
  const [sortKey, setSortKey] = useState<'price' | 'sales' | 'daily'>('price')

  const fetchMonitorProducts = useCallback(async () => {
    try {
      const res = await apiFetch('/api/monitor-products/')
      setMonitorProducts(res.items || [])
    } catch { /**/ }
  }, [])

  useEffect(() => { fetchMonitorProducts() }, [fetchMonitorProducts])

  const fetchCategories = async (mpId: number) => {
    try {
      const res = await apiFetch(`/api/monitor-products/${mpId}/sku-categories`)
      setCategories(res.items || [])
    } catch { setCategories([]) }
  }

  const fetchProducts = async () => {
    if (!selectedMp && !selectedCat) return
    setLoading(true)
    try {
      let url = `/api/product-keywords/products?limit=500`
      // 通过监控商品ID过滤（目前API不支持直接过滤，在前端过滤）
      const res = await apiFetch(url)
      const items = (res.items || []).filter((p: any) => {
        // 简单过滤：如果选了监控商品和规格，按标题关键词过滤
        if (!selectedCat) return true
        const cat = categories.find(c => c.id === selectedCat)
        if (!cat) return true
        return p.title?.includes(cat.name)
      })
      setProducts(items)
    } catch { setProducts([]) } finally { setLoading(false) }
  }

  useEffect(() => {
    if (selectedMp) { fetchCategories(selectedMp); fetchProducts() }
  }, [selectedMp]) // eslint-disable-line

  const filtered = products.filter(p => {
    if (shopFilter && !p.shop_name?.includes(shopFilter)) return false
    if (sellerFilter && !(p.seller_name || '').includes(sellerFilter)) return false
    return true
  }).sort((a, b) => {
    if (sortKey === 'price') return (a.price || 0) - (b.price || 0)
    if (sortKey === 'sales') return (b.sales_volume || 0) - (a.sales_volume || 0)
    return (b.daily_sales || 0) - (a.daily_sales || 0)
  })

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 20 }}>价格分析</h1>

      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={selectedMp || ''} onChange={e => { const v = parseInt(e.target.value); setSelectedMp(v || null); setSelectedCat(null) }}
          style={selectStyle}>
          <option value="">选择监控商品</option>
          {monitorProducts.map(mp => <option key={mp.id} value={mp.id}>{mp.name}</option>)}
        </select>
        {categories.length > 0 && (
          <select value={selectedCat || ''} onChange={e => { const v = parseInt(e.target.value); setSelectedCat(v || null); fetchProducts() }}
            style={selectStyle}>
            <option value="">全部规格</option>
            {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        )}
        <select value={sortKey} onChange={e => setSortKey(e.target.value as any)} style={selectStyle}>
          <option value="price">按价格升序</option>
          <option value="sales">按销量降序</option>
          <option value="daily">按日均销量降序</option>
        </select>
        <input value={shopFilter} onChange={e => setShopFilter(e.target.value)} placeholder="筛选店铺名" style={inputStyle} />
        <input value={sellerFilter} onChange={e => setSellerFilter(e.target.value)} placeholder="筛选掌柜名" style={inputStyle} />
        <button onClick={fetchProducts} style={btnSecondary}>刷新</button>
      </div>

      {loading ? <p style={{ color: '#999' }}>加载中...</p> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ background: '#fafafa', borderBottom: '1px solid #f0f0f0' }}>
                <th style={thStyle}>图片</th><th style={thStyle}>标题</th><th style={thStyle}>店铺</th>
                <th style={thStyle}>价格</th><th style={thStyle}>总销量</th><th style={thStyle}>日均销量</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 200).map(p => (
                <tr key={p.product_id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                  <td style={tdStyle}>
                    {p.main_image_url ? <img src={p.main_image_url} alt="" style={{ width: 50, height: 50, objectFit: 'cover', borderRadius: 4 }} />
                      : <div style={{ width: 50, height: 50, background: '#f5f5f5', borderRadius: 4 }} />}
                  </td>
                  <td style={{ ...tdStyle, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.title}
                  </td>
                  <td style={tdStyle}>{p.shop_name}</td>
                  <td style={{ ...tdStyle, fontWeight: 600, color: '#dc2626' }}>¥{(p.price || 0).toFixed(2)}</td>
                  <td style={tdStyle}>{p.sales_volume?.toLocaleString() || '-'}</td>
                  <td style={tdStyle}>{p.daily_sales?.toFixed(1) || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && <p style={{ textAlign: 'center', padding: 40, color: '#999' }}>请选择监控商品查看数据</p>}
        </div>
      )}
    </div>
  )
}

const selectStyle: React.CSSProperties = { padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, outline: 'none' }
const inputStyle: React.CSSProperties = { padding: '6px 10px', border: '1px solid #d9d9d9', borderRadius: 6, fontSize: 14, outline: 'none', width: 140 }
const btnSecondary: React.CSSProperties = { padding: '6px 12px', backgroundColor: '#fff', border: '1px solid #d9d9d9', borderRadius: 6, cursor: 'pointer', fontSize: 13 }
const thStyle: React.CSSProperties = { textAlign: 'left', padding: '12px 16px', fontWeight: 600, color: '#333' }
const tdStyle: React.CSSProperties = { padding: '12px 16px', color: '#555' }
