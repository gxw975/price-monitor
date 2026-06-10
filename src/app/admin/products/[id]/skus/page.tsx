'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

interface ProductSku {
  id: number; sku_name: string; sku_price: number; unit_price: number | null
  sku_image_url: string | null; sku_category_id: number | null
  category_name?: string; is_verified: boolean; quantity?: number
}

interface SkuCategory {
  id: number; monitor_product_id: number; name: string; unit: string; conversion_factor: number
}

export default function SkuReviewPage() {
  const params = useParams()
  const productId = params.id as string
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'

  const [skus, setSkus] = useState<ProductSku[]>([])
  const [categories, setCategories] = useState<SkuCategory[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [bulkCatId, setBulkCatId] = useState<number | null>(null)
  const [productTitle, setProductTitle] = useState('')

  const fetchSkus = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiFetch(`/api/products/${productId}`)
      setProductTitle(res.product?.title || productId)
    } catch { /**/ } finally { setLoading(false) }
  }, [productId])

  useEffect(() => { fetchSkus() }, [fetchSkus])

  const verifySku = async (skuId: number, catId: number | null) => {
    if (!catId) return
    try {
      // 通过直接 SQL 更新（简化版：使用 product_keywords 或直接 fetch）
      const token = localStorage.getItem('auth_token')
      const res = await fetch(`/api/products/${productId}/skus/${skuId}/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ sku_ids: [skuId], sku_category_id: catId }),
      })
      if (res.ok) fetchSkus()
    } catch { /**/ }
  }

  const batchVerify = async () => {
    if (!bulkCatId || selectedIds.size === 0) return
    try {
      const token = localStorage.getItem('auth_token')
      const res = await fetch(`/api/products/${productId}/skus/batch-verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ sku_ids: Array.from(selectedIds), sku_category_id: bulkCatId }),
      })
      if (res.ok) { fetchSkus(); setSelectedIds(new Set()) }
    } catch { /**/ }
  }

  if (loading) return <div style={{ padding: 24, color: '#999' }}>加载中...</div>

  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 20 }}>
        <a href={`/admin/products/${productId}`} style={{ color: '#1677ff', fontSize: 14 }}>← 返回商品详情</a>
        <h1 style={{ fontSize: 24, fontWeight: 700, marginTop: 8 }}>SKU 规格审核</h1>
        <p style={{ color: '#6b7280', fontSize: 14 }}>{productTitle}</p>
      </div>

      <p style={{ color: '#666', fontSize: 13, marginBottom: 16 }}>
        自动归类基于监控商品的SKU分类规则。无法自动匹配的SKU需要手动选择分类。
      </p>

      {skus.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 40, color: '#999' }}>
          <p>暂无SKU数据</p>
          <p style={{ fontSize: 13, marginTop: 8 }}>导入商品后系统会自动抓取SKU详情</p>
        </div>
      ) : (
        <>
          {categories.length > 0 && canWrite && (
            <div style={{ display: 'flex', gap: 8, marginBottom: 16, alignItems: 'center', padding: 12, background: '#f9fafb', borderRadius: 8 }}>
              <span style={{ fontSize: 13, color: '#374151' }}>批量审核 {selectedIds.size} 个SKU：</span>
              <select value={bulkCatId || ''} onChange={e => setBulkCatId(parseInt(e.target.value) || null)}
                style={{ padding: '4px 8px', border: '1px solid #d9d9d9', borderRadius: 4, fontSize: 13 }}>
                <option value="">选择分类</option>
                {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <button onClick={batchVerify} style={{
                padding: '4px 12px', background: '#16a34a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 13,
              }}>确认</button>
            </div>
          )}
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
            <thead>
              <tr style={{ background: '#fafafa', borderBottom: '2px solid #e5e7eb' }}>
                <th style={thStyle}><input type="checkbox" onChange={e => {
                  if (e.target.checked) setSelectedIds(new Set(skus.map(s => s.id)))
                  else setSelectedIds(new Set())
                }} /></th>
                <th style={thStyle}>SKU名称</th>
                <th style={thStyle}>价格</th>
                <th style={thStyle}>自动归类</th>
                <th style={thStyle}>单单位价格</th>
                <th style={thStyle}>状态</th>
                {canWrite && <th style={thStyle}>操作</th>}
              </tr>
            </thead>
            <tbody>
              {skus.map(s => (
                <tr key={s.id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                  <td style={tdStyle}><input type="checkbox" checked={selectedIds.has(s.id)}
                    onChange={() => {
                      const next = new Set(selectedIds)
                      if (next.has(s.id)) { next.delete(s.id) } else { next.add(s.id) }
                      setSelectedIds(next)
                    }} /></td>
                  <td style={tdStyle}>{s.sku_name}</td>
                  <td style={{ ...tdStyle, color: '#dc2626', fontWeight: 600 }}>¥{s.sku_price?.toFixed(2)}</td>
                  <td style={tdStyle}>{s.category_name || '-'}</td>
                  <td style={tdStyle}>{s.unit_price != null ? `¥${s.unit_price.toFixed(2)}` : '-'}</td>
                  <td style={tdStyle}>
                    {s.is_verified ? (
                      <span style={{ color: '#16a34a', fontSize: 12 }}>✓ 已审核</span>
                    ) : (
                      <span style={{ color: '#fa8c16', fontSize: 12 }}>待审核</span>
                    )}
                  </td>
                  {canWrite && (
                    <td style={tdStyle}>
                      {!s.is_verified && (
                        <select onChange={e => verifySku(s.id, parseInt(e.target.value) || null)}
                          style={{ padding: '2px 6px', border: '1px solid #d9d9d9', borderRadius: 4, fontSize: 12 }}>
                          <option value="">选择分类</option>
                          {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  )
}

const thStyle: React.CSSProperties = { textAlign: 'left', padding: '10px 14px', fontWeight: 600, color: '#333' }
const tdStyle: React.CSSProperties = { padding: '10px 14px', color: '#555' }
