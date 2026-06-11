'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiFetch, cn, formatDateTime } from '@/lib/utils'

interface AlertItem {
  id: number
  product_id: string
  product_title: string
  alert_type: string
  message: string
  status: string
  is_sent: boolean
  sent_at: string | null
  is_read: boolean
  is_handled: boolean
  alert_value: number | null
  threshold: number | null
  monitor_product_id: number | null
  created_at: string
  handled_at: string | null
  price: number | null
  sales_volume: number | null
  platform: string | null
  seller_name: string | null
  shop_name: string | null
  product_url: string | null
  location: string | null
  main_image_url: string | null
}

interface AlertsResponse {
  items: AlertItem[]
  total: number
  page: number
  page_size: number
  unread_count: number
}

interface Stats {
  total: number
  unread: number
  by_type: Record<string, number>
  recent_7d: Record<string, number>
}

export default function AlertsPage() {
  const router = useRouter()
  const fileRef = useRef<HTMLInputElement>(null)
  const [alerts, setAlerts] = useState<AlertItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [unreadCount, setUnreadCount] = useState(0)
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [monitorProducts, setMonitorProducts] = useState<{id:number;name:string}[]>([])
  const [chartPid, setChartPid] = useState<string | null>(null)
  const [chartData, setChartData] = useState<any[]>([])
  const [chartLoading, setChartLoading] = useState(false)
  const fetchChart = async (pid: string) => { setChartPid(pid); setChartLoading(true)
    try { const r = await apiFetch(`/api/products/${pid}`); setChartData(r.price_history || []) } catch { setChartData([]) } finally { setChartLoading(false) } }
  const [filter, setFilter] = useState<{
    type: string; keyword: string; read: string; status: string; mp_id: string; handled: string
  }>({ type: '', keyword: '', read: '', status: '', mp_id: '', handled: '' })
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())

  const fetchAlerts = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', String(page))
      params.set('page_size', '20')
      if (typeof window !== 'undefined') { const p = localStorage.getItem('platform') || 'taobao'; params.set('platform', p) }
      if (filter.type) params.set('alert_type', filter.type)
      if (filter.read === 'unread') params.set('is_read', 'false')
      if (filter.read === 'read') params.set('is_read', 'true')
      if (filter.status) params.set('status', filter.status)
      if (filter.keyword) params.set('keyword', filter.keyword)
      if (filter.mp_id) params.set('monitor_product_id', filter.mp_id)
      if (filter.handled === 'unhandled') params.set('is_handled', 'false')
      if (filter.handled === 'handled') params.set('is_handled', 'true')

      const data: AlertsResponse = await apiFetch(`/api/alerts/list?${params}`)
      setAlerts(data.items)
      setTotal(data.total)
      setUnreadCount(data.unread_count)
    } catch (err) {
      console.error('获取预警列表失败:', err)
    } finally {
      setLoading(false)
    }
  }, [page, filter])

  const fetchStats = useCallback(async () => {
    try {
      const data: Stats = await apiFetch('/api/alerts/stats')
      setStats(data)
    } catch (err) {
      console.error('获取统计数据失败:', err)
    }
  }, [])

  useEffect(() => { fetchAlerts() }, [fetchAlerts])
  useEffect(() => { fetchStats() }, [fetchStats])
  useEffect(() => { apiFetch('/api/monitor-products/').then(r => setMonitorProducts(r.items||[])).catch(()=>{}) }, [])

  const batchAction = async (action: string, ids: number[]) => {
    if (!ids.length) return
    try {
      await apiFetch(`/api/alerts/${action}`, { method: 'POST', body: JSON.stringify(ids) })
      setSelectedIds(new Set())
      fetchAlerts()
      if (action !== 'batch-delete') fetchStats()
    } catch (err) {
      console.error(`批量${action}失败:`, err)
    }
  }

  const handleExportCSV = async () => {
    try {
      const params = new URLSearchParams()
      if (filter.type) params.set('alert_type', filter.type)
      const data = await apiFetch(`/api/alerts/export?${params}`, { method: 'POST' })
      const blob = new Blob(['\uFEFF' + data.csv], { type: 'text/csv;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `alerts_${new Date().toISOString().slice(0, 10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('导出失败:', err)
    }
  }

  const handleSelectAll = () => {
    if (selectedIds.size === alerts.length) setSelectedIds(new Set())
    else setSelectedIds(new Set(alerts.map((a) => a.id)))
  }

  const handleToggleSelect = (id: number) => {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelectedIds(next)
  }

  const totalPages = Math.ceil(total / 20)

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-7xl">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">预警管理</h1>
          <span className="text-sm text-gray-500">电商低价监控系统</span>
        </div>

        <div className="mb-6 grid grid-cols-4 gap-4">
          <Card title="总预警" value={stats?.total ?? 0} color="text-gray-700" bg="bg-gray-50" />
          <Card title="未读" value={unreadCount} color="text-red-600" bg="bg-red-50" />
          <Card title="价格预警(7天)" value={stats?.recent_7d?.price ?? 0} color="text-red-500" bg="bg-red-50" />
          <Card title="销量预警(7天)" value={stats?.recent_7d?.sales ?? 0} color="text-orange-500" bg="bg-orange-50" />
        </div>

        <div className="mb-4 flex items-center gap-3 flex-wrap">
          <select className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
            value={filter.type}
            onChange={(e) => { setFilter((f) => ({ ...f, type: e.target.value })); setPage(1) }}>
            <option value="">全部类型</option>
            <option value="price">价格预警</option>
            <option value="sales">销量预警</option>
          </select>
          <select className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
            value={filter.read}
            onChange={(e) => { setFilter((f) => ({ ...f, read: e.target.value })); setPage(1) }}>
            <option value="">全部状态</option>
            <option value="unread">未读</option>
            <option value="read">已读</option>
          </select>
          <select className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
            value={filter.status}
            onChange={(e) => { setFilter((f) => ({ ...f, status: e.target.value })); setPage(1) }}>
            <option value="">全部处理</option>
            <option value="unprocessed">未处理</option>
            <option value="processed">已处理</option>
          </select>
          <select className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
            value={filter.mp_id}
            onChange={(e) => { setFilter((f) => ({ ...f, mp_id: e.target.value })); setPage(1) }}>
            <option value="">全部商品</option>
            {monitorProducts.map(mp => <option key={mp.id} value={mp.id}>{mp.name}</option>)}
          </select>
          <select className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
            value={filter.handled}
            onChange={(e) => { setFilter((f) => ({ ...f, handled: e.target.value })); setPage(1) }}>
            <option value="">全部处理状态</option>
            <option value="unhandled">未处理</option>
            <option value="handled">已处理</option>
          </select>
          <input type="text" placeholder="搜索商品/消息..."
            className="rounded-md border border-gray-300 px-3 py-2 text-sm flex-1 min-w-[200px]"
            value={filter.keyword}
            onChange={(e) => { setFilter((f) => ({ ...f, keyword: e.target.value })); setPage(1) }}
          />
          <div className="flex gap-2 ml-auto">
            {selectedIds.size > 0 && (
              <>
                <button onClick={() => batchAction('mark-read', Array.from(selectedIds))}
                  className="rounded-md bg-blue-600 px-3 py-2 text-xs text-white hover:bg-blue-700">
                  已读 ({selectedIds.size})
                </button>
                <button onClick={() => batchAction('mark-processed', Array.from(selectedIds))}
                  className="rounded-md bg-green-600 px-3 py-2 text-xs text-white hover:bg-green-700">
                  处理 ({selectedIds.size})
                </button>
                <button onClick={() => batchAction('batch-handle', Array.from(selectedIds))}
                  className="rounded-md bg-purple-600 px-3 py-2 text-xs text-white hover:bg-purple-700">
                  标记已处理 ({selectedIds.size})
                </button>
                <button onClick={() => { if (confirm(`确定删除 ${selectedIds.size} 条预警？`)) batchAction('batch-delete', Array.from(selectedIds)) }}
                  className="rounded-md bg-red-600 px-3 py-2 text-xs text-white hover:bg-red-700">
                  删除 ({selectedIds.size})
                </button>
              </>
            )}
            <button onClick={handleExportCSV}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100">
              导出 CSV
            </button>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  <th className="w-10 px-3 py-2">
                    <input type="checkbox" checked={selectedIds.size === alerts.length && alerts.length > 0}
                      onChange={handleSelectAll} className="rounded" />
                  </th>
                  <th className="px-3 py-2 font-medium text-xs">类型</th>
                  <th className="px-3 py-2 font-medium text-xs">平台</th>
                  <th className="px-3 py-2 font-medium text-xs">商品</th>
                  <th className="px-3 py-2 font-medium text-xs">现价</th>
                  <th className="px-3 py-2 font-medium text-xs">销量</th>
                  <th className="px-3 py-2 font-medium text-xs">掌柜</th>
                  <th className="px-3 py-2 font-medium text-xs">店铺</th>
                  <th className="px-3 py-2 font-medium text-xs">地址</th>
                  <th className="px-3 py-2 font-medium text-xs">预警消息</th>
                  <th className="px-3 py-2 font-medium text-xs">状态</th>
                  <th className="px-3 py-2 font-medium text-xs">时间</th>
                  <th className="px-3 py-2 font-medium text-xs">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr><td colSpan={11} className="px-4 py-12 text-center text-gray-400">加载中...</td></tr>
                ) : alerts.length === 0 ? (
                  <tr><td colSpan={11} className="px-4 py-12 text-center text-gray-400">暂无预警记录</td></tr>
                ) : (
                  alerts.map((alert) => (
                    <tr key={alert.id}
                      className={cn('hover:bg-gray-50 transition-colors', !alert.is_read && 'bg-blue-50/50')}>
                      <td className="px-3 py-2">
                        <input type="checkbox" checked={selectedIds.has(alert.id)}
                          onChange={() => handleToggleSelect(alert.id)} className="rounded" />
                      </td>
                      <td className="px-3 py-2">
                        <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold',
                          alert.alert_type === 'price' ? 'bg-red-100 text-red-700' : 'bg-orange-100 text-orange-700')}>
                          {alert.alert_type === 'price' ? '💰' : '📈'}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <span style={{ padding: '1px 6px', borderRadius: 10, fontSize: 11, fontWeight: 500,
                          background: (alert.platform || 'taobao') === 'jd' ? '#fee2e2' : '#fff7ed',
                          color: (alert.platform || 'taobao') === 'jd' ? '#dc2626' : '#ea580c',
                        }}>{(alert.platform || 'taobao') === 'jd' ? '京东' : '淘天'}</span>
                      </td>
                      <td className="px-3 py-2 max-w-[180px] truncate" title={alert.product_title}>
                        {alert.product_url ? (
                          <a href={alert.product_url.startsWith('http') ? alert.product_url : 'https:' + alert.product_url}
                            target="_blank" rel="noreferrer"
                            className="text-blue-600 hover:text-blue-800 text-left text-xs">
                            {alert.product_title}
                          </a>
                        ) : (
                          <span className="text-xs">{alert.product_title}</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-xs font-medium text-red-600">{alert.price != null ? `¥${Number(alert.price).toFixed(0)}` : '-'}</td>
                      <td className="px-3 py-2 text-xs">{alert.sales_volume?.toLocaleString() || '-'}</td>
                      <td className="px-3 py-2 text-xs">{alert.seller_name || '-'}</td>
                      <td className="px-3 py-2 text-xs">{alert.shop_name || '-'}</td>
                      <td className="px-3 py-2 text-xs text-gray-400">{alert.location || '-'}</td>
                      <td className="px-3 py-2 max-w-[250px] truncate text-xs" title={alert.message}>{alert.message}</td>
                      <td className="px-3 py-2">
                        <div style={{display:'flex',flexDirection:'column',gap:2}}>
                          {alert.is_handled ? (
                            <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700">已处理</span>
                          ) : (
                            <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-700">待处理</span>
                          )}
                          {!alert.is_read && <span className="text-red-500 text-xs font-medium">● 未读</span>}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-gray-500 text-xs whitespace-nowrap">{formatDateTime(alert.created_at)}</td>
                      <td className="px-3 py-2">
                        <div className="flex gap-1 flex-wrap">
                          <button onClick={() => fetchChart(alert.product_id)} className="text-purple-600 hover:text-purple-800 text-xs">历史</button>
                          {!alert.is_read && (
                            <button onClick={() => batchAction('mark-read', [alert.id])} className="text-blue-600 hover:text-blue-800 text-xs">已读</button>
                          )}
                          {!alert.is_handled && (
                            <button onClick={() => batchAction('mark-processed', [alert.id])} className="text-green-600 hover:text-green-800 text-xs">处理</button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-gray-200 px-4 py-3">
              <span className="text-sm text-gray-500">共 {total} 条，第 {page}/{totalPages} 页</span>
              <div className="flex gap-1">
                <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}
                  className="rounded border px-3 py-1 text-sm disabled:opacity-40 hover:bg-gray-100">上一页</button>
                <button disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}
                  className="rounded border px-3 py-1 text-sm disabled:opacity-40 hover:bg-gray-100">下一页</button>
              </div>
            </div>
          )}
        </div>
      </div>
      {chartPid && (
        <div style={{position:'fixed',top:0,left:0,right:0,bottom:0,background:'rgba(0,0,0,0.45)',display:'flex',justifyContent:'center',alignItems:'center',zIndex:2000}}>
          <div style={{background:'#fff',borderRadius:8,padding:24,width:960,maxHeight:'90vh',overflow:'auto'}}>
            <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:12}}>
              <h3 style={{fontSize:16,fontWeight:600}}>历史趋势 — {chartPid}</h3>
              <button onClick={()=>setChartPid(null)} className="rounded border px-3 py-1 text-sm hover:bg-gray-100">关闭</button>
            </div>
            {chartLoading ? <p className="text-gray-400 text-center py-10">加载中...</p> :
             chartData.length===0 ? <p className="text-gray-400 text-center py-10">暂无历史数据</p> :
             <HistoryChartAlerts data={chartData} />}
          </div>
        </div>
      )}
    </div>
  )
}

function HistoryChartAlerts({ data }: { data: any[] }) {
  const [hoverX, setHoverX] = useState<number | null>(null)
  if (!data.length) return null
  const W=880, H=280, padL=55, padR=30, padT=20, padB=40
  const chartW=W-padL-padR, chartH=H-padT-padB
  const prices=data.map((d:any)=>d.avg_price||d.min_price||0).reverse()
  const sales=data.map((d:any)=>d.entries||0).reverse()
  const labels=data.map((d:any)=>d.date||'').reverse()
  const maxP=Math.max(...prices,1), minP=Math.min(...prices.filter((p:number)=>p>0),maxP)
  const rangeP=maxP-minP||1; const maxS=Math.max(...sales,1)
  const px=(i:number)=>padL+(i/(prices.length-1||1))*chartW
  const pyP=(v:number)=>padT+chartH-((v-minP)/rangeP)*chartH
  const pyS=(v:number)=>padT+chartH-((v/maxS)*chartH)
  const line=(vals:number[],fn:(v:number)=>number)=>vals.map((v,i)=>`${i===0?'M':'L'}${px(i)},${fn(v)}`).join(' ')
  let hoverIdx=-1, hoverPrice=0, hoverSales=0, hoverLabel=''
  if (hoverX!==null) { hoverIdx=Math.round(((hoverX-padL)/chartW)*(prices.length-1)); hoverIdx=Math.max(0,Math.min(prices.length-1,hoverIdx)); hoverPrice=prices[hoverIdx]; hoverSales=sales[hoverIdx]; hoverLabel=labels[hoverIdx] }
  return <div style={{position:'relative'}}>
    <svg width={W} height={H} style={{fontSize:10,cursor:'crosshair'}} onMouseMove={e=>{const r=e.currentTarget.getBoundingClientRect();setHoverX(e.clientX-r.left)}} onMouseLeave={()=>setHoverX(null)}>
      <defs><linearGradient id="pga2" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#dc2626" stopOpacity={0.12}/><stop offset="100%" stopColor="#dc2626" stopOpacity={0}/></linearGradient></defs>
      {[0,0.25,0.5,0.75,1].map(r=><g key={'g'+r}><line x1={padL} y1={pyP(minP+rangeP*r)} x2={W-padR} y2={pyP(minP+rangeP*r)} stroke="#f0f0f0" strokeWidth={1}/><text x={padL-6} y={pyP(minP+rangeP*r)+3} fill="#999" fontSize={10} textAnchor="end">¥{Math.round(minP+rangeP*r)}</text></g>)}
      <path d={`${line(prices,pyP)} L${px(prices.length-1)},${padT+chartH} L${px(0)},${padT+chartH} Z`} fill="url(#pga2)"/>
      <path d={line(prices,pyP)} fill="none" stroke="#dc2626" strokeWidth={2.5}/>
      {prices.map((v,i)=><circle key={'p'+i} cx={px(i)} cy={pyP(v)} r={3} fill="#fff" stroke="#dc2626" strokeWidth={2}/>)}
      <path d={line(sales,pyS)} fill="none" stroke="#3b82f6" strokeWidth={2} strokeDasharray="6,3"/>
      {labels.filter((_:any,i:number)=>i%Math.ceil(labels.length/10)===0||i===labels.length-1).map((l:string,i:number)=><text key={l} x={px(i*Math.ceil(labels.length/10))} y={H-6} fill="#999" fontSize={10} textAnchor="middle">{l.slice(5)}</text>)}
      <line x1={padL} y1={padT} x2={padL} y2={padT+chartH} stroke="#e5e7eb"/><line x1={padL} y1={padT+chartH} x2={W-padR} y2={padT+chartH} stroke="#e5e7eb"/>
      {hoverIdx>=0 && <><line x1={px(hoverIdx)} y1={padT} x2={px(hoverIdx)} y2={padT+chartH} stroke="#999" strokeWidth={1} strokeDasharray="3,3"/><circle cx={px(hoverIdx)} cy={pyP(hoverPrice)} r={5} fill="#dc2626" stroke="#fff" strokeWidth={2}/><circle cx={px(hoverIdx)} cy={pyS(hoverSales)} r={4} fill="#3b82f6" stroke="#fff" strokeWidth={2}/></>}
    </svg>
    {hoverIdx>=0 && <div style={{position:'absolute',top:padT+4,left:px(hoverIdx)>W/2?px(hoverIdx)-140:px(hoverIdx)+16,background:'rgba(0,0,0,0.8)',color:'#fff',fontSize:12,padding:'6px 10px',borderRadius:6,pointerEvents:'none',whiteSpace:'nowrap'}}><div>{hoverLabel}</div><div style={{color:'#fca5a5'}}>💰 ¥{hoverPrice.toFixed(2)}</div><div style={{color:'#93c5fd'}}>📈 {hoverSales}单</div></div>}
    <div style={{position:'absolute',top:padT,right:padR,display:'flex',gap:12,fontSize:11,background:'#fff',padding:'2px 8px',borderRadius:4}}><span style={{color:'#dc2626'}}>● 价格</span><span style={{color:'#3b82f6'}}>● 销量</span></div>
  </div>
}


function Card({ title, value, color, bg }: { title: string; value: number; color: string; bg: string }) {
  return (
    <div className={cn('rounded-lg border p-4', bg)}>
      <div className="text-sm text-gray-500">{title}</div>
      <div className={cn('mt-1 text-2xl font-bold', color)}>{value}</div>
    </div>
  )
}
