'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useState } from 'react'

interface Keyword {
  id: number
  name: string
  platform: string
  is_active: boolean
  created_by_name: string
  product_count: number
  created_at: string
}

export default function KeywordsPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'

  const [keywords, setKeywords] = useState<Keyword[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'active' | 'inactive'>('all')
  const [showForm, setShowForm] = useState(false)
  const [formName, setFormName] = useState('')
  const [formPlatform, setFormPlatform] = useState('taobao')
  const [error, setError] = useState('')

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

  useEffect(() => {
    fetchKeywords()
  }, [fetchKeywords])

  const handleCreate = async () => {
    if (!formName.trim()) {
      setError('请输入关键词名称')
      return
    }
    setError('')
    try {
      await apiFetch('/api/keywords/create', {
        method: 'POST',
        body: JSON.stringify({ name: formName.trim(), platform: formPlatform }),
      })
      setFormName('')
      setShowForm(false)
      fetchKeywords()
    } catch (err: any) {
      setError(err.message || '创建失败')
    }
  }

  const handleToggleActive = async (kw: Keyword) => {
    try {
      await apiFetch(`/api/keywords/${kw.id}`, {
        method: 'PUT',
        body: JSON.stringify({ is_active: !kw.is_active }),
      })
      fetchKeywords()
    } catch (err) {
      console.error(err)
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这个关键词吗？关联的商品也会被解除。')) return
    try {
      await apiFetch(`/api/keywords/${id}`, { method: 'DELETE' })
      fetchKeywords()
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">关键词监控</h1>
          <span className="text-sm text-gray-500">管理搜索关键词</span>
        </div>

        <div className="mb-4 flex items-center gap-3 flex-wrap">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as any)}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
          >
            <option value="all">全部</option>
            <option value="active">启用</option>
            <option value="inactive">禁用</option>
          </select>

          {canWrite && (
            <button
              onClick={() => { setShowForm(!showForm); setError('') }}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
            >
              {showForm ? '取消' : '添加关键词'}
            </button>
          )}
        </div>

        {showForm && canWrite && (
          <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-end gap-3 flex-wrap">
              <div className="flex-1 min-w-[200px]">
                <label className="block text-sm font-medium text-gray-700 mb-1">关键词</label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="例如：连衣裙 夏季"
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">平台</label>
                <select
                  value={formPlatform}
                  onChange={(e) => setFormPlatform(e.target.value)}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                >
                  <option value="taobao">淘宝</option>
                  <option value="tmall">天猫</option>
                  <option value="jd">京东</option>
                </select>
              </div>
              <button
                onClick={handleCreate}
                className="rounded-md bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700"
              >
                添加
              </button>
            </div>
            {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
          </div>
        )}

        <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 text-left text-gray-600">
                <tr>
                  <th className="px-4 py-3 font-medium">关键词</th>
                  <th className="px-4 py-3 font-medium">平台</th>
                  <th className="px-4 py-3 font-medium">关联商品</th>
                  <th className="px-4 py-3 font-medium">状态</th>
                  <th className="px-4 py-3 font-medium">创建人</th>
                  <th className="px-4 py-3 font-medium">创建时间</th>
                  {canWrite && <th className="px-4 py-3 font-medium w-32">操作</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr>
                    <td colSpan={canWrite ? 7 : 6} className="px-4 py-12 text-center text-gray-400">
                      加载中...
                    </td>
                  </tr>
                ) : keywords.length === 0 ? (
                  <tr>
                    <td colSpan={canWrite ? 7 : 6} className="px-4 py-12 text-center text-gray-400">
                      暂无关键词
                    </td>
                  </tr>
                ) : (
                  keywords.map((kw) => (
                    <tr key={kw.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 font-medium text-gray-900">{kw.name}</td>
                      <td className="px-4 py-3">
                        <span className="rounded bg-blue-100 px-2 py-0.5 text-xs text-blue-700">
                          {kw.platform === 'taobao' ? '淘宝' : kw.platform === 'tmall' ? '天猫' : kw.platform === 'jd' ? '京东' : kw.platform}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-500">{kw.product_count} 个</td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                            kw.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                          }`}
                        >
                          {kw.is_active ? '启用' : '禁用'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-500">{kw.created_by_name || '-'}</td>
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                        {kw.created_at ? new Date(kw.created_at).toLocaleDateString('zh-CN') : '-'}
                      </td>
                      {canWrite && (
                        <td className="px-4 py-3">
                          <div className="flex gap-2">
                            <button
                              onClick={() => handleToggleActive(kw)}
                              className="text-xs text-blue-600 hover:text-blue-800"
                            >
                              {kw.is_active ? '禁用' : '启用'}
                            </button>
                            <button
                              onClick={() => handleDelete(kw.id)}
                              className="text-xs text-red-600 hover:text-red-800"
                            >
                              删除
                            </button>
                          </div>
                        </td>
                      )}
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
