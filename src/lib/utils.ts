import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export async function apiFetch(path: string, options?: RequestInit) {
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const mergedOptions: RequestInit = {
    ...options,
  }
  if (mergedOptions.headers) {
    const existingHeaders = mergedOptions.headers as Record<string, string>
    mergedOptions.headers = { ...headers, ...existingHeaders }
  } else {
    mergedOptions.headers = headers
  }

  const res = await fetch(path, mergedOptions)

  if (res.status === 401 && typeof window !== 'undefined') {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_user')
    window.location.href = '/login'
    throw new Error('认证已过期，请重新登录')
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`API error ${res.status}: ${text}`)
  }
  return res.json()
}

export function formatPrice(price: number | string) {
  return `¥${Number(price).toFixed(2)}`
}

export function formatDateTime(dateStr: string) {
  return new Date(dateStr).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
