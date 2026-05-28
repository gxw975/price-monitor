'use client'

import { apiFetch } from '@/lib/utils'
import { useAuth } from '@/lib/auth-context'
import { useCallback, useEffect, useState } from 'react'

interface UserItem {
  id: number
  username: string
  role: string
  created_at: string | null
}

export default function UsersPage() {
  const { user: currentUser } = useAuth()
  const isAdmin = currentUser?.role === 'admin'

  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const [showCreate, setShowCreate] = useState(false)
  const [newUser, setNewUser] = useState({ username: '', password: '', role: 'staff' })
  const [createError, setCreateError] = useState('')

  const [editingId, setEditingId] = useState<number | null>(null)
  const [editForm, setEditForm] = useState({ username: '', role: '', password: '' })

  const [showPwdModal, setShowPwdModal] = useState(false)
  const [pwdForm, setPwdForm] = useState({ old_password: '', new_password: '', confirm: '' })
  const [pwdError, setPwdError] = useState('')

  const fetchUsers = useCallback(async () => {
    if (!isAdmin) { setLoading(false); return }
    try {
      const data = await apiFetch('/api/users/list')
      setUsers(data.items)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [isAdmin])

  useEffect(() => { fetchUsers() }, [fetchUsers])

  const handleCreate = async () => {
    setCreateError('')
    if (!newUser.username || !newUser.password) {
      setCreateError('用户名和密码不能为空')
      return
    }
    try {
      await apiFetch('/api/users/create', {
        method: 'POST',
        body: JSON.stringify(newUser),
      })
      setNewUser({ username: '', password: '', role: 'staff' })
      setShowCreate(false)
      setMsg({ type: 'success', text: `用户 ${newUser.username} 创建成功` })
      fetchUsers()
    } catch (err: any) {
      setCreateError(err.message || '创建失败')
    }
  }

  const startEdit = (u: UserItem) => {
    setEditingId(u.id)
    setEditForm({ username: u.username, role: u.role, password: '' })
    setMsg(null)
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditForm({ username: '', role: '', password: '' })
  }

  const handleUpdate = async (id: number) => {
    const body: Record<string, string> = {}
    if (editForm.username) body.username = editForm.username
    if (editForm.role) body.role = editForm.role
    if (editForm.password) body.password = editForm.password
    try {
      await apiFetch(`/api/users/${id}`, { method: 'PUT', body: JSON.stringify(body) })
      setEditingId(null)
      setMsg({ type: 'success', text: '用户信息已更新' })
      fetchUsers()
    } catch (err: any) {
      setMsg({ type: 'error', text: err.message || '更新失败' })
    }
  }

  const handleDelete = async (id: number, username: string) => {
    if (!confirm(`确定要删除用户「${username}」吗？其创建的关键词也会被清理。`)) return
    try {
      await apiFetch(`/api/users/${id}`, { method: 'DELETE' })
      setMsg({ type: 'success', text: `用户 ${username} 已删除` })
      fetchUsers()
    } catch (err: any) {
      setMsg({ type: 'error', text: err.message || '删除失败' })
    }
  }

  const handleChangePassword = async () => {
    setPwdError('')
    if (!pwdForm.old_password || !pwdForm.new_password) {
      setPwdError('请填写所有密码字段')
      return
    }
    if (pwdForm.new_password !== pwdForm.confirm) {
      setPwdError('两次输入的新密码不一致')
      return
    }
    try {
      await apiFetch('/api/users/change-password', {
        method: 'POST',
        body: JSON.stringify({ old_password: pwdForm.old_password, new_password: pwdForm.new_password }),
      })
      setShowPwdModal(false)
      setPwdForm({ old_password: '', new_password: '', confirm: '' })
      setMsg({ type: 'success', text: '密码修改成功' })
    } catch (err: any) {
      setPwdError(err.message || '修改失败')
    }
  }

  const roleLabels: Record<string, string> = {
    admin: '管理员',
    manager: '主管',
    staff: '员工',
  }

  if (!isAdmin && loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-gray-400">加载中...</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-900">用户管理</h1>
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowPwdModal(true)}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
            >
              修改密码
            </button>
            {isAdmin && (
              <button
                onClick={() => { setShowCreate(!showCreate); setCreateError('') }}
                className="rounded-md bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-700"
              >
                {showCreate ? '取消' : '添加用户'}
              </button>
            )}
          </div>
        </div>

        {msg && (
          <div className={`mb-4 rounded-lg px-4 py-3 text-sm ${
            msg.type === 'success' ? 'bg-green-50 text-green-700 border border-green-200' :
            'bg-red-50 text-red-700 border border-red-200'
          }`}>
            {msg.text}
          </div>
        )}

        {showCreate && isAdmin && (
          <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4">
            <div className="flex items-end gap-3 flex-wrap">
              <div>
                <label className="block text-xs text-gray-500 mb-1">用户名</label>
                <input
                  type="text"
                  value={newUser.username}
                  onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
                  className="w-36 rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">密码</label>
                <input
                  type="password"
                  value={newUser.password}
                  onChange={(e) => setNewUser({ ...newUser, password: e.target.value })}
                  className="w-36 rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">角色</label>
                <select
                  value={newUser.role}
                  onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}
                  className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                >
                  <option value="staff">员工</option>
                  <option value="manager">主管</option>
                  <option value="admin">管理员</option>
                </select>
              </div>
              <button
                onClick={handleCreate}
                className="rounded-md bg-green-600 px-4 py-2 text-sm text-white hover:bg-green-700"
              >
                创建
              </button>
            </div>
            {createError && <p className="mt-2 text-sm text-red-600">{createError}</p>}
          </div>
        )}

        {!isAdmin ? (
          <div className="rounded-lg border border-gray-200 bg-white p-12 text-center">
            <p className="text-gray-400">仅管理员可以管理用户</p>
            <p className="mt-1 text-sm text-gray-400">当前用户：{currentUser?.username}（{roleLabels[currentUser?.role || 'staff']}）</p>
          </div>
        ) : (
          <div className="rounded-lg border border-gray-200 bg-white overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left text-gray-600">
                  <tr>
                    <th className="px-4 py-3 font-medium">ID</th>
                    <th className="px-4 py-3 font-medium">用户名</th>
                    <th className="px-4 py-3 font-medium">角色</th>
                    <th className="px-4 py-3 font-medium">创建时间</th>
                    <th className="px-4 py-3 font-medium w-40">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {users.map((u) => (
                    <tr key={u.id} className="hover:bg-gray-50">
                      <td className="px-4 py-3 text-gray-500">{u.id}</td>
                      <td className="px-4 py-3">
                        {editingId === u.id ? (
                          <input
                            type="text"
                            value={editForm.username}
                            onChange={(e) => setEditForm({ ...editForm, username: e.target.value })}
                            className="w-36 rounded border border-gray-300 px-2 py-1 text-sm"
                          />
                        ) : (
                          <span className="font-medium text-gray-900">{u.username}</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {editingId === u.id ? (
                          <select
                            value={editForm.role}
                            onChange={(e) => setEditForm({ ...editForm, role: e.target.value })}
                            className="rounded border border-gray-300 px-2 py-1 text-sm bg-white"
                          >
                            <option value="staff">员工</option>
                            <option value="manager">主管</option>
                            <option value="admin">管理员</option>
                          </select>
                        ) : (
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            u.role === 'admin' ? 'bg-red-100 text-red-700' :
                            u.role === 'manager' ? 'bg-yellow-100 text-yellow-700' :
                            'bg-green-100 text-green-700'
                          }`}>
                            {roleLabels[u.role] || u.role}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                        {u.created_at ? new Date(u.created_at).toLocaleDateString('zh-CN') : '-'}
                      </td>
                      <td className="px-4 py-3">
                        {editingId === u.id ? (
                          <div className="flex gap-2">
                            <button
                              onClick={() => handleUpdate(u.id)}
                              className="text-xs text-green-600 hover:text-green-800"
                            >
                              保存
                            </button>
                            <button onClick={cancelEdit} className="text-xs text-gray-500 hover:text-gray-700">
                              取消
                            </button>
                            <input
                              type="password"
                              value={editForm.password}
                              onChange={(e) => setEditForm({ ...editForm, password: e.target.value })}
                              placeholder="新密码"
                              className="w-20 rounded border border-gray-300 px-1.5 py-0.5 text-xs"
                            />
                          </div>
                        ) : (
                          <div className="flex gap-2">
                            <button
                              onClick={() => startEdit(u)}
                              className="text-xs text-blue-600 hover:text-blue-800"
                            >
                              编辑
                            </button>
                            {u.id !== currentUser?.user_id && (
                              <button
                                onClick={() => handleDelete(u.id, u.username)}
                                className="text-xs text-red-600 hover:text-red-800"
                              >
                                删除
                              </button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {showPwdModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setShowPwdModal(false)}>
          <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-4 text-lg font-semibold text-gray-900">修改密码</h2>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">原密码</label>
                <input
                  type="password"
                  value={pwdForm.old_password}
                  onChange={(e) => setPwdForm({ ...pwdForm, old_password: e.target.value })}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onKeyDown={(e) => e.key === 'Enter' && handleChangePassword()}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">新密码</label>
                <input
                  type="password"
                  value={pwdForm.new_password}
                  onChange={(e) => setPwdForm({ ...pwdForm, new_password: e.target.value })}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">确认新密码</label>
                <input
                  type="password"
                  value={pwdForm.confirm}
                  onChange={(e) => setPwdForm({ ...pwdForm, confirm: e.target.value })}
                  className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                  onKeyDown={(e) => e.key === 'Enter' && handleChangePassword()}
                />
              </div>
              {pwdError && <p className="text-sm text-red-600">{pwdError}</p>}
              <div className="flex gap-2 pt-2">
                <button
                  onClick={handleChangePassword}
                  className="flex-1 rounded-md bg-blue-600 py-2 text-sm text-white hover:bg-blue-700"
                >
                  确认修改
                </button>
                <button
                  onClick={() => { setShowPwdModal(false); setPwdError('') }}
                  className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-100"
                >
                  取消
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
