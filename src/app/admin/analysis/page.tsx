'use client'

import { apiFetch } from '@/lib/utils'
import { useCallback, useEffect, useState } from 'react'

interface MonitorProduct { id: number; name: string; whitelist_sellers?: string }
interface SkuCategory { id: number; name: string; unit: string; conversion_factor: number }
interface ProductItem { product_id: string; title: string; shop_name: string; seller_name: string; shop_id?: string; main_image_url: string; image_url: string; price: number; sales: number; platform: string; shop_type: string; location?: string; url?: string; product_url?: string }

export default function AnalysisPage() {
  const [monitorProducts, setMonitorProducts] = useState<MonitorProduct[]>([])
  const [selectedMp, setSelectedMp] = useState<number | null>(null)
  const [products, setProducts] = useState<ProductItem[]>([])
  const [loading, setLoading] = useState(false)
  const [mpName, setMpName] = useState('')
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<'price'|'sales'>('price')
  const [sortDir, setSortDir] = useState<'asc'|'desc'>('asc')
  const [excludeWhitelist, setExcludeWhitelist] = useState(false)
  const [whitelistSellers, setWhitelistSellers] = useState<string[]>([])
  const [hoverImg, setHoverImg] = useState<string | null>(null)
  const [hoverPos, setHoverPos] = useState({ x: 0, y: 0 })
  const [currentPlatform, setCurrentPlatform] = useState('taobao')
  const [chartPid, setChartPid] = useState<string | null>(null)
  const [chartData, setChartData] = useState<any[]>([])
  const [chartLoading, setChartLoading] = useState(false)

  const fetchChart = async (pid: string) => { setChartPid(pid); setChartLoading(true)
    try { const r = await apiFetch(`/api/products/${pid}`); setChartData(r.price_history || []) } catch { setChartData([]) } finally { setChartLoading(false) } }

  const fetchMPs = useCallback(async () => {
    try { const p = localStorage.getItem('platform') || 'taobao'; const r = await apiFetch(`/api/monitor-products/?platform=${p}`); setMonitorProducts(r.items||[]) } catch { /**/ }
  }, [])
  useEffect(() => { fetchMPs() }, [fetchMPs])

  const fetchProducts = async (mpId: number) => {
    setLoading(true); setProducts([])
    try {
      const r = await apiFetch(`/api/monitor-products/${mpId}/products?limit=2000`)
      setProducts(r.items||[])
      const mp = monitorProducts.find(m=>m.id===mpId); setMpName(mp?.name||'')
      setWhitelistSellers((mp?.whitelist_sellers||'').split(',').map((s:string)=>s.trim()).filter(Boolean))
    } catch { /**/ } finally { setLoading(false) }
  }

  const filtered = products
    .filter(p => excludeWhitelist ? !(whitelistSellers.includes(p.seller_name||'') || whitelistSellers.includes(p.shop_name||'')) : true)
    .filter(p => !search || p.title?.includes(search) || p.shop_name?.includes(search) || p.seller_name?.includes(search))
    .sort((a,b) => {
      if (sortKey==='price') return sortDir==='asc'?(a.price||0)-(b.price||0):(b.price||0)-(a.price||0)
      return sortDir==='asc'?(a.sales||0)-(b.sales||0):(b.sales||0)-(a.sales||0)
    })

  // Stats (based on filtered)
  const fprices = filtered.map(p=>p.price||0).filter(p=>p>0).sort((a,b)=>a-b)
  const avgPrice = fprices.length>0?fprices.reduce((a,b)=>a+b,0)/fprices.length:0
  const minPrice = fprices[0]||0; const maxPrice = fprices[fprices.length-1]||0
  const medianPrice = fprices.length>0?fprices[Math.floor(fprices.length/2)]:0
  const totalSales = filtered.reduce((s,p)=>s+(p.sales||0),0)
  const shops=Array.from(new Set(filtered.map(p=>p.shop_name).filter(Boolean))).length
  const sellers=Array.from(new Set(filtered.map(p=>p.seller_name).filter(Boolean))).length
  // Price distribution
  const range=maxPrice-minPrice||1; const bins=8
  const histogram=Array(bins).fill(0).map((_,i)=>({lo:Math.round(minPrice+range*i/bins),hi:Math.round(minPrice+range*(i+1)/bins),cnt:0}))
  fprices.forEach(p=>{const idx=Math.min(Math.floor((p-minPrice)/range*bins),bins-1);histogram[idx].cnt++})

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 20 }}>数据分析</h1>
      <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap', alignItems: 'center' }}>
        <select value={selectedMp||''} onChange={e=>{const v=parseInt(e.target.value); setSelectedMp(v||null); if(v)fetchProducts(v); else setProducts([])}}
          style={selectStyle}>
          <option value="">选择监控商品</option>
          {monitorProducts.map(mp=><option key={mp.id} value={mp.id}>{mp.name}</option>)}
        </select>
        {products.length>0 && <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="搜索商品/店铺/掌柜" style={{...selectStyle,width:200}} />}
        {whitelistSellers.length>0 && (
          <label style={{display:'flex',alignItems:'center',gap:6,fontSize:13,cursor:'pointer',background:'#f9fafb',padding:'6px 12px',borderRadius:6,border:'1px solid #e5e7eb'}}>
            <input type="checkbox" checked={excludeWhitelist} onChange={e=>setExcludeWhitelist(e.target.checked)} />
            🛡️ 去除白名单({whitelistSellers.length}个)
          </label>
        )}
      </div>

      {!selectedMp ? (
        <div style={{textAlign:'center',padding:80,color:'#999',border:'1px dashed #d9d9d9',borderRadius:8}}>
          <p style={{fontSize:48,marginBottom:16}}>📊</p>
          <p style={{fontSize:16,marginBottom:8}}>请选择一个监控商品</p>
          <p style={{fontSize:13}}>系统将对该商品的全平台价格、销量数据进行分析</p>
        </div>
      ) : loading ? <p style={{color:'#999'}}>加载中...</p> :
        products.length===0 ? <p style={{color:'#999',textAlign:'center',padding:40}}>暂无数据</p> : (
        <>
          {/* Summary cards */}
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))',gap:12,marginBottom:20}}>
            <StatCard label="商品总数" value={filtered.length} unit="个" color="#1677ff" />
            <StatCard label="均价" value={`¥${avgPrice.toFixed(0)}`} unit="" color="#16a34a" />
            <StatCard label="最低价" value={`¥${minPrice.toFixed(0)}`} unit="" color="#dc2626" />
            <StatCard label="最高价" value={`¥${maxPrice.toFixed(0)}`} unit="" color="#d97706" />
            <StatCard label="中位价" value={`¥${medianPrice.toFixed(0)}`} unit="" color="#8b5cf6" />
            <StatCard label="总销量" value={totalSales.toLocaleString()} unit="单" color="#0891b2" />
            <StatCard label="店铺数" value={shops} unit="家" color="#db2777" />
            <StatCard label="掌柜数" value={sellers} unit="人" color="#4f46e5" />
          </div>

          {/* Price histogram */}
          <div style={{background:'#fff',border:'1px solid #e5e7eb',borderRadius:8,padding:16,marginBottom:20}}>
            <h3 style={{fontSize:15,fontWeight:600,marginBottom:12}}>价格分布</h3>
            <div style={{display:'flex',alignItems:'flex-end',gap:4,height:120,paddingBottom:20,borderBottom:'1px solid #e5e7eb'}}>
              {histogram.map((b,i)=><div key={i} style={{flex:1,display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'flex-end'}}>
                <span style={{fontSize:10,color:'#999',marginBottom:2}}>{b.cnt||''}</span>
                <div style={{width:'100%',maxWidth:40,background:'#1677ff',borderRadius:'4px 4px 0 0',opacity:0.7,height:Math.max(2,b.cnt/Math.max(...histogram.map(h=>h.cnt),1)*100)}} />
                <span style={{fontSize:9,color:'#999',marginTop:4,transform:'rotate(-30deg)',transformOrigin:'top left',whiteSpace:'nowrap'}}>¥{b.lo}</span>
              </div>)}
            </div>
          </div>

          {/* Top cheapest */}
          <div style={{marginBottom:20}}>
            <h3 style={{fontSize:15,fontWeight:600,marginBottom:8}}>🏪 最低价店铺 TOP 10</h3>
            <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fill,minmax(280px,1fr))',gap:8}}>
              {[...filtered].sort((a,b)=>(a.price||0)-(b.price||0)).slice(0,10).map(p=>(
                <div key={p.product_id} style={{display:'flex',alignItems:'center',gap:8,padding:8,background:'#fff',border:'1px solid #e5e7eb',borderRadius:6}}>
                  {(p.image_url||p.main_image_url)?<img src={p.image_url||p.main_image_url} alt="" style={{width:40,height:40,objectFit:'cover',borderRadius:4,cursor:'pointer'}} onMouseEnter={(e) => {const r = e.currentTarget.getBoundingClientRect(); setHoverImg(p.image_url||p.main_image_url); setHoverPos({x: r.right + 8, y: r.top})}} onMouseLeave={() => setHoverImg(null)}/>:<div style={{width:40,height:40,background:'#f5f5f5',borderRadius:4}}/>}
                  <div style={{flex:1,minWidth:0}}>
                    <div style={{fontSize:12,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{p.title}</div>
                    <div style={{fontSize:11,color:'#999'}}>{p.shop_name}</div>
                  </div>
                  <div style={{fontSize:14,fontWeight:700,color:'#dc2626'}}>¥{Number(p.price||0).toFixed(0)}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Full table */}
          <h3 style={{fontSize:15,fontWeight:600,marginBottom:8}}>📋 全部商品 ({filtered.length}条)</h3>
          <div style={{overflow:'auto',border:'1px solid #e5e7eb',borderRadius:8}}>
            <table style={{width:'100%',borderCollapse:'collapse',fontSize:13}}>
              <thead><tr style={{background:'#fafafa'}}>
                <th style={thStyle}>图片</th><th style={thStyle}>标题</th><th style={{...thStyle,cursor:'pointer'}} onClick={()=>{setSortKey('price');setSortDir(d=>d==='asc'?'desc':'asc')}}>现价{sortKey==='price'?(sortDir==='asc'?'▲':'▼'):''}</th>
                <th style={{...thStyle,cursor:'pointer'}} onClick={()=>{setSortKey('sales');setSortDir(d=>d==='asc'?'desc':'asc')}}>销量{sortKey==='sales'?(sortDir==='asc'?'▲':'▼'):''}</th>
                <th style={thStyle}>店铺</th><th style={thStyle}>掌柜名</th><th style={thStyle}>地址</th><th style={thStyle}>操作</th>
              </tr></thead>
              <tbody>{filtered.slice(0,200).map(p=>(
                <tr key={p.product_id} style={{borderBottom:'1px solid #f0f0f0'}}>
                  <td style={tdStyle}>{(p.image_url||p.main_image_url)?<img src={p.image_url||p.main_image_url} alt="" style={{width:36,height:36,objectFit:'cover',borderRadius:4,cursor:'pointer'}} onMouseEnter={(e) => {const r = e.currentTarget.getBoundingClientRect(); setHoverImg(p.image_url||p.main_image_url); setHoverPos({x: r.right + 8, y: r.top})}} onMouseLeave={() => setHoverImg(null)}/>:<div style={{width:36,height:36,background:'#f5f5f5',borderRadius:4}}/>}</td>
                  <td style={tdStyle}>{p.url||p.product_url?<a href={(p.url||p.product_url||'').startsWith('https')?p.url||p.product_url:'https:'+(p.url||p.product_url)} target="_blank" rel="noreferrer" style={{color:'#1677ff'}}>{p.title}</a>:p.title}</td>
                  <td style={{...tdStyle,color:'#dc2626',fontWeight:600}}>¥{Number(p.price||0).toFixed(0)}</td>
                  <td style={tdStyle}>{p.sales?.toLocaleString()||'-'}</td>
                  <td style={tdStyle}>{p.shop_name||'-'}</td>
                  <td style={tdStyle}>{p.seller_name||'-'}</td>
                  <td style={{...tdStyle,fontSize:11,color:'#999'}}>{p.location||'-'}</td>
                  <td style={tdStyle}><button onClick={() => fetchChart(p.product_id)} style={{padding:'2px 6px',fontSize:11,color:'#1677ff',border:'1px solid #bfdbfe',borderRadius:4,background:'#fff',cursor:'pointer'}}>历史</button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </>
      )}
      {/* Image hover preview */}
      {hoverImg && (
        <div style={{ position: 'fixed', left: hoverPos.x, top: Math.min(hoverPos.y, window.innerHeight - 320), zIndex: 9999, pointerEvents: 'none' }}>
          <img src={hoverImg} alt="" style={{ width: 280, height: 280, objectFit: 'contain', borderRadius: 8, boxShadow: '0 4px 20px rgba(0,0,0,0.3)', background: '#fff', padding: 4 }} />
        </div>
      )}
      {/* History chart modal */}
      {chartPid && (
        <div style={{position:'fixed',top:0,left:0,right:0,bottom:0,background:'rgba(0,0,0,0.45)',display:'flex',justifyContent:'center',alignItems:'center',zIndex:1000}}>
          <div style={{background:'#fff',borderRadius:8,padding:24,width:'92vw',maxWidth:1140,maxHeight:'90vh',overflow:'auto'}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:12}}>
              <h3 style={{fontSize:16,fontWeight:600}}>历史趋势 — {chartPid}</h3>
              <button onClick={() => setChartPid(null)} style={{padding:'6px 12px',background:'#fff',border:'1px solid #d9d9d9',borderRadius:6,cursor:'pointer',fontSize:13}}>关闭</button>
            </div>
            {chartLoading ? <p style={{color:'#999',textAlign:'center',padding:40}}>加载中...</p> :
            chartData.length===0 ? <p style={{color:'#999',textAlign:'center',padding:40}}>暂无历史数据</p> :
            <div style={{background:'#f9fafb',borderRadius:8,padding:16,overflow:'auto'}}>
              <HistChart data={chartData} />
            </div>}
          </div>
        </div>
      )}
    </div>
  )
}

function HistChart({ data }: { data: any[] }) {
  const [hx, setHx] = useState<number | null>(null)
  if (!data.length) return null
  const sorted=[...data].sort((a:any,b:any)=>new Date(a.date).getTime()-new Date(b.date).getTime())
  const prices=sorted.map((d:any)=>d.avg_price||d.min_price||0)
  const sales=sorted.map((d:any)=>d.entries||0)
  const labels=sorted.map((d:any)=>d.date||'')
  const maxP=Math.max(...prices,1),minP=Math.min(...prices.filter((p:number)=>p>0),maxP)
  const W=Math.min(window.innerWidth*0.82,1050),H=Math.min(window.innerHeight*0.5,380)
  const pL=70,pR=80,pT=30,pB=50,cW=W-pL-pR,cH=H-pT-pB
  const px=(i:number)=>pL+(i/(prices.length-1||1))*cW
  const pyP=(v:number)=>pT+cH-((v-minP)/(maxP-minP||1))*cH
  const pyS=(v:number)=>pT+cH-((v/Math.max(...sales,1))*cH)
  const line=(v:number[],f:(v:number)=>number)=>v.map((v,i)=>`${i?'L':'M'}${px(i)},${f(v)}`).join(' ')
  let hi=-1,hp=0,hs=0,hl=''
  if(hx!==null){hi=Math.round(((hx-pL)/cW)*(prices.length-1));hi=Math.max(0,Math.min(prices.length-1,hi));hp=prices[hi];hs=sales[hi];hl=labels[hi]}
  return<div style={{position:'relative',width:W,height:H}}>
    <svg width={W} height={H} style={{fontSize:11,cursor:'crosshair'}} onMouseMove={e=>{const r=e.currentTarget.getBoundingClientRect();setHx(e.clientX-r.left)}} onMouseLeave={()=>setHx(null)}>
      <defs><linearGradient id="ahg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#dc2626" stopOpacity={0.15}/><stop offset="100%" stopColor="#dc2626" stopOpacity={0}/></linearGradient></defs>
      {[0,0.25,0.5,0.75,1].map(r=><g key={'p'+r}><line x1={pL} y1={pyP(minP+(maxP-minP)*r)} x2={W-pR} y2={pyP(minP+(maxP-minP)*r)} stroke="#f0f0f0" strokeWidth={1}/><text x={pL-10} y={pyP(minP+(maxP-minP)*r)+4} fill="#dc2626" fontSize={11} textAnchor="end">¥{Math.round(minP+(maxP-minP)*r)}</text></g>)}
      {[0,0.5,1].map(r=><text key={'s'+r} x={W-pR+30} y={pyS(Math.max(...sales,1)*r)+4} fill="#3b82f6" fontSize={11} textAnchor="start">{Math.round(Math.max(...sales,1)*r)}单</text>)}
      <path d={`${line(prices,pyP)} L${px(prices.length-1)},${pT+cH} L${px(0)},${pT+cH} Z`} fill="url(#ahg)"/>
      <path d={line(prices,pyP)} fill="none" stroke="#dc2626" strokeWidth={2.5}/>
      {prices.length<=60&&prices.map((v,i)=><circle key={'p'+i} cx={px(i)} cy={pyP(v)} r={3} fill="#fff" stroke="#dc2626" strokeWidth={2}/>)}
      <path d={line(sales,pyS)} fill="none" stroke="#3b82f6" strokeWidth={2} strokeDasharray="6,3"/>
      {labels.filter((_:any,i:number)=>i%Math.max(1,Math.ceil(labels.length/10))===0||i===labels.length-1).map((l:string,i:number)=><text key={l} x={px(i*Math.max(1,Math.ceil(labels.length/10)))} y={H-8} fill="#999" fontSize={11} textAnchor="middle">{l.slice(5)}</text>)}
      {hi>=0&&<><line x1={px(hi)} y1={pT} x2={px(hi)} y2={pT+cH} stroke="#999" strokeWidth={1} strokeDasharray="3,3"/><circle cx={px(hi)} cy={pyP(hp)} r={6} fill="#dc2626" stroke="#fff" strokeWidth={2}/><circle cx={px(hi)} cy={pyS(hs)} r={5} fill="#3b82f6" stroke="#fff" strokeWidth={2}/></>}
    </svg>
    {hi>=0&&<div style={{position:'absolute',top:pT+4,left:px(hi)>W/2?px(hi)-150:px(hi)+16,background:'rgba(0,0,0,0.85)',color:'#fff',fontSize:13,padding:'8px 12px',borderRadius:8,pointerEvents:'none',whiteSpace:'nowrap',zIndex:10}}><div style={{fontWeight:600,marginBottom:4}}>{hl}</div><div style={{color:'#fca5a5'}}>💰 价格 ¥{hp.toFixed(2)}</div><div style={{color:'#93c5fd'}}>📈 销量 {hs}单</div></div>}
    <div style={{position:'absolute',top:pT+2,right:pR-10,display:'flex',gap:16,fontSize:12,background:'rgba(255,255,255,0.9)',padding:'4px 12px',borderRadius:4,border:'1px solid #e5e7eb'}}><span style={{color:'#dc2626'}}>● 价格</span><span style={{color:'#3b82f6'}}>● 销量</span></div>
  </div>
}

function StatCard({label,value,unit,color}:{label:string;value:string|number;unit:string;color:string}) {
  return <div style={{background:'#fff',border:'1px solid #e5e7eb',borderRadius:8,padding:'14px 16px',textAlign:'center'}}>
    <div style={{fontSize:12,color:'#6b7280',marginBottom:4}}>{label}</div>
    <div style={{fontSize:20,fontWeight:700,color}}>{value}<span style={{fontSize:12,fontWeight:400,color:'#999'}}>{unit}</span></div>
  </div>
}

const selectStyle:React.CSSProperties={padding:'6px 10px',border:'1px solid #d9d9d9',borderRadius:6,fontSize:14,outline:'none'}
const thStyle:React.CSSProperties={textAlign:'left',padding:'8px 10px',fontWeight:600,fontSize:12,color:'#666'}
const tdStyle:React.CSSProperties={padding:'8px 10px',color:'#555',fontSize:13}
