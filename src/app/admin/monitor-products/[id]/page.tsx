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
interface Product { product_id: string; title: string; shop_name: string; main_image_url: string; image_url: string; price: number; sales: number; seller_name: string; platform: string; shop_type: string; location: string; url?: string; product_url?: string; is_approved: boolean }
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
  const prodTotalPages = Math.ceil(sortedProds.length / prodPageSize)
  const pagedProds = sortedProds.slice((prodPage-1)*prodPageSize, prodPage*prodPageSize)
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
        <table style={tableStyle}><thead><tr style={{background:'#fafafa'}}><th style={thStyle}>时间</th><th style={thStyle}>文件名</th><th style={thStyle}>总数</th><th style={thStyle}>广告</th><th style={thStyle}>有效</th><th style={thStyle}>操作人</th></tr></thead>
          <tbody>{imports.map(i=><tr key={i.id} style={{borderBottom:'1px solid #f0f0f0'}}><td style={tdStyle}>{i.import_time?new Date(i.import_time).toLocaleString('zh-CN'):'-'}</td><td style={tdStyle}>{i.file_name}</td><td style={tdStyle}>{i.total_count}</td><td style={tdStyle}>{i.ad_count}</td><td style={tdStyle}>{i.valid_count}</td><td style={tdStyle}>{i.imported_by_name||'-'}</td></tr>)}</tbody>
        </table>
      )}

      {/* Products Tab */}
      {tab === 'products' && (
        <div>
          <div style={{ maxHeight: 'calc(100vh - 250px)', overflow: 'auto', border: '1px solid #e5e7eb', borderRadius: 8 }}>
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
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Pagination + count + page size — all at bottom */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 8 }}>
            <span style={{ fontSize: 12, color: '#999' }}>共 {products.length} 条</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <button onClick={()=>setProdPage(1)} disabled={prodPage<=1} style={pageBtn(prodPage<=1)}>«</button>
              <button onClick={()=>setProdPage(p=>Math.max(1,p-1))} disabled={prodPage<=1} style={pageBtn(prodPage<=1)}>‹</button>
              <span style={{ fontSize: 12, color: '#999', margin: '0 4px' }}>第 {prodPage}/{prodTotalPages||1} 页</span>
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
        <div><h3 style={{fontSize:16,fontWeight:600,marginBottom:12}}>SKU 规格分类</h3>
          <div style={{display:'flex',flexWrap:'wrap',gap:8}}>{categories.map(c=><span key={c.id} style={{padding:'4px 12px',background:'#e0e7ff',color:'#3730a3',borderRadius:16,fontSize:13}}>{c.name} ({c.unit||'—'}, ×{c.conversion_factor})</span>)}</div>
          <p style={{color:'#6b7280',fontSize:13,marginTop:16}}>SKU 分类在监控商品列表页的「SKU分类」展开面板中管理</p>
        </div>
      )}

      {/* Alerts Tab */}
      {tab === 'alerts' && (
        <div>
          {canWrite && alerts.some(a=>!a.is_handled) && <button onClick={()=>handleAlert(alerts.filter(a=>!a.is_handled).map(a=>a.id))} style={{...btnPrimary,marginBottom:12,background:'#16a34a'}}>全部标记已处理</button>}
          <table style={tableStyle}><thead><tr style={{background:'#fafafa'}}><th style={thStyle}>时间</th><th style={thStyle}>商品</th><th style={thStyle}>类型</th><th style={thStyle}>消息</th><th style={thStyle}>状态</th></tr></thead>
            <tbody>{alerts.map(a=><tr key={a.id} style={{borderBottom:'1px solid #f0f0f0'}}><td style={tdStyle}>{a.created_at?new Date(a.created_at).toLocaleString('zh-CN'):'-'}</td><td style={tdStyle}>{a.product_title||a.product_id}</td><td style={tdStyle}>{a.alert_type==='price'?'💰价格':'📈销量'}</td><td style={tdStyle}>{a.message}</td><td style={tdStyle}>{a.is_handled?<span style={{color:'#16a34a'}}>已处理</span>:<span style={{color:'#fa8c16'}}>待处理</span>}</td></tr>)}</tbody>
          </table>
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
const tableStyle:React.CSSProperties={width:'100%',borderCollapse:'collapse',fontSize:14}
