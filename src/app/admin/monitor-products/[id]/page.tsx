'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

interface MonitorProduct { id: number; name: string; brand: string | null; description: string | null
  price_threshold_bag: number | null; price_threshold_can: number | null
  price_threshold_mix: number | null; sales_threshold: number | null
  import_count: number; unhandled_alert_count: number; whitelist_sellers: string | null
  platform: string
}
interface ImportBatch { id: number; file_name: string; import_time: string; total_count: number; ad_count: number; valid_count: number; imported_by_name: string }
interface Product { product_id: string; title: string; shop_name: string; main_image_url: string; image_url: string; price: number; sales: number; seller_name: string; shop_id?: string; platform: string; shop_type: string; location?: string; url?: string; product_url?: string; is_approved: boolean; import_batch_id?: number }
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
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0 })
  const [jumpPage, setJumpPage] = useState('')
  const [catFilter, setCatFilter] = useState<number | null>(null)
  const [filters, setFilters] = useState({ title: '', pid: '', minPrice: '', maxPrice: '', minSales: '', maxSales: '', seller: '', shop: '', location: '' })
  const [onlyNew, setOnlyNew] = useState(false)
  const [excludeWhitelist, setExcludeWhitelist] = useState(false)
  const [delBatch, setDelBatch] = useState<ImportBatch | null>(null)
  const [delProduct, setDelProduct] = useState<Product | null>(null)
  const [delLoading, setDelLoading] = useState(false)
  const [chartPid, setChartPid] = useState<string | null>(null)
  const [chartData, setChartData] = useState<any[]>([])
  const [chartLoading, setChartLoading] = useState(false)
  const fetchChart = async (pid: string) => { setChartPid(pid); setChartLoading(true)
    try { const r = await apiFetch(`/api/products/${pid}`); setChartData(r.price_history || []) } catch { setChartData([]) } finally { setChartLoading(false) } }

  const fetchMp = useCallback(async () => {
    try {
      const res = await apiFetch('/api/monitor-products/')
      const found = (res.items || []).find((m: any) => m.id === id)
      if (found) {
        const selectedPlatform = localStorage.getItem('platform') || 'taobao'
        // 平台不一致：自动找到同名异平台的监控商品并跳转
        if (found.platform !== selectedPlatform) {
          const alt = (res.items || []).find((m: any) => m.name === found.name && m.platform === selectedPlatform)
          if (alt) { router.replace(`/admin/monitor-products/${alt.id}`) }
          else { router.replace('/admin/monitor-products') }
          return
        }
        setMp(found); setEditData(found); setWhitelistInput(found.whitelist_sellers || '')
      }
    } catch { /**/ } finally { setLoading(false) }
  }, [id])
  useEffect(() => { fetchMp() }, [fetchMp])

  // Load categories on mount (needed for filter bar)
  useEffect(() => { if(id) { apiFetch(`/api/monitor-products/${id}/sku-categories`).then(r => setCategories(r.items||[])).catch(()=>{}) } }, [id])

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
  const whitelistSellers = (mp?.whitelist_sellers || '').split(',').map(s => s.trim()).filter(Boolean)
  const latestBatchId = imports.length > 0 ? imports[0].id : null
  const filteredProds = sortedProds.filter(p => {
    if (catFilter) { const cat = categories.find((c:any) => c.id === catFilter); if (cat) { const kw = (cat.unit || cat.name.split(/[\s(（]/)[0]); if (!(p.title||'').includes(kw)) return false } }
    const f = filters
    if (excludeWhitelist && whitelistSellers.length > 0) { if (whitelistSellers.includes(p.seller_name||'') || whitelistSellers.includes(p.shop_name||'')) return false }
    if (onlyNew && latestBatchId && (p as any).import_batch_id !== latestBatchId) return false
    if (f.title && !(p.title||'').toLowerCase().includes(f.title.toLowerCase())) return false
    if (f.pid && !(p.product_id||'').includes(f.pid)) return false
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
          {canWrite && !editing && tab === 'info' && <button onClick={() => setEditing(true)} style={btnSecondary}>编辑</button>}
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
            <span style={{ fontSize: 12, color: '#999', whiteSpace: 'nowrap' }}>规格:</span>
            <button onClick={() => setCatFilter(null)} style={{ padding:'2px 8px',fontSize:11,borderRadius:4,border:'1px solid #d9d9d9',background:catFilter===null?'#1677ff':'#fff',color:catFilter===null?'#fff':'#666',cursor:'pointer' }}>全部</button>
            {categories.map((c:any) => (
              <button key={c.id} onClick={() => setCatFilter(c.id)} style={{ padding:'2px 8px',fontSize:11,borderRadius:4,border:'1px solid #d9d9d9',background:catFilter===c.id?'#1677ff':'#fff',color:catFilter===c.id?'#fff':'#666',cursor:'pointer' }}>{c.name}</button>
            ))}
            <span style={{ fontSize: 12, color: '#999', whiteSpace: 'nowrap', marginLeft:8 }}>筛选:</span>
            <input placeholder="标题" value={filters.title} onChange={e => setFilter('title', e.target.value)}
              style={filterInput} />
            <input placeholder="商品ID" value={filters.pid} onChange={e => setFilter('pid', e.target.value)}
              style={{...filterInput, width:110}} />
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
            <span style={{ flex: 1 }} />
            <button onClick={async () => {
              const token = localStorage.getItem('auth_token')
              const res = await fetch(`/api/monitor-products/${id}/products/export`, { headers: { Authorization: `Bearer ${token}` } })
              const blob = await res.blob()
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a'); a.href = url; a.download = `products_${id}_${new Date().toISOString().slice(0,10)}.xlsx`
              a.click(); URL.revokeObjectURL(url)
            }}
              style={{ padding: '4px 10px', background: '#16a34a', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 12, whiteSpace: 'nowrap' }}>📥 导出Excel</button>
            {whitelistSellers.length>0 && (
              <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', whiteSpace: 'nowrap' }}>
                <input type="checkbox" checked={excludeWhitelist} onChange={e => { setExcludeWhitelist(e.target.checked); setProdPage(1) }} />
                🛡️ 去除白名单({whitelistSellers.length})
              </label>
            )}
            <button onClick={() => { setFilters({ title:'',pid:'',minPrice:'',maxPrice:'',minSales:'',maxSales:'',seller:'',shop:'',location:'' }); setOnlyNew(false); setExcludeWhitelist(false); setProdPage(1) }}
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
                <th style={{...thStyle,width:160,cursor:'pointer'}} onClick={()=>toggleProdSort('shop_name')}>店铺名称{prodSortIndicator('shop_name')}</th>
                <th style={{...thStyle,width:85,cursor:'pointer'}} onClick={()=>toggleProdSort('unit_price')}>单克价{prodSortIndicator('unit_price')}</th>
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
                            onMouseEnter={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHoverImg(p.image_url || p.main_image_url); setHoverPos({x: r.right + 8, y: r.top}) }}
                            onMouseLeave={() => setHoverImg(null)} />
                          {hoverImg === (p.image_url || p.main_image_url) && (
                            <div style={{ position: 'fixed', left: hoverPos.x, top: Math.min(hoverPos.y, window.innerHeight - 320), zIndex: 9999, pointerEvents: 'none' }}>
                              <img src={p.image_url || p.main_image_url} alt="" style={{ width: 260, height: 260, objectFit: 'contain', borderRadius: 8, boxShadow: '0 4px 20px rgba(0,0,0,0.3)', background: '#fff', padding: 4 }} />
                            </div>
                          )}
                        </div>
                      ) : <div style={{ width: 72, height: 72, background: '#f5f5f5', borderRadius: 6 }} />}
                    </td>
                    <td style={{...tdStyle,fontFamily:'monospace',fontSize:12}}>{p.product_id}</td>
                    <td style={tdStyle}>
                      {(() => { const link = p.url || p.product_url || ((p.platform||'')==='jd'?`https://item.jd.com/${p.product_id}.html`:`https://item.taobao.com/item.htm?id=${p.product_id}`); return <a href={link.startsWith('http')?link:'https:'+link} target="_blank" rel="noreferrer" style={{color:'#1677ff'}}>{p.title}</a> })()}
                    </td>
                    <td style={{...tdStyle,color:'#dc2626',fontWeight:600}}>¥{Number(p.price||0).toFixed(2)}</td>
                    <td style={tdStyle}>{p.sales?.toLocaleString()||'-'}</td>
                    <td style={tdStyle}>{p.platform||'-'}</td>
                    <td style={tdStyle}>{p.shop_type||'-'}</td>
                    <td style={{...tdStyle,fontSize:12}}>{p.shop_name||'-'}</td>
                    <td style={{...tdStyle,fontWeight:600,color:Number((p as any).unit_price) > 0 && Number((p as any).unit_price) < 0.5 ? '#dc2626' : '#16a34a'}}>{(p as any).unit_price ? `¥${Number((p as any).unit_price).toFixed(4)}` : '-'}</td>
                    {canWrite && <td style={tdStyle}><div style={{display:'flex',gap:4}}><button onClick={() => fetchChart(p.product_id)} style={{padding:'2px 6px',fontSize:11,color:'#1677ff',border:'1px solid #bfdbfe',borderRadius:4,background:'#fff',cursor:'pointer'}}>历史</button><button onClick={() => setDelProduct(p)} style={{padding:'2px 6px',fontSize:11,color:'#dc2626',border:'1px solid #fecaca',borderRadius:4,background:'#fff',cursor:'pointer'}}>删除</button></div></td>}
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
                <span key={c.id} style={{padding:'6px 14px',background:'#e0e7ff',color:'#3730a3',borderRadius:16,fontSize:13,border:'1px solid #c7d2fe',display:'flex',alignItems:'center',gap:6}}>
                  {c.name}（{c.unit||'单位未设'}，×{c.conversion_factor}）
                  {canWrite && (
                    <button onClick={async () => { if(!confirm('删除分类？')) return; await apiFetch(`/api/monitor-products/${id}/sku-categories/${c.id}`,{method:'DELETE'}); const r=await apiFetch(`/api/monitor-products/${id}/sku-categories`); setCategories(r.items||[]) }}
                      style={{marginLeft:2,background:'none',border:'none',color:'#ef4444',cursor:'pointer',fontSize:14,lineHeight:1}}>×</button>
                  )}
                </span>
              ))}
            </div>
          )}
          <p style={{color:'#6b7280',fontSize:12,padding:12,textAlign:'center'}}>
            分类管理请前往 <a href="/admin/monitor-products" style={{color:'#1677ff'}}>商品监控列表页</a> — 展开商品对应的「分类」面板增删
          </p>
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
      {/* History chart modal */}
      {chartPid && (
        <div style={modalOverlay}>
          <div style={{...modalContent,width:'92vw',maxWidth:1140,maxHeight:'90vh',overflow:'auto'}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:12}}>
              <h3 style={{fontSize:16,fontWeight:600}}>历史趋势 — {chartPid}</h3>
              <button onClick={() => setChartPid(null)} style={btnSecondary}>关闭</button>
            </div>
            {chartLoading ? <p style={{color:'#999',textAlign:'center',padding:40}}>加载中...</p> :
            chartData.length === 0 ? <p style={{color:'#999',textAlign:'center',padding:40}}>暂无历史数据</p> :
            <div style={{background:'#f9fafb',borderRadius:8,padding:16}}>
              <HistoryChart data={chartData} />
            </div>}
          </div>
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
function HistoryChart({ data }: { data: any[] }) {
  const [hoverX, setHoverX] = useState<number | null>(null)
  if (!data.length) return null
  // Date ascending (old→new, left→right)
  const sorted = [...data].sort((a:any,b:any) => new Date(a.date).getTime() - new Date(b.date).getTime())
  const prices=sorted.map((d:any)=>d.avg_price||d.min_price||0)
  const sales=sorted.map((d:any)=>d.entries||0)
  const labels=sorted.map((d:any)=>d.date||'')
  const maxP=Math.max(...prices,1), minP=Math.min(...prices.filter((p:number)=>p>0),maxP)
  const rangeP=maxP-minP||1; const maxS=Math.max(...sales,1)
  // Responsive sizing using viewport
  const W=Math.min(window.innerWidth*0.85, 1100), H=Math.min(window.innerHeight*0.55, 420)
  const padL=70, padR=80, padT=30, padB=50
  const chartW=W-padL-padR, chartH=H-padT-padB
  const px=(i:number)=>padL+(i/(prices.length-1||1))*chartW
  const pyP=(v:number)=>padT+chartH-((v-minP)/rangeP)*chartH
  const pyS=(v:number)=>padT+chartH-((v/maxS)*chartH)
  const line=(vals:number[],fn:(v:number)=>number)=>vals.map((v,i)=>`${i===0?'M':'L'}${px(i)},${fn(v)}`).join(' ')
  let hoverIdx=-1, hoverPrice=0, hoverSales=0, hoverLabel=''
  if (hoverX!==null) { hoverIdx=Math.round(((hoverX-padL)/chartW)*(prices.length-1)); hoverIdx=Math.max(0,Math.min(prices.length-1,hoverIdx)); hoverPrice=prices[hoverIdx]; hoverSales=sales[hoverIdx]; hoverLabel=labels[hoverIdx] }
  return <div style={{position:'relative',width:W,height:H}}>
    <svg width={W} height={H} style={{fontSize:11,cursor:'crosshair'}} onMouseMove={e=>{const r=e.currentTarget.getBoundingClientRect();setHoverX(e.clientX-r.left)}} onMouseLeave={()=>setHoverX(null)}>
      <defs><linearGradient id="pg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#dc2626" stopOpacity={0.15}/><stop offset="100%" stopColor="#dc2626" stopOpacity={0}/></linearGradient></defs>
      {/* Grid + Y-axis labels for PRICE (left) */}
      {[0,0.25,0.5,0.75,1].map(r=><g key={'gp'+r}><line x1={padL} y1={pyP(minP+rangeP*r)} x2={W-padR} y2={pyP(minP+rangeP*r)} stroke="#f0f0f0" strokeWidth={1}/><text x={padL-10} y={pyP(minP+rangeP*r)+4} fill="#dc2626" fontSize={11} textAnchor="end">¥{Math.round(minP+rangeP*r)}</text></g>)}
      {/* Grid for SALES (right Y-axis, positions only) */}
      {[0,0.5,1].map(r=><text key={'gs'+r} x={W-padR+30} y={pyS(maxS*r)+4} fill="#3b82f6" fontSize={11} textAnchor="start">{Math.round(maxS*r)}单</text>)}
      {/* Area fill */}
      <path d={`${line(prices,pyP)} L${px(prices.length-1)},${padT+chartH} L${px(0)},${padT+chartH} Z`} fill="url(#pg)"/>
      {/* Price line */}
      <path d={line(prices,pyP)} fill="none" stroke="#dc2626" strokeWidth={2.5}/>
      {prices.length<=60 && prices.map((v,i)=><circle key={'p'+i} cx={px(i)} cy={pyP(v)} r={3} fill="#fff" stroke="#dc2626" strokeWidth={2}/>)}
      {/* Sales line */}
      <path d={line(sales,pyS)} fill="none" stroke="#3b82f6" strokeWidth={2} strokeDasharray="6,3"/>
      {/* X-axis labels (show ~10 evenly spaced) */}
      {labels.filter((_:any,i:number)=>i%Math.max(1,Math.ceil(labels.length/10))===0||i===labels.length-1).map((l:string,i:number)=><text key={l} x={px(i*Math.max(1,Math.ceil(labels.length/10)))} y={H-8} fill="#999" fontSize={11} textAnchor="middle">{l.slice(5)}</text>)}
      {/* Axes */}
      <line x1={padL} y1={padT} x2={padL} y2={padT+chartH} stroke="#e5e7eb"/><line x1={padL} y1={padT+chartH} x2={W-padR} y2={padT+chartH} stroke="#e5e7eb"/>
      {/* Crosshair */}
      {hoverIdx>=0 && <><line x1={px(hoverIdx)} y1={padT} x2={px(hoverIdx)} y2={padT+chartH} stroke="#999" strokeWidth={1} strokeDasharray="3,3"/>
        <circle cx={px(hoverIdx)} cy={pyP(hoverPrice)} r={6} fill="#dc2626" stroke="#fff" strokeWidth={2}/>
        <circle cx={px(hoverIdx)} cy={pyS(hoverSales)} r={5} fill="#3b82f6" stroke="#fff" strokeWidth={2}/></>}
    </svg>
    {/* Tooltip */}
    {hoverIdx>=0 && <div style={{position:'absolute',top:padT+4,left:px(hoverIdx)>W/2?px(hoverIdx)-150:px(hoverIdx)+16,background:'rgba(0,0,0,0.85)',color:'#fff',fontSize:13,padding:'8px 12px',borderRadius:8,pointerEvents:'none',whiteSpace:'nowrap',zIndex:10}}>
      <div style={{fontWeight:600,marginBottom:4}}>{hoverLabel}</div><div style={{color:'#fca5a5'}}>💰 价格 ¥{hoverPrice.toFixed(2)}</div><div style={{color:'#93c5fd'}}>📈 销量 {hoverSales}单</div></div>}
    {/* Legend */}
    <div style={{position:'absolute',top:padT+2,right:padR-10,display:'flex',gap:16,fontSize:12,background:'rgba(255,255,255,0.9)',padding:'4px 12px',borderRadius:4,border:'1px solid #e5e7eb'}}>
      <span style={{color:'#dc2626'}}>● 价格</span><span style={{color:'#3b82f6'}}>● 销量</span></div>
  </div>
}

const filterInput:React.CSSProperties={width:80,padding:'3px 6px',border:'1px solid #d9d9d9',borderRadius:4,fontSize:12,outline:'none'}
const tableStyle:React.CSSProperties={width:'100%',borderCollapse:'collapse',fontSize:14}
