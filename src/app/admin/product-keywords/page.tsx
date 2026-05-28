'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useState } from 'react'

interface Product {
  product_id: string
  title: string
  shop_name: string
  main_image_url: string | null
  is_approved: boolean
}

interface Keyword {
  id: number
  name: string
  platform: string
  is_active: boolean
}

interface ProductKeyword {
  id: number
  name: string
  platform: string
  is_active: boolean
  created_by_name: string
  created_at: string
}

export default function ProductKeywordsPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'

  const [products, setProducts] = useState<Product[]>([])
  const [keywords, setKeywords] = useState<Keyword[]>([])
  const [selectedProduct, setSelectedProduct] = useState<string | null>(null)
  const [productKeywords, setProductKeywords] = useState<ProductKeyword[]>([])
  const [selectedKeywordIds, setSelectedKeywordIds] = useState<Set<number>>(new Set())
  const [productSearch, setProductSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const fetchProducts = useCallback(async () => {
    try {
      const params = new URLSearchParams()
      if (productSearch) params.set('keyword', productSearch)
      params.set('limit', '30')
      const data = await apiFetch(`/api/product-keywords/products?${params}`)
      setProducts(data.items)
    } catch (err) {
      console.error(err)
    }
  }, [productSearch])

  const fetchAllKeywords = useCallback(async () => {
    try {
      const data = await apiFetch('/api/keywords/list?is_active=true')
      setKeywords(data.items)
    } catch (err) {
      console.error(err)
    }
  }, [])

  const fetchProductKeywords = useCallback(async (pid: string) => {
    setLoading(true)
    try {
      const data = await apiFetch(`/api/product-keywords/by-product/${pid}`)
      setProductKeywords(data.items)
      setSelectedKeywordIds(new Set(data.items.map((k: ProductKeyword) => k.id)))
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAllKeywords()
  }, [fetchAllKeywords])

  useEffect(() => {
    fetchProducts()
  }, [fetchProducts])

  const handleSelectProduct = (pid: string) => {
    setSelectedProduct(pid)
    fetchProductKeywords(pid)
  }

  const toggleKeyword = (id: number) => {
    const next = new Set(selectedKeywordIds)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    setSelectedKeywordIds(next)
  }

  const handleSave = async () => {
    if (!selectedProduct) return
    setSaving(true)
    try {
      await apiFetch(`/api/product-keywords/by-product/${selectedProduct}`, {
        method: 'PUT',
        body: JSON.stringify({ keyword_ids: Array.from(selectedKeywordIds) }),
      })
      fetchProductKeywords(selectedProduct)
    } catch (err) {
      console.error(err)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-6xl">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">商品关键词关联</h1>
          <p className="mt-1 text-sm text-gray-500">为商品绑定监控关键词</p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="lg:col-span-1">
            <div className="rounded-lg border border-gray-200 bg-white">
              <div className="border-b border-gray-200 px-4 py-3">
                <input
                  type="text"
                  placeholder="搜索商品..."
                  value={productSearch}
                  onChange={(e) => setProductSearch(e.target.value)}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div className="max-h-[600px] overflow-y-auto">
                {products.length === 0 ? (
                  <p className="px-4 py-8 text-center text-sm text-gray-400">暂无匹配商品</p>
                ) : (
                  products.map((p) => (
                    <button
                      key={p.product_id}
                      onClick={() => handleSelectProduct(p.product_id)}
                      className={`w-full text-left px-4 py-3 border-b border-gray-100 hover:bg-blue-50 transition-colors ${
                        selectedProduct === p.product_id ? 'bg-blue-50 border-l-2 border-l-blue-500' : ''
                      }`}
                    >
                      <div className="text-sm font-medium text-gray-900 truncate">{p.title}</div>
                      <div className="mt-0.5 text-xs text-gray-500">
                        {p.shop_name}
                        {p.is_approved ? (
                          <span className="ml-2 text-green-600">✓ 已审核</span>
                        ) : (
                          <span className="ml-2 text-yellow-600">待审核</span>
                        )}
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="lg:col-span-2">
            {selectedProduct ? (
              loading ? (
                <div className="rounded-lg border border-gray-200 bg-white p-12 text-center text-gray-400">
                  加载中...
                </div>
              ) : (
                <div className="rounded-lg border border-gray-200 bg-white">
                  <div className="border-b border-gray-200 px-4 py-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-gray-700">
                        已关联关键词 ({productKeywords.length})
                      </span>
                      {canWrite && (
                        <button
                          onClick={handleSave}
                          disabled={saving}
                          className="rounded-md bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                        >
                          {saving ? '保存中...' : '保存'}
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="p-4">
                    {canWrite ? (
                      keywords.length === 0 ? (
                        <p className="text-sm text-gray-400">暂无可用关键词，请先在关键词管理页面添加</p>
                      ) : (
                        <div className="flex flex-wrap gap-2">
                          {keywords.map((kw) => {
                            const checked = selectedKeywordIds.has(kw.id)
                            return (
                              <label
                                key={kw.id}
                                className={`inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm cursor-pointer transition-colors ${
                                  checked
                                    ? 'border-blue-400 bg-blue-50 text-blue-700'
                                    : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                                }`}
                              >
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => toggleKeyword(kw.id)}
                                  className="rounded"
                                />
                                {kw.name}
                              </label>
                            )
                          })}
                        </div>
                      )
                    ) : (
                      <div className="space-y-1">
                        {productKeywords.length === 0 ? (
                          <p className="text-sm text-gray-400">暂无关联关键词</p>
                        ) : (
                          productKeywords.map((pk) => (
                            <div key={pk.id} className="flex items-center gap-2 rounded bg-gray-50 px-3 py-1.5 text-sm">
                              <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-700">
                                {pk.platform === 'taobao' ? '淘宝' : pk.platform}
                              </span>
                              <span className="text-gray-700">{pk.name}</span>
                            </div>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )
            ) : (
              <div className="rounded-lg border border-gray-200 bg-white p-12 text-center text-gray-400">
                请在左侧选择一个商品来设置关键词关联
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
