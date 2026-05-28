'use client'

import { apiFetch, formatPrice, cn } from '@/lib/utils'
import { useParams, useRouter } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

interface ProductInfo {
  product_id: string
  title: string
  main_image_url: string | null
  shop_name: string
  shop_type: string | null
  shipping_area: string | null
  is_approved: boolean
  is_whitelist: boolean
  created_at: string | null
  last_updated_at: string | null
  last_sku_crawled_at: string | null
}

interface PricePoint {
  date: string
  min_price: number
  max_price: number
  avg_price: number
  entries: number
}

interface KeywordInfo {
  id: number
  name: string
  platform: string
  is_active: boolean
}

interface AlertInfo {
  id: number
  alert_type: string
  message: string
  status: string
  is_sent: boolean
  is_read: boolean
  created_at: string | null
}

interface ProductDetail {
  product: ProductInfo
  price_history: PricePoint[]
  keywords: KeywordInfo[]
  alerts: AlertInfo[]
}

export default function ProductDetailPage() {
  const params = useParams()
  const router = useRouter()
  const productId = params.id as string
  const [data, setData] = useState<ProductDetail | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchDetail = useCallback(async () => {
    setLoading(true)
    try {
      const result = await apiFetch(`/api/products/${productId}`)
      setData(result)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [productId])

  useEffect(() => {
    fetchDetail()
  }, [fetchDetail])

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-400">加载中...</p>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-gray-400">商品不存在或加载失败</p>
      </div>
    )
  }

  const p = data.product
  const allPrices = data.price_history.flatMap((pp) => [pp.min_price, pp.max_price])
  const priceMin = Math.min(...allPrices, 0)
  const priceMax = Math.max(...allPrices, 1)
  const priceRange = priceMax - priceMin || 1

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-7xl">
        <button
          onClick={() => router.back()}
          className="mb-4 text-sm text-blue-600 hover:text-blue-800"
        >
          ← 返回
        </button>

        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">{p.title}</h1>
          <div className="mt-1 flex items-center gap-2 text-sm text-gray-500">
            <span>ID: {p.product_id}</span>
            <span>·</span>
            <span>{p.shop_name}</span>
            {p.shop_type && (
              <>
                <span>·</span>
                <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-700">
                  {p.shop_type === 'tmall' ? '天猫' : p.shop_type === 'taobao' ? '淘宝' : p.shop_type}
                </span>
              </>
            )}
            <span>·</span>
            {p.is_approved ? (
              <span className="text-green-600">已审核</span>
            ) : (
              <span className="text-red-500">未审核</span>
            )}
            {p.is_whitelist && <span className="text-gray-400">· 白名单</span>}
          </div>
          {p.last_sku_crawled_at && (
            <p className="mt-1 text-xs text-gray-400">
              最近爬取: {new Date(p.last_sku_crawled_at).toLocaleString('zh-CN')}
            </p>
          )}
        </div>

        <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-2 rounded-lg border border-gray-200 bg-white p-5">
            <h2 className="mb-4 text-sm font-semibold text-gray-700">近 30 天价格趋势</h2>
            {data.price_history.length === 0 ? (
              <div className="flex items-center justify-center h-64 text-sm text-gray-400">
                暂无价格历史数据
              </div>
            ) : (
              <div className="relative h-64">
                <svg viewBox="0 0 600 220" className="w-full h-full" preserveAspectRatio="xMidYMid meet">
                  {[0, 25, 50, 75, 100].map((pct) => {
                    const y = 220 - 10 - (pct / 100) * 200
                    const val = priceMin + (priceRange * pct) / 100
                    return (
                      <g key={pct}>
                        <line x1={50} y1={y} x2={590} y2={y} stroke="#e5e7eb" strokeWidth={0.5} />
                        <text x={44} y={y + 4} textAnchor="end" fontSize={10} fill="#9ca3af">
                          ¥{val.toFixed(0)}
                        </text>
                      </g>
                    )
                  })}
                  {data.price_history.map((pp, i) => {
                    const x = 50 + (i / Math.max(data.price_history.length - 1, 1)) * 540
                    const minY = 220 - 10 - ((pp.min_price - priceMin) / priceRange) * 200
                    const maxY = 220 - 10 - ((pp.max_price - priceMin) / priceRange) * 200
                    const avgY = 220 - 10 - ((pp.avg_price - priceMin) / priceRange) * 200
                    const d = new Date(pp.date + 'T00:00:00')
                    const label = `${d.getMonth() + 1}/${d.getDate()}`
                    return (
                      <g key={pp.date}>
                        <line x1={x} y1={minY} x2={x} y2={maxY} stroke="#93c5fd" strokeWidth={2} />
                        <rect x={x - 3} y={maxY - 1.5} width={6} height={3} rx={1} fill="#3b82f6" />
                        <rect x={x - 3} y={minY - 1.5} width={6} height={3} rx={1} fill="#3b82f6" />
                        <circle cx={x} cy={avgY} r={3} fill="#ef4444" />
                        {i % 5 === 0 && (
                          <text x={x} y={235} textAnchor="middle" fontSize={9} fill="#9ca3af">
                            {label}
                          </text>
                        )}
                      </g>
                    )
                  })}
                  {data.price_history.length > 1 && (() => {
                    const points = data.price_history.map((pp, i) => {
                      const x = 50 + (i / (data.price_history.length - 1)) * 540
                      const y = 220 - 10 - ((pp.avg_price - priceMin) / priceRange) * 200
                      return `${x},${y}`
                    }).join(' ')
                    return <polyline points={points} fill="none" stroke="#ef4444" strokeWidth={1.5} strokeDasharray="4,2" />
                  })()}
                  <line x1={50} y1={10} x2={50} y2={210} stroke="#d1d5db" strokeWidth={1} />
                  <line x1={50} y1={210} x2={590} y2={210} stroke="#d1d5db" strokeWidth={1} />
                  <text x={320} y={18} textAnchor="middle" fontSize={11} fill="#6b7280">
                    ▬ 最低-最高 (蓝) · 日均价 (红)
                  </text>
                </svg>
              </div>
            )}
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-5">
            <h2 className="mb-3 text-sm font-semibold text-gray-700">关联关键词</h2>
            {data.keywords.length === 0 ? (
              <p className="text-sm text-gray-400">暂无关联关键词</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {data.keywords.map((kw) => (
                  <span
                    key={kw.id}
                    className={cn(
                      'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium',
                      kw.is_active
                        ? 'bg-blue-100 text-blue-700'
                        : 'bg-gray-100 text-gray-400'
                    )}
                  >
                    {kw.name}
                    <span className="ml-1 opacity-60">
                      ({kw.platform === 'taobao' ? '淘宝' : kw.platform === 'tmall' ? '天猫' : kw.platform})
                    </span>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-white">
          <div className="border-b border-gray-200 px-5 py-3">
            <h2 className="text-sm font-semibold text-gray-700">
              预警记录
              {data.alerts.length > 0 && (
                <span className="ml-2 text-xs font-normal text-gray-400">
                  共 {data.alerts.length} 条
                </span>
              )}
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  <th className="px-4 py-3 font-medium w-16">类型</th>
                  <th className="px-4 py-3 font-medium">预警消息</th>
                  <th className="px-4 py-3 font-medium w-20">状态</th>
                  <th className="px-4 py-3 font-medium w-36">时间</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {data.alerts.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center text-gray-400">
                      暂无预警记录
                    </td>
                  </tr>
                ) : (
                  data.alerts.map((a) => (
                    <tr key={a.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold',
                            a.alert_type === 'price'
                              ? 'bg-red-100 text-red-700'
                              : 'bg-orange-100 text-orange-700'
                          )}
                        >
                          {a.alert_type === 'price' ? '价格' : '销量'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-700">{a.message}</td>
                      <td className="px-4 py-3">
                        {a.status === 'processed' ? (
                          <span className="text-green-600 text-xs">已处理</span>
                        ) : (
                          <span className="text-gray-400 text-xs">未处理</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">
                        {a.created_at
                          ? new Date(a.created_at).toLocaleString('zh-CN', {
                              month: '2-digit',
                              day: '2-digit',
                              hour: '2-digit',
                              minute: '2-digit',
                            })
                          : '-'}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
