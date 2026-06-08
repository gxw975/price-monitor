'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useState, useEffect } from 'react'

interface Product {
  product_id: string
  title: string
  shop_name: string
  main_image_url: string
  is_approved: boolean
}

export default function ProductsPage() {
  const { user } = useAuth()
  const canWrite = user?.role === 'admin' || user?.role === 'manager'

  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)
  const [uploadVisible, setUploadVisible] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [importResult, setImportResult] = useState<{
    success_count: number
    fail_count: number
    total: number
  } | null>(null)

  const fetchProducts = async () => {
    setLoading(true)
    try {
      const res = await apiFetch('/api/product-keywords/products?limit=200')
      const data = await res.json()
      setProducts(data.items || [])
    } catch (err) {
      console.error('获取商品列表失败', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchProducts()
  }, [])

  const handleUpload = async (file: File) => {
    setUploading(true)
    setImportResult(null)
    const formData = new FormData()
    formData.append('file', file)

    try {
      const token = localStorage.getItem('token')
      const res = await fetch('/api/products/import-excel', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      })
      const json = await res.json()
      if (!res.ok) throw new Error(json.detail || '导入失败')

      const data = json.data
      setImportResult({
        success_count: data.import_result?.success_count || 0,
        fail_count: data.import_result?.fail_count || 0,
        total: data.import_result?.total || 0,
      })
      alert(
        `导入完成！成功 ${data.import_result?.success_count || 0} 条，` +
        `失败 ${data.import_result?.fail_count || 0} 条\n` +
        `预警检测：触发 ${data.alert_result?.sent || 0} 条推送`
      )
      setUploadVisible(false)
      fetchProducts()
    } catch (err: any) {
      alert(err.message || '导入失败，请检查文件格式')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 700 }}>商品管理</h1>
        <div style={{ display: 'flex', gap: '8px' }}>
          {canWrite && (
            <button
              onClick={() => setUploadVisible(true)}
              style={{
                padding: '8px 16px',
                backgroundColor: '#1677ff',
                color: '#fff',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '14px',
              }}
            >
              导入 DTS Excel
            </button>
          )}
          <button
            onClick={fetchProducts}
            style={{
              padding: '8px 16px',
              backgroundColor: '#fff',
              border: '1px solid #d9d9d9',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '14px',
            }}
          >
            刷新
          </button>
        </div>
      </div>

      {loading ? (
        <p>加载中...</p>
      ) : products.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '40px', color: '#999' }}>
          <p>暂无商品数据</p>
          {canWrite && <p style={{ marginTop: '8px' }}>请点击「导入 DTS Excel」上传店透视导出的商品数据</p>}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '14px' }}>
            <thead>
              <tr style={{ backgroundColor: '#fafafa', borderBottom: '1px solid #f0f0f0' }}>
                <th style={thStyle}>商品图片</th>
                <th style={thStyle}>商品ID</th>
                <th style={thStyle}>标题</th>
                <th style={thStyle}>店铺</th>
                <th style={thStyle}>审核状态</th>
              </tr>
            </thead>
            <tbody>
              {products.map((p) => (
                <tr key={p.product_id} style={{ borderBottom: '1px solid #f0f0f0' }}>
                  <td style={tdStyle}>
                    {p.main_image_url ? (
                      <img src={p.main_image_url} alt="" style={{ width: '60px', height: '60px', objectFit: 'cover', borderRadius: '4px' }} />
                    ) : (
                      <div style={{ width: '60px', height: '60px', backgroundColor: '#f5f5f5', borderRadius: '4px' }} />
                    )}
                  </td>
                  <td style={tdStyle}>
                    <a href={`/admin/products/${p.product_id}`} style={{ color: '#1677ff' }}>
                      {p.product_id}
                    </a>
                  </td>
                  <td style={{ ...tdStyle, maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.title}
                  </td>
                  <td style={tdStyle}>{p.shop_name}</td>
                  <td style={tdStyle}>
                    <span style={{
                      padding: '2px 8px',
                      borderRadius: '4px',
                      fontSize: '12px',
                      backgroundColor: p.is_approved ? '#f6ffed' : '#fff7e6',
                      color: p.is_approved ? '#52c41a' : '#fa8c16',
                      border: `1px solid ${p.is_approved ? '#b7eb8f' : '#ffd591'}`,
                    }}>
                      {p.is_approved ? '已审核' : '未审核'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {uploadVisible && (
        <div style={{
          position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.45)',
          display: 'flex', justifyContent: 'center', alignItems: 'center',
          zIndex: 1000,
        }}>
          <div style={{ backgroundColor: '#fff', borderRadius: '8px', padding: '24px', width: '480px', maxHeight: '80vh' }}>
            <h2 style={{ fontSize: '18px', fontWeight: 600, marginBottom: '16px' }}>导入商品数据</h2>
            <p style={{ color: '#666', marginBottom: '8px' }}>
              请上传店透视（DTS）导出的Excel文件，系统将自动解析商品、价格和销量数据
            </p>
            <p style={{ color: '#fa8c16', fontSize: '13px', marginBottom: '16px' }}>
              注意：仅支持.xlsx和.xls格式，文件大小不超过10MB
            </p>

            <input
              type="file"
              accept=".xlsx,.xls"
              disabled={uploading}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (!file) return
                if (!file.name.endsWith('.xlsx') && !file.name.endsWith('.xls')) {
                  alert('仅支持Excel文件格式')
                  return
                }
                if (file.size > 10 * 1024 * 1024) {
                  alert('文件大小不能超过10MB')
                  return
                }
                handleUpload(file)
              }}
              style={{ marginBottom: '16px', display: 'block' }}
            />

            {uploading && <p style={{ color: '#1677ff' }}>正在上传并解析文件...</p>}

            <div style={{ textAlign: 'right', marginTop: '16px' }}>
              <button
                onClick={() => { setUploadVisible(false); setImportResult(null) }}
                disabled={uploading}
                style={{
                  padding: '6px 16px',
                  border: '1px solid #d9d9d9',
                  borderRadius: '6px',
                  backgroundColor: '#fff',
                  cursor: uploading ? 'not-allowed' : 'pointer',
                }}
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '12px 16px',
  fontWeight: 600,
  color: '#333',
}

const tdStyle: React.CSSProperties = {
  padding: '12px 16px',
  color: '#555',
}
