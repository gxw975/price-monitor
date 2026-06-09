'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

interface MonitorProduct { id: number; name: string; brand: string | null; description: string | null
  price_threshold_bag: number | null; price_threshold_can: number | null
  price_threshold_mix: number | null; sales_threshold: number | null
  import_count: number; unhandled_alert_count: number; whitelist_sellers: string | null
}
interface ImportBatch { id: number; file_name: string; import_time: string; total_count: number; ad_count: number; valid_count: number; imported_by_name: string }
interface Product { product_id: string; title: string; shop_name: string; main_image_url: string; image_url: string; price: number; sales: number; seller_name: string; platform: string; shop_type: string; location: string; url?: string; product_url?: string; is_approved: boolean; import_batch_id?: number }
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
  const [imports, setImports] = useState<ImportBatch[]>([])
  const [products, setProducts] = useState<Product[]>([])
  const [categories, setCategories] = useState<SkuCategory[]>([])
  const [alerts, setAlerts] = useState<Alert[]>([])
  const [editing, setEditing] = useState(false)
  const [editData, setEditData] = useState<Record<string, any>>({})
  const [whitelistInput, setWhitelistInput] = useState('')

  // Products tab: pagination + sort
  const [prodPage, setProdPage] = useState(1); const [prodPageSize, setProdPageSize] = useState(20)
  const [prodSort, setProdSort] = useState<string | null>(null); const [prodSortDir, setProdSortDir] = useState<'asc'|'desc'>('asc')
  const [hoverImg, setHoverImg] = useState<string | null>(null)
  const [jumpPage, setJumpPage] = useState('')
  const [filters, setFilters] = useState({ minPrice: '', maxPrice: '', minSales: '', maxSales: '', seller: '', shop: '', location: '' })
  const [onlyNew, setOnlyNew] = useState(false)
  const [delBatch, setDelBatch] = useState<ImportBatch | null>(null)
  const [delProduct, setDelProduct] = useState<Product | null>(null)
  const [delLoading, setDelLoading] = useState(false)

  const fetchMp = useCallback(async () => {
    try {
      const res = await apiFetch('/api/monitor-products/')
      const found = (res.items || []).find((m: any) => m.id === id)
      if (found) { setMp(found); setEditData(found); setWhitelistInput(found.whitelist_sellers || '') }
    } catch { /**/ } finally { setLoading(false) }
  }, [id])
  useEffect(() => { fetchMp() }, [fetchMp])

  useEffect(() => {
    if (!id) return
    const f: Record<Tab, (() => Promise<void>) | null> = {
      info: null,
      imports: async () => { const r = await apiFetch(`/api/monitor-products/${id}/imports`); setImports(r.items||[]) },
      products: async () => { const r = await apiFetch(`/api/monitor-products/${id}/products?limit=2000`); setProducts(r.items||[]); setProdPage(1) },
      skus: async () => { const r = await apiFetch(`/api/monitor-products/${id}/sku-categories`); setCategories(r.items||[]) },
      alerts: async () => { const r = await apiFetch(`/api/monitor-products/${id}/alerts?limit=100`); setAlerts(r.items||[]) },
    }
    f[tab]?.().catch(()=>{})
  }, [id, tab])

  const saveEdit = async () => {
    try {
      const clean: Record<string, any> = {}
      for (const [k, v] of Object.entries(editData)) {
        if (v === '' || v === undefined || v === null) { clean[k] = null; continue }
        if (['price_threshold_bag','price_threshold_can','price_threshold_mix','sales_threshold'].includes(k))
          clean[k] = parseFloat(v as string) || null
        else clean[k] = v
      }
      await apiFetch(`/api/monitor-products/${id}`, { method: 'PUT', body: JSON.stringify(clean) })
      setEditing(false); fetchMp()
    } catch { /**/ }
  }

  const saveWhitelist = async () => {
    try {
      const sellers = whitelistInput.split(/[,，\n]+/).map(s => s.trim()).filter(Boolean).join(',')
      await apiFetch(`/api/monitor-products/${id}`, { method: 'PUT', body: JSON.stringify({ whitelist_sellers: sellers }) })
      fetchMp()
    } catch { /**/ }
  }

  const handleAlert = async (alertIds: number[]) => {
    try { await apiFetch('/api/alerts/batch-handle', { method: 'POST', body: JSON.stringify(alertIds) }); const r = await apiFetch(`/api/monitor-products/${id}/alerts?limit=100`); setAlerts(r.items||[]) } catch { /**/ }
  }

  // Sorting for products tab
  const prodSortFn = (a: any, b: any) => {
    if (!prodSort) return 0
    const va = a[prodSort]; const vb = b[prodSort]
    if (typeof va === 'number' && typeof vb === 'number') return prodSortDir === 'asc' ? va - vb : vb - va
    return prodSortDir === 'asc' ? String(va||'').localeCompare(String(vb||''), 'zh-CN') : String(vb||'').localeCompare(String(va||''), 'zh-CN')
  }
  const sortedProds = [...products].sort(prodSortFn)
  const latestBatchId = imports.length > 0 ? imports[0].id : null
  const filteredProds = sortedProds.filter(p => {
    const f = filters
    // onlyNew: 只显示最新批次的商品
    if (onlyNew && latestBatchId && (p as any).import_batch_id !== latestBatchId) return false
    if (f.minPrice && (p.price||0) < parseFloat(f.minPrice)) return false
    if (f.maxPrice && (p.price||0) > parseFloat(f.maxPrice)) return false
    if (f.minSales && (p.sales||0) < parseInt(f.minSales)) return false
    if (f.maxSales && (p.sales||0) > parseInt(f.maxSales)) return false
    if (f.seller && !(p.seller_name||'').toLowerCase().includes(f.seller.toLowerCase())) return false
    if (f.shop && !(p.shop_name||'').toLowerCase().includes(f.shop.toLowerCase())) return false
    if (f.location && !(p.location||'').includes(f.location)) return false
    return true
  })
  const prodTotalPages = Math.ceil(filteredProds.length / prodPageSize)
  const pagedProds = filteredProds.slice((prodPage-1)*prodPageSize, prodPage*prodPageSize)
  const setFilter = (k: string, v: string) => { setFilters(prev => ({...prev, [k]: v})); setProdPage(1) }
  const prodSortIndicator = (k: string) => prodSort === k ? (prodSortDir === 'asc' ? ' ▲' : ' ▼') : ''
  const toggleProdSort = (k: string) => {
    if (prodSort === k) setProdSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setProdSort(k); setProdSortDir('asc') }
  }

  if (loading || !mp) return <div style={{ padding: 24, color: '#999' }}>加载中...</div>

  const tabs: { key: Tab; label: string }[] = [
    { key: 'info', label: '基本信息' }, { key: 'imports', label: '导入历史' },
    { key: 'products', label: '商品列表' }, { key: 'skus', label: 'SKU管理' },
    { key: 'alerts', label: `预警记录${mp.unhandled_alert_count ? ` (${mp.unhandled_alert_count})` : ''}` },
  ]

  const whitelistSellers = (mp.whitelist_sellers || '').split(',').filter(Boolean)

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <a href="/admin/monitor-products" style={{ color: '#1677ff', fontSize: 13 }}>← 返回列表</a>
          <h1 style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{mp.name}</h1>
          {mp.brand && <span style={{ color: '#6b7280', fontSize: 14 }}>{mp.brand}</span>}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {canWrite && <button onClick={() => router.push(`/admin/monitor-products/${id}/import`)} style={btnPrimary}>导入数据</button>}
          {canWrite && !editing && <button onClick={() => setEditing(true)} style={btnSecondary}>编辑</button>}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid #e5e7eb', marginBottom: 20 }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{ padding: '10px 16px', border: 'none', background: 'none', cursor: 'pointer', borderBottom: tab===t.key ? '2px solid #1677ff' : '2px solid transparent', color: tab===t.key ? '#1677ff' : '#6b7280', fontWeight: tab===t.key ? 600 : 400, fontSize: 14 }}>{t.label}</button>
        ))}
      </div>

      {/* Info Tab */}
      {tab === 'info' && (
        <div style={{ maxWidth: 700 }}>
          {editing ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {[['name','商品名称'],['brand','品牌'],['description','描述'],['price_threshold_bag','袋装价格红线'],['price_threshold_can','罐装价格红线'],['price_threshold_mix','混合装价格红线'],['sales_threshold','日均销量红线']].map(([k,label]) => (
                <div key={k}><label style={labelStyle}>{label}</label><input value={editData[k] ?? ''} onChange={e => setEditData({...editData, [k]: e.target.value})} style={inputStyle} type={k.includes('price')||k.includes('sales')?'number':'text'} /></div>
              ))}
              <div style={{ display: 'flex', gap: 8 }}><button onClick={saveEdit} style={btnPrimary}>保存</button><button onClick={() => { setEditing(false); setEditData(mp as any) }} style={btnSecondary}>取消</button></div>
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

          {/* Whitelist section */}
          <div style={{ marginTop: 24, padding: 16, border: '1px solid #e5e7eb', borderRadius: 8 }}>
            <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>🛡️ 监控白名单</h3>
            <p style={{ fontSize: 13, color: '#6b7280', marginBottom: 8 }}>
              添加掌柜名称到白名单，匹配的店铺商品不会触发价格/销量预警。多个名称用逗号或换行分隔。
            </p>
            {canWrite ? (
              <div>
                <textarea value={whitelistInput} onChange={e => setWhitelistInput(e.target.value)}
                  placeholder="掌柜名1, 掌柜名2" rows={3}
                  style={{ ...inputStyle, width: '100%', marginBottom: 8 }} />
                <button onClick={saveWhitelist} style={btnPrimary}>保存白名单</button>
              </div>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {whitelistSellers.length === 0 ? <span style={{ color: '#999', fontSize: 13 }}>暂无</span> :
                  whitelistSellers.map(s => <span key={s} style={{ padding: '2px 10px', background: '#f0fdf4', color: '#166534', borderRadius: 12, fontSize: 13, border: '1px solid #bbf7d0' }}>{s}</span>)}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Imports Tab */}
      {tab === 'imports' && (
        <div>
          {imports.length === 0 ? (
            <div style={{textAlign:'center',padding:60,color:'#999',border:'1px dashed #d9d9d9',borderRadius:8}}>
              <p style={{fontSize:16,marginBottom:8}}>📦 暂无导入记录</p>
              <p style={{fontSize:13}}>点击右上角「导入数据」上传 DTS Excel</p>
            </div>
          ) : (
            <div style={{display:'flex',flexDirection:'column',gap:12}}>
              {imports.map(i => (
                <div key={i.id} style={{border:'1px solid #e5e7eb',borderRadius:8,overflow:'hidden'}}>
                  <div style={{padding:'12px 16px',display:'flex',justifyContent:'space-between',alignItems:'center',background:'#fafafa'}}>
                    <div style={{flex:1}}>
                      <div style={{fontWeight:500,fontSize:14}}>{i.file_name}</div>
                      <div style={{fontSize:12,color:'#999',marginTop:2}}>
                        {i.import_time ? new Date(i.import_time).toLocaleString('zh-CN') : '-'} · 操作人: {i.imported_by_name||'-'}
                      </div>
                    </div>
                    <div style={{display:'flex',gap:16,alignItems:'center',fontSize:13}}>
                      <span>总计 <b>{i.total_count}</b></span>
                      <span style={{color:'#fa8c16'}}>广告 <b>{i.ad_count}</b></span>
                      <span style={{color:'#16a34a'}}>有效 <b>{i.valid_count}</b></span>
                    </div>
                    <div style={{display:'flex',gap:8,marginLeft:16}}>
                      <button onClick={async () => {
                        try { const r = await apiFetch(`/api/monitor-products/${id}/products?limit=2000`); setProducts(r.items||[]); setTab('products') } catch { /**/ }
                      }} style={btnSecondary}>查看商品</button>
                      {canWrite && (
                        <button onClick={() => setDelBatch(i)} style={{...btnSecondary,color:'#dc2626',borderColor:'#fecaca'}}>删除</button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Products Tab */}
      {tab === 'products' && (
        <div>
          {/* Filter bar */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center', padding: 8, background: '#f9fafb', borderRadius: 6, border: '1px solid #e5e7eb' }}>
            <span style={{ fontSize: 12, color: '#999', whiteSpace: 'nowrap' }}>筛选:</span>
            <input placeholder="现价≥" value={filters.minPrice} onChange={e => setFilter('minPrice', e.target.value)}
              style={filterInput} type="number" />
            <input placeholder="现价≤" value={filters.maxPrice} onChange={e => setFilter('maxPrice', e.target.value)}
              style={filterInput} type="number" />
            <input placeholder="销量≥" value={filters.minSales} onChange={e => setFilter('minSales', e.target.value)}
              style={{...filterInput, width: 70}} type="number" />
            <input placeholder="掌柜" value={filters.seller} onChange={e => setFilter('seller', e.target.value)}
              style={filterInput} />
            <input placeholder="店铺" value={filters.shop} onChange={e => setFilter('shop', e.target.value)}
              style={filterInput} />
            <input placeholder="地址" value={filters.location} onChange={e => setFilter('location', e.target.value)}
              style={filterInput} />
            <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', whiteSpace: 'nowrap' }}>
              <input type="checkbox" checked={onlyNew} onChange={e => { setOnlyNew(e.target.checked); setProdPage(1) }} />
              仅看新增({products.filter((p:any)=>latestBatchId && p.import_batch_id===latestBatchId).length})
            </label>
            <button onClick={() => { setFilters({ minPrice:'',maxPrice:'',minSales:'',maxSales:'',seller:'',shop:'',location:'' }); setOnlyNew(false); setProdPage(1) }}
              style={{ ...btnSecondary, fontSize: 12, padding: '3px 10px' }}>清除</button>
            <span style={{ fontSize: 11, color: '#999', marginLeft: 'auto' }}>筛选后 {filteredProds.length} 条</span>
          </div>
          <div style={{ maxHeight: 'calc(100vh - 370px)', overflow: 'auto', border: '1px solid #e5e7eb', borderRadius: 8 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead><tr style={{ background: '#fafafa', position: 'sticky', top: 0, zIndex: 1 }}>
                <th style={{...thStyle,width:40}}>#</th>
                <th style={{...thStyle,width:90}}>图片</th>
                <th style={{...thStyle,width:120}}>商品ID</th>
                <th style={{...thStyle,minWidth:200}}>标题</th>
                <th style={{...thStyle,width:80,cursor:'pointer'}} onClick={()=>toggleProdSort('price')}>现价{prodSortIndicator('price')}</th>
                <th style={{...thStyle,width:70,cursor:'pointer'}} onClick={()=>toggleProdSort('sales')}>销量{prodSortIndicator('sales')}</th>
                <th style={{...thStyle,width:60,cursor:'pointer'}} onClick={()=>toggleProdSort('platform')}>平台{prodSortIndicator('platform')}</th>
                <th style={{...thStyle,width:90,cursor:'pointer'}} onClick={()=>toggleProdSort('shop_type')}>店铺类型{prodSortIndicator('shop_type')}</th>
                <th style={{...thStyle,width:110,cursor:'pointer'}} onClick={()=>toggleProdSort('seller_name')}>掌柜{prodSortIndicator('seller_name')}</th>
                <th style={{...thStyle,width:150,cursor:'pointer'}} onClick={()=>toggleProdSort('shop_name')}>店铺{prodSortIndicator('shop_name')}</th>
                <th style={{...thStyle,width:100,cursor:'pointer'}} onClick={()=>toggleProdSort('location')}>地址{prodSortIndicator('location')}</th>
                {canWrite && <th style={{...thStyle,width:50}}>操作</th>}
              </tr></thead>
              <tbody>
                {pagedProds.map((p, i) => (
                  <tr key={p.product_id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                    <td style={{...tdStyle,color:'#999',fontSize:12}}>{(prodPage-1)*prodPageSize+i+1}</td>
                    <td style={tdStyle}>
                      {(p.image_url || p.main_image_url) ? (
                        <div style={{ position: 'relative' }}>
                          <img src={p.image_url || p.main_image_url} alt="" style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: 6, border: '1px solid #f0f0f0', cursor: 'pointer' }}
                            onError={e => { (e.target as HTMLImageElement).style.display = 'none' }}
                            onMouseEnter={() => setHoverImg(p.image_url || p.main_image_url)}
                            onMouseLeave={() => setHoverImg(null)} />
                          {hoverImg === (p.image_url || p.main_image_url) && (
                            <div style={{ position: 'fixed', left: '50%', top: '50%', transform: 'translate(-50%,-50%)', zIndex: 2000, border: '2px solid #e5e7eb', borderRadius: 8, background: '#fff', boxShadow: '0 4px 24px rgba(0,0,0,0.2)', padding: 8 }}>
                              <img src={p.image_url || p.main_image_url} alt="" style={{ width: 300, height: 300, objectFit: 'contain', borderRadius: 4 }} />
                            </div>
                          )}
                        </div>
                      ) : <div style={{ width: 72, height: 72, background: '#f5f5f5', borderRadius: 6 }} />}
                    </td>
                    <td style={{...tdStyle,fontFamily:'monospace',fontSize:12}}>{p.product_id}</td>
                    <td style={tdStyle}>
                      {(p.url || p.product_url) ? <a href={(p.url||p.product_url||'').startsWith('http')?(p.url||p.product_url):'https:'+(p.url||p.product_url)} target="_blank" rel="noreferrer" style={{color:'#1677ff'}}>{p.title}</a> : p.title}
                    </td>
                    <td style={{...tdStyle,color:'#dc2626',fontWeight:600}}>¥{(p.price||0).toFixed(2)}</td>
                    <td style={tdStyle}>{p.sales?.toLocaleString()||'-'}</td>
                    <td style={tdStyle}>{p.platform||'-'}</td>
                    <td style={tdStyle}>{p.shop_type||'-'}</td>
                    <td style={tdStyle}>{p.seller_name||'-'}</td>
                    <td style={{...tdStyle,fontSize:12}}>{p.shop_name||'-'}</td>
                    <td style={{...tdStyle,fontSize:11,color:'#999'}}>{p.location||'-'}</td>
                    {canWrite && <td style={tdStyle}><button onClick={() => setDelProduct(p)} style={{padding:'2px 8px',fontSize:12,color:'#dc2626',border:'1px solid #fecaca',borderRadius:4,background:'#fff',cursor:'pointer'}}>删除</button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Pagination + count + page size — all at bottom */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
            <span style={{ fontSize: 12, color: '#999' }}>共 {filteredProds.length}/{products.length} 条</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <button onClick={()=>setProdPage(1)} disabled={prodPage<=1} style={pageBtn(prodPage<=1)}>«</button>
              <button onClick={()=>setProdPage(p=>Math.max(1,p-1))} disabled={prodPage<=1} style={pageBtn(prodPage<=1)}>‹</button>
              <span style={{ fontSize: 12, color: '#999', margin: '0 4px' }}>第</span>
              <input value={jumpPage} onChange={e => setJumpPage(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { const n = parseInt(jumpPage); if (n>=1 && n<=prodTotalPages) { setProdPage(n); setJumpPage('') } } }}
                placeholder={String(prodPage)} style={{ width: 40, padding: '2px 4px', border: '1px solid #d9d9d9', borderRadius: 4, fontSize: 12, textAlign: 'center' }} />
              <span style={{ fontSize: 12, color: '#999' }}>/ {prodTotalPages||1} 页</span>
              <button onClick={()=>setProdPage(p=>Math.min(prodTotalPages,p+1))} disabled={prodPage>=prodTotalPages} style={pageBtn(prodPage>=prodTotalPages)}>›</button>
              <button onClick={()=>setProdPage(prodTotalPages)} disabled={prodPage>=prodTotalPages} style={pageBtn(prodPage>=prodTotalPages)}>»</button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 12, color: '#666' }}>每页</span>
              <select value={prodPageSize} onChange={e => { setProdPageSize(parseInt(e.target.value)); setProdPage(1) }} style={{ padding: '2px 6px', border: '1px solid #d9d9d9', borderRadius: 4, fontSize: 12 }}>
                {[20,50,100,99999].map(s => <option key={s} value={s}>{s>=99999?'全部':s}</option>)}
              </select><span style={{ fontSize: 12, color: '#666' }}>条</span>
            </div>
          </div>
        </div>
      )}

      {/* SKUs Tab */}
      {tab === 'skus' && (
        <div style={{ maxWidth: 700 }}>
          <h3 style={{fontSize:16,fontWeight:600,marginBottom:12}}>SKU 规格分类</h3>
          <p style={{fontSize:13,color:'#6b7280',marginBottom:16}}>
            为监控商品定义规格分类（如袋装、罐装），系统会在导入商品时自动将SKU归类并计算单单位价格。
          </p>
          {categories.length === 0 ? (
            <div style={{textAlign:'center',padding:40,color:'#999',border:'1px dashed #d9d9d9',borderRadius:8}}>
              <p>暂无规格分类</p>
              <p style={{fontSize:12}}>在下方或监控商品列表页添加</p>
            </div>
          ) : (
            <div style={{display:'flex',flexWrap:'wrap',gap:8,marginBottom:16}}>
              {categories.map(c => (
                <span key={c.id} style={{padding:'6px 14px',background:'#e0e7ff',color:'#3730a3',borderRadius:16,fontSize:13,border:'1px solid #c7d2fe'}}>
                  {c.name}（{c.unit||'单位未设'}，折算系数 ×{c.conversion_factor}）
                </span>
              ))}
            </div>
          )}
          {canWrite && (
            <div style={{marginTop:20,padding:16,border:'1px solid #e5e7eb',borderRadius:8}}>
              <h4 style={{fontSize:14,fontWeight:600,marginBottom:12}}>添加分类</h4>
              <div style={{display:'flex',gap:8,alignItems:'center'}}>
                <input id="catName" placeholder="分类名(如袋装)" style={filterInput} />
                <input id="catUnit" placeholder="单位(如袋)" style={{...filterInput,width:80}} />
                <input id="catFactor" placeholder="系数" style={{...filterInput,width:60}} defaultValue="1.0" />
                <button onClick={async () => {
                  const n = (document.getElementById('catName') as HTMLInputElement)?.value
                  const u = (document.getElementById('catUnit') as HTMLInputElement)?.value
                  const f = (document.getElementById('catFactor') as HTMLInputElement)?.value
                  if (!n) return
                  try { await apiFetch(`/api/monitor-products/${id}/sku-categories`, { method: 'POST', body: JSON.stringify({ name: n, unit: u||'', conversion_factor: parseFloat(f)||1 }) }); const r = await apiFetch(`/api/monitor-products/${id}/sku-categories`); setCategories(r.items||[]); (document.getElementById('catName') as HTMLInputElement).value=''; (document.getElementById('catUnit') as HTMLInputElement).value=''; (document.getElementById('catFactor') as HTMLInputElement).value='1.0' } catch { /**/ }
                }} style={btnPrimary}>添加</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Alerts Tab */}
      {tab === 'alerts' && (
        <div>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:12}}>
            <span style={{fontSize:14,color:'#6b7280'}}>
              该商品的预警记录
              {mp.price_threshold_bag && ` · 袋装红线: ¥${mp.price_threshold_bag}`}
              {mp.price_threshold_can && ` · 罐装红线: ¥${mp.price_threshold_can}`}
              {mp.sales_threshold && ` · 销量红线: ${mp.sales_threshold}/天`}
            </span>
            {canWrite && alerts.some(a=>!a.is_handled) && (
              <button onClick={()=>handleAlert(alerts.filter(a=>!a.is_handled).map(a=>a.id))} style={{...btnPrimary,background:'#16a34a'}}>全部标记已处理</button>
            )}
          </div>
          {alerts.length === 0 ? (
            <div style={{textAlign:'center',padding:60,color:'#999',border:'1px dashed #d9d9d9',borderRadius:8}}>
              <p style={{fontSize:16,marginBottom:8}}>📭 暂无预警</p>
              <p style={{fontSize:13}}>导入商品并设置监控阈值后，系统会自动检测价格和销量异常</p>
              <p style={{fontSize:12,marginTop:8}}>
                {!mp.price_threshold_bag && !mp.price_threshold_can && !mp.sales_threshold
                  ? '💡 提示：请先在「基本信息」标签中设置价格红线和销量红线'
                  : '系统将在下次导入或定时检测时自动触发预警'}
              </p>
            </div>
          ) : (
            <div style={{overflow:'auto'}}>
              <table style={tableStyle}><thead><tr style={{background:'#fafafa'}}><th style={thStyle}>时间</th><th style={thStyle}>商品ID</th><th style={thStyle}>商品名称</th><th style={thStyle}>类型</th><th style={thStyle}>预警值</th><th style={thStyle}>阈值</th><th style={thStyle}>消息</th><th style={thStyle}>状态</th></tr></thead>
                <tbody>{alerts.map(a=><tr key={a.id} style={{borderBottom:'1px solid #f0f0f0'}}>
                  <td style={tdStyle}>{a.created_at?new Date(a.created_at).toLocaleString('zh-CN'):'-'}</td>
                  <td style={{...tdStyle,fontFamily:'monospace',fontSize:12}}>{a.product_id}</td>
                  <td style={tdStyle}>{a.product_title||'-'}</td>
                  <td style={tdStyle}>{a.alert_type==='price'?'💰价格':'📈销量'}</td>
                  <td style={tdStyle}>{(a as any).alert_value||'-'}</td>
                  <td style={tdStyle}>{(a as any).threshold||'-'}</td>
                  <td style={{...tdStyle,fontSize:12}}>{a.message}</td>
                  <td style={tdStyle}>{a.is_handled?<span style={{color:'#16a34a'}}>✓ 已处理</span>:<span style={{color:'#fa8c16'}}>待处理</span>}</td>
                </tr>)}</tbody>
              </table>
            </div>
          )}
        </div>
      )}
      {/* Product delete modal */}
      {delProduct && (
        <div style={modalOverlay}>
          <div style={{...modalContent,width:440}}>
            <h3 style={{fontSize:16,fontWeight:600,marginBottom:8}}>确认删除商品</h3>
            <p style={{fontSize:14,color:'#6b7280',marginBottom:12}}>确定要删除以下商品及其关联数据？</p>
            <div style={{fontSize:13,marginBottom:12,background:'#fef2f2',padding:8,borderRadius:6}}>
              <p style={{fontWeight:500}}>{delProduct.title}</p>
              <p style={{color:'#999',fontSize:12}}>ID: {delProduct.product_id} · 店铺: {delProduct.shop_name||'-'}</p>
              <span style={{color:'#dc2626',fontSize:11}}>⚠ 将同时删除价格历史和预警记录</span>
            </div>
            <div style={{display:'flex',gap:8,justifyContent:'flex-end'}}>
              <button onClick={() => setDelProduct(null)} style={btnSecondary}>取消</button>
              <button onClick={async () => {
                try {
                  await apiFetch(`/api/products/${delProduct.product_id}`, { method: 'DELETE' })
                  setDelProduct(null); const r = await apiFetch(`/api/monitor-products/${id}/products?limit=2000`); setProducts(r.items||[])
                } catch { /**/ }
              }} style={{...btnPrimary,background:'#dc2626'}}>确认删除</button>
            </div>
          </div>
        </div>
      )}

      {/* Import batch delete modal */}
      {delBatch && (
        <div style={modalOverlay}>
          <div style={{...modalContent,width:440}}>
            <h3 style={{fontSize:16,fontWeight:600,marginBottom:8}}>确认删除</h3>
            <p style={{fontSize:14,color:'#6b7280',marginBottom:4}}>确定要删除以下批次的所有导入数据？</p>
            <p style={{fontSize:13,color:'#374151',marginBottom:12,background:'#fef2f2',padding:8,borderRadius:6}}>
              📄 {delBatch.file_name}<br/>
              总计 {delBatch.total_count} 条 · 有效 {delBatch.valid_count} 条<br/>
              <span style={{color:'#dc2626',fontSize:12}}>⚠ 将同时删除关联的商品、价格历史和预警记录</span>
            </p>
            <div style={{display:'flex',gap:8,justifyContent:'flex-end'}}>
              <button onClick={() => setDelBatch(null)} style={btnSecondary} disabled={delLoading}>取消</button>
              <button onClick={async () => {
                setDelLoading(true)
                try {
                  await apiFetch(`/api/monitor-products/${id}/imports/${delBatch.id}`, { method: 'DELETE' })
                  setDelBatch(null)
                  const r = await apiFetch(`/api/monitor-products/${id}/imports`); setImports(r.items||[]); fetchMp()
                } catch { /**/ } finally { setDelLoading(false) }
              }} style={{...btnPrimary,background:'#dc2626'}} disabled={delLoading}>
                {delLoading ? '删除中...' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const InfoRow = ({label,value}:{label:string;value:string|null})=><div style={{display:'flex'}}><span style={{color:'#6b7280',width:140}}>{label}</span><span>{value||'-'}</span></div>
const pageBtn=(d:boolean):React.CSSProperties=>({padding:'3px 10px',border:'1px solid #d9d9d9',borderRadius:4,background:'#fff',cursor:d?'not-allowed':'pointer',fontSize:13,opacity:d?0.5:1})
const btnPrimary:React.CSSProperties={padding:'8px 16px',background:'#1677ff',color:'#fff',border:'none',borderRadius:6,cursor:'pointer',fontSize:14}
const btnSecondary:React.CSSProperties={padding:'6px 12px',background:'#fff',border:'1px solid #d9d9d9',borderRadius:6,cursor:'pointer',fontSize:13}
const thStyle:React.CSSProperties={textAlign:'left',padding:'8px 10px',fontWeight:600,fontSize:12,color:'#666',whiteSpace:'nowrap'}
const tdStyle:React.CSSProperties={padding:'8px 10px',color:'#555',fontSize:13}
const inputStyle:React.CSSProperties={padding:'6px 10px',border:'1px solid #d9d9d9',borderRadius:6,fontSize:14,width:'100%'}
const labelStyle:React.CSSProperties={display:'block',fontSize:13,fontWeight:500,marginBottom:2,color:'#374151'}
const modalOverlay:React.CSSProperties={position:'fixed',top:0,left:0,right:0,bottom:0,background:'rgba(0,0,0,0.45)',display:'flex',justifyContent:'center',alignItems:'center',zIndex:1000}
const modalContent:React.CSSProperties={background:'#fff',borderRadius:8,padding:24,maxHeight:'85vh',overflow:'auto'}
const filterInput:React.CSSProperties={width:80,padding:'3px 6px',border:'1px solid #d9d9d9',borderRadius:4,fontSize:12,outline:'none'}
const tableStyle:React.CSSProperties={width:'100%',borderCollapse:'collapse',fontSize:14}
