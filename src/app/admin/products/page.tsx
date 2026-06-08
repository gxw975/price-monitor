'use client'

import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function ProductsPage() {
  const router = useRouter()
  useEffect(() => { router.replace('/admin/monitor-products') }, [router])
  return <div style={{ padding: 24, color: '#999' }}>正在跳转到商品监控...</div>
}
