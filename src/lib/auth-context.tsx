'use client'

import { createContext, useCallback, useContext, useEffect, useState } from 'react'

interface User {
  user_id: number
  username: string
  role: string
}

interface AuthContextType {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string) => Promise<{ success: boolean; error?: string }>
  logout: () => void
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  token: null,
  isAuthenticated: false,
  isLoading: true,
  login: async () => ({ success: false }),
  logout: () => {},
})

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const loadFromStorage = useCallback(() => {
    const stored = localStorage.getItem('auth_token')
    const storedUser = localStorage.getItem('auth_user')
    if (stored && storedUser) {
      try {
        setToken(stored)
        setUser(JSON.parse(storedUser))
      } catch {
        localStorage.removeItem('auth_token')
        localStorage.removeItem('auth_user')
      }
    }
    setIsLoading(false)
  }, [])

  useEffect(() => {
    loadFromStorage()
  }, [loadFromStorage])

  const login = useCallback(async (username: string, password: string) => {
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })

      if (!res.ok) {
        const data = await res.json()
        return { success: false, error: data.detail || '登录失败' }
      }

      const data = await res.json()
      const newToken = data.token
      const userInfo: User = { user_id: 0, username: data.username, role: data.role }

      localStorage.setItem('auth_token', newToken)
      localStorage.setItem('auth_user', JSON.stringify(userInfo))
      setToken(newToken)
      setUser(userInfo)

      try {
        const meRes = await fetch('/api/auth/me', {
          headers: { Authorization: `Bearer ${newToken}` },
        })
        if (meRes.ok) {
          const meData = await meRes.json()
          const fullUser: User = {
            user_id: meData.user_id,
            username: meData.username,
            role: meData.role,
          }
          localStorage.setItem('auth_user', JSON.stringify(fullUser))
          setUser(fullUser)
        }
      } catch {
        // me lookup is optional
      }

      return { success: true }
    } catch {
      return { success: false, error: '网络错误，请重试' }
    }
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('auth_token')
    localStorage.removeItem('auth_user')
    setToken(null)
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isAuthenticated: !!token,
        isLoading,
        login,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}

export function getAuthHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null
  return token ? { Authorization: `Bearer ${token}` } : {}
}
