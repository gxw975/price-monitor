'use client'

import { apiFetch, cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'

interface Keyword {
  id: number
  name: string
  platform: string
  is_active: boolean
  created_by_name: string
  product_count: number
  crawled_today: number
  last_crawl_time: string | null
  created_at: string | null
}

export default function KeywordsPage() {
  const { user } = useAuth()
  const router = useRouter()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'
  const fileRef = useRef<HTMLInputElement>(null)

  const [keywords, setKeywords] = useState<Keyword[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'active' | 'inactive'>('all')
  const [showForm, setShowForm] = useState(false)
  const [formName, setFormName] = useState('')
  const [formPlatform, setFormPlatform] = useState('taobao')
  const [error, setError] = useState('')
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<{ created: number; skipped: number; errors: string[] } | null>(null)

  const fetchKeywords = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filter === 'active') params.set('is_active', 'true')
      if (filter === 'inactive') params.set('is_active', 'false')
      const data = await apiFetch(`/api/keywords/list?${params}`)
      setKeywords(data.items)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { fetchKeywords() }, [fetchKeywords])

  const handleCreate = async () => {
    if (!formName.trim()) { setError('请输入关键词名称'); return }
    setError('')
    try {
      await apiFetch('/api/keywords/create', { method: 'POST', body: JSON.stringify({ name: formName.trim(), platform: formPlatform }) })
      setFormName(''); setShowForm(false); fetchKeywords()
    } catch (err: any) { setError(err.message || '创建失败') }
  }

  const handleToggleActive = async (kw: Keyword) => {
    try {
      await apiFetch(`/api/keywords/${kw.id}`, { method: 'PUT', body: JSON.stringify({ is_active: !kw.is_active }) })
      fetchKeywords()
    } catch (err) { console.error(err) }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这个关键词吗？')) return
    try { await apiFetch(`/api/keywords/${id}`, { method: 'DELETE' }); fetchKeywords() }
    catch (err) { console.error(err) }
  }

  const batchToggle = async (active: boolean) => {
    if (!selectedIds.size) return
    try {
      await apiFetch('/api/keywords/batch-toggle', {
        method: 'POST',
        body: JSON.stringify({ ids: Array.from(selectedIds), is_active: active }),
      })
      setSelectedIds(new Set())
      fetchKeywords()
    } catch (err) { console.error(err) }
  }

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true)
    setImportResult(null)
    try {
      const form = new FormData()
      form.append('file', file)
      const token = localStorage.getItem('auth_token')
      const res = await fetch('/api/import/keywords', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      })
      const data = await res.json()
      if (res.ok) {
        setImportResult(data)
        fetchKeywords()
      } else {
        setError(data.detail || '导入失败')
      }
    } catch (err: any) {
      setError(err.message || '导入失败')
    } finally {
      setImporting(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const handleExport = async () => {
    try {
      const params = filter === 'active' ? '?is_active=true' : filter === 'inactive' ? '?is_active=false' : ''
      const token = localStorage.getItem('auth_token')
      const res = await fetch(`/api/import/export/keywords${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) throw new Error('导出失败')
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `keywords_${new Date().toISOString().slice(0, 10)}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) { console.error(err) }
  }

  const handleSelectAll = () => {
    if (selectedIds.size === keywords.length) setSelectedIds(new Set())
    else setSelectedIds(new Set(keywords.map((k) => k.id)))
  }

  const getCrawlStatus = (kw: Keyword) => {
    if (kw.product_count === 0) return { text: '无商品', color: 'text-gray-400', bg: 'bg-gray-100' }
    if (kw.crawled_today === 0 && !kw.last_crawl_time) return { text: '未抓取', color: 'text-gray-500', bg: 'bg-gray-100' }
    if (kw.crawled_today > 0) return { text: `今日 ${kw.crawled_today}`, color: 'text-green-700', bg: 'bg-green-100' }
    if (kw.last_crawl_time) {
      const days = Math.floor((Date.now() - new Date(kw.last_crawl_time).getTime()) / 86400000)
      if (days <= 1) return { text: '昨日抓取', color: 'text-blue-700', bg: 'bg-blue-100' }
      return { text: `${days}天前`, color: 'text-yellow-700', bg: 'bg-yellow-100' }
    }
    return { text: '待抓取', color: 'text-gray-500', bg: 'bg-gray-100' }
  }

  const formatCrawlTime = (t: string | null) => {
    if (!t) return '-'
    const d = new Date(t); const now = new Date()
    const diffMin = Math.floor((now.getTime() - d.getTime()) / 60000)
    if (diffMin < 1) return '刚刚'
    if (diffMin < 60) return `${diffMin}分钟前`
    const diffHour = Math.floor(diffMin / 60)
    if (diffHour < 24) return `${diffHour}小时前`
    return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">关键词监控</h1>
          <span className="text-sm text-gray-500">管理搜索关键词</span>
        </div>

        <div className="mb-4 flex items-center gap-3 flex-wrap">
          <select value={filter} onChange={(e) => setFilter(e.target.value as any)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white">
            <option value="all">全部</option>
            <option value="active">启用</option>
            <option value="inactive">禁用</option>
          </select>

          {canWrite && (
            <>
              <button onClick={() => { setShowForm(!showForm); setError('') }}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700">
                {showForm ? '取消' : '添加关键词'}
              </button>
              <label className="rounded-md bg-purple-600 px-4 py-2 text-sm text-white hover:bg-purple-700 cursor-pointer">
                {importing ? '导入中...' : '批量导入'}
                <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv" onChange={handleImport}
                  className="hidden" disabled={importing} />
              </label>
            </>
          )}

          {selectedIds.size > 0 && canWrite && (
            <>
              <button onClick={() => batchToggle(true)}
                className="rounded-md bg-green-600 px-3 py-2 text-xs text-white hover:bg-green-700">
                批量启用 ({selectedIds.size})
              </button>
              <button onClick={() => batchToggle(false)}
                className="rounded-md bg-yellow-600 px-3 py-2 text-xs text-white hover:bg-yellow-700">
                批量禁用 ({selectedIds.size})
              </button>
            </>
          )}

          <button onClick={handleExport}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 ml-auto">
            导出 Excel
          </button>
        </div>

        {importResult && (
          <div className="mb-4 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
            ✅ 导入完成: 新建 {importResult.created} 个, 跳过 {importResult.skipped} 个
            {importResult.errors.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-xs">
                {importResult.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            )}
          </div>
        )}

        {showForm && canWrite && (
          <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-end gap-3 flex-wrap">
              <div className="flex-1 min-w-[200px]">
                <label className="block text-sm font-medium text-gray-700 mb-1">关键词</label>
                <input type="text" value={formName} onChange={(e) => setFormName(e.target.value)}
                  placeholder="例如：连衣裙 夏季"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">平台</label>
                <select value={formPlatform} onChange={(e) => setFormPlatform(e.target.value)}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white">
                  <option value="taobao">淘宝</option>
                  <option value="tmall">天猫</option>
                  <option value="jd">京东</option>
                </select>
              </div>
              <button onClick={handleCreate}
                className="rounded-md bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700">添加</button>
            </div>
            {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
          </div>
        )}

        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  {canWrite && (
                    <th className="w-10 px-4 py-3">
                      <input type="checkbox" checked={selectedIds.size === keywords.length && keywords.length > 0}
                        onChange={handleSelectAll} className="rounded" />
                    </th>
                  )}
                  <th className="px-4 py-3 font-medium">关键词</th>
                  <th className="px-4 py-3 font-medium">平台</th>
                  <th className="px-4 py-3 font-medium">监控商品</th>
                  <th className="px-4 py-3 font-medium">抓取状态</th>
                  <th className="px-4 py-3 font-medium">最近抓取</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">创建人</th>
                  {canWrite && <th className="px-4 py-3 font-medium w-32">操作</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr><td colSpan={canWrite ? 9 : 8} className="px-4 py-12 text-center text-gray-400">加载中...</td></tr>
                ) : keywords.length === 0 ? (
                  <tr><td colSpan={canWrite ? 9 : 8} className="px-4 py-12 text-center text-gray-400">暂无关键词</td></tr>
                ) : (
                  keywords.map((kw) => {
                    const cs = getCrawlStatus(kw)
                    return (
                      <tr key={kw.id} className="hover:bg-gray-50">
                        {canWrite && (
                          <td className="px-4 py-3">
                            <input type="checkbox" checked={selectedIds.has(kw.id)}
                              onChange={() => {
                                const next = new Set(selectedIds)
                                if (next.has(kw.id)) next.delete(kw.id)
                                else next.add(kw.id)
                                setSelectedIds(next)
                              }} className="rounded" />
                          </td>
                        )}
                        <td className="px-4 py-3 font-medium text-gray-900">
                          <button onClick={() => router.push(`/admin/products?keyword=${encodeURIComponent(kw.name)}`)}
                            className="hover:text-blue-600 cursor-pointer">{kw.name}</button>
                        </td>
                        <td className="px-4 py-3">
                          <span className="rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700">
                            {kw.platform === 'taobao' ? '淘宝' : kw.platform === 'tmall' ? '天猫' : kw.platform === 'jd' ? '京东' : kw.platform}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-500">{kw.product_count} 个</td>
                        <td className="px-4 py-3">
                          <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium', cs.bg, cs.color)}>
                            {cs.text}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-500 whitespace-nowrap text-xs">{formatCrawlTime(kw.last_crawl_time)}</td>
                        <td className="px-4 py-3">
                          <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                            kw.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500')}>
                            {kw.is_active ? '启用' : '禁用'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-500">{kw.created_by_name || '-'}</td>
                        {canWrite && (
                          <td className="px-4 py-3">
                            <div className="flex gap-2">
                              <button onClick={() => handleToggleActive(kw)} className="text-xs text-blue-600 hover:text-blue-800">
                                {kw.is_active ? '禁用' : '启用'}
                              </button>
                              <button onClick={() => handleDelete(kw.id)} className="text-xs text-red-600 hover:text-red-800">删除</button>
                            </div>
                          </td>
                        )}
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}
