import { useCallback, useEffect, useMemo, useState } from 'react'
import { API_BASE } from '../../types'
import { useTenantContext } from '../../context/TenantContext'

type UserRecord = {
  id: string
  email: string
  display_name: string
  status: string
  tenant_role?: string
  has_password?: boolean | number
}

const TENANT_ROLES = ['viewer', 'editor', 'owner']

type GroupRecord = {
  id: string
  name: string
  description: string
  member_count?: number
}

type ProjectRecord = {
  id: string
  name: string
  description: string
  status: string
}

type AclRecord = {
  id: string
  project_id?: string | null
  principal_type: string
  principal_id: string
  resource: string
  action: string
  effect: string
}

type TenantRecord = {
  id: string
  name: string
  slug: string
  status: string
}

interface Props {
  /** 'members' = users, groups, ACLs and the access check; 'workspaces' = tenants and projects. */
  section: 'members' | 'workspaces'
}

/** " — 3 apps, 1 secrets" from a delete response's {table: rows} */
function removedSummary(removed: Record<string, number> | undefined): string {
  const parts = Object.entries(removed ?? {}).map(([table, n]) => `${n} ${table.replaceAll('_', ' ')}`)
  return parts.length ? ` — removed ${parts.join(', ')}` : ''
}

export function IamAdminPanel({ section }: Props) {
  const { scope, canAdmin, users: ctxUsers, projects: ctxProjects, refresh: refreshContext } = useTenantContext()

  const [tenants, setTenants] = useState<TenantRecord[]>([])
  const [users, setUsers] = useState<UserRecord[]>([])
  const [groups, setGroups] = useState<GroupRecord[]>([])
  const [projects, setProjects] = useState<ProjectRecord[]>([])
  const [acls, setAcls] = useState<AclRecord[]>([])
  const [groupMembers, setGroupMembers] = useState<Record<string, UserRecord[]>>({})
  const [selectedGroupId, setSelectedGroupId] = useState('')

  const [newUserEmail, setNewUserEmail] = useState('')
  const [newUserName, setNewUserName] = useState('')
  const [newUserRole, setNewUserRole] = useState('viewer')
  const [newUserPassword, setNewUserPassword] = useState('')
  const [newGroupName, setNewGroupName] = useState('')
  const [newGroupDesc, setNewGroupDesc] = useState('')
  const [newProjectName, setNewProjectName] = useState('')
  const [newProjectDesc, setNewProjectDesc] = useState('')
  const [newTenantName, setNewTenantName] = useState('')
  const [newTenantSlug, setNewTenantSlug] = useState('')

  const [aclProjectId, setAclProjectId] = useState('')
  const [aclPrincipalType, setAclPrincipalType] = useState('group')
  const [aclPrincipalId, setAclPrincipalId] = useState('')
  const [aclResource, setAclResource] = useState('apps')
  const [aclAction, setAclAction] = useState('read')
  const [aclEffect, setAclEffect] = useState('allow')
  const [checkUserId, setCheckUserId] = useState('')
  const [checkProjectId, setCheckProjectId] = useState('')
  const [checkResource, setCheckResource] = useState('apps')
  const [checkAction, setCheckAction] = useState('read')
  const [checkResult, setCheckResult] = useState<null | { allowed: boolean; detail: string }>(null)
  const [statusMsg, setStatusMsg] = useState('')
  const [statusType, setStatusType] = useState<'info' | 'success' | 'error'>('info')

  const showSuccess = (msg: string) => {
    setStatusType('success')
    setStatusMsg(msg)
  }

  const showError = (msg: string) => {
    setStatusType('error')
    setStatusMsg(msg)
  }

  const getErrorMessage = async (res: Response, fallback: string) => {
    try {
      const payload = await res.json()
      return payload?.detail || fallback
    } catch {
      return fallback
    }
  }

  const loadAll = useCallback(async () => {
    try {
      const [tRes, uRes, gRes, pRes, aRes] = await Promise.allSettled([
        fetch(`${API_BASE}/api/iam/tenants`),
        fetch(`${API_BASE}/api/iam/users`),
        fetch(`${API_BASE}/api/iam/groups`),
        fetch(`${API_BASE}/api/iam/projects`),
        fetch(`${API_BASE}/api/iam/acls`),
      ])

      let hadFailure = false

      if (tRes.status === 'fulfilled' && tRes.value.ok) {
        const data = await tRes.value.json()
        setTenants(data?.tenants ?? [])
      } else {
        hadFailure = true
      }

      if (uRes.status === 'fulfilled' && uRes.value.ok) {
        const data = await uRes.value.json()
        const rows = data?.users ?? []
        setUsers(rows)
        if (!checkUserId && rows.length > 0) {
          setCheckUserId(rows[0].id)
        }
      } else {
        hadFailure = true
      }
      if (gRes.status === 'fulfilled' && gRes.value.ok) {
        const data = await gRes.value.json()
        const rows = data?.groups ?? []
        setGroups(rows)
        if (!selectedGroupId && rows.length > 0) setSelectedGroupId(rows[0].id)
      } else {
        hadFailure = true
      }
      if (pRes.status === 'fulfilled' && pRes.value.ok) {
        const data = await pRes.value.json()
        const rows = data?.projects ?? []
        setProjects(rows)
        if (!checkProjectId && rows.length > 0) {
          setCheckProjectId(rows[0].id)
        }
      } else {
        hadFailure = true
      }
      if (aRes.status === 'fulfilled' && aRes.value.ok) {
        const data = await aRes.value.json()
        setAcls(data?.acls ?? [])
      } else if (aRes.status === 'fulfilled' && aRes.value.status === 403) {
        setAcls([]) // ACLs are visible to IAM admins only
      } else {
        hadFailure = true
      }
      await refreshContext()
      if (hadFailure) {
        showError('Some IAM endpoints failed to load. You can still use available sections and click Reload IAM.')
      }
    } catch {
      showError('Failed to load IAM data from backend')
    }
  }, [refreshContext, selectedGroupId])

  useEffect(() => {
    loadAll()
  }, [loadAll])

  const loadGroupMembers = useCallback(async (groupId: string) => {
    if (!groupId) return
    try {
      const res = await fetch(`${API_BASE}/api/iam/groups/${groupId}/members`)
      if (!res.ok) return
      const data = await res.json()
      setGroupMembers((prev) => ({ ...prev, [groupId]: data?.members ?? [] }))
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    if (!selectedGroupId) return
    loadGroupMembers(selectedGroupId)
  }, [selectedGroupId, loadGroupMembers])

  const userOptions = useMemo(() => {
    if (ctxUsers.length > 0) return ctxUsers
    return users.map((u) => ({ id: u.id, display_name: u.display_name }))
  }, [ctxUsers, users])

  const projectOptions = useMemo(() => {
    if (ctxProjects.length > 0) return ctxProjects
    return projects.map((p) => ({ id: p.id, name: p.name }))
  }, [ctxProjects, projects])

  const createUser = async () => {
    if (!newUserEmail.trim() || !newUserName.trim()) {
      showError('Enter both user email and display name')
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/iam/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: newUserEmail.trim(),
          display_name: newUserName.trim(),
          status: 'active',
          role: newUserRole,
          password: newUserPassword || undefined,
        }),
      })
      if (!res.ok) {
        showError(await getErrorMessage(res, 'Failed to create user'))
        return
      }
      const created = await res.json()
      setNewUserEmail('')
      setNewUserName('')
      setNewUserPassword('')
      showSuccess(created?.existing_account
        ? 'Existing account added to this tenant'
        : created?.has_password
          ? 'User created — they can sign in now'
          : 'User created without a password — use "Set password" so they can sign in')
      await loadAll()
    } catch {
      showError('Failed to create user')
    }
  }

  const createGroup = async () => {
    if (!newGroupName.trim()) {
      showError('Enter group name')
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/iam/groups`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newGroupName.trim(), description: newGroupDesc.trim() }),
      })
      if (!res.ok) {
        showError(await getErrorMessage(res, 'Failed to create group'))
        return
      }
      setNewGroupName('')
      setNewGroupDesc('')
      showSuccess('Group created')
      await loadAll()
    } catch {
      showError('Failed to create group')
    }
  }

  const createProject = async () => {
    if (!newProjectName.trim()) {
      showError('Enter project name')
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/iam/projects`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newProjectName.trim(), description: newProjectDesc.trim() }),
      })
      if (!res.ok) {
        showError(await getErrorMessage(res, 'Failed to create project'))
        return
      }
      setNewProjectName('')
      setNewProjectDesc('')
      showSuccess('Project created')
      await loadAll()
    } catch {
      showError('Failed to create project')
    }
  }

  const addMemberToGroup = async (groupId: string, userId: string) => {
    if (!groupId || !userId) return
    const res = await fetch(`${API_BASE}/api/iam/groups/${groupId}/members`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    })
    if (res.ok) {
      showSuccess('Group membership updated')
      await loadGroupMembers(groupId)
      await loadAll()
    }
  }

  const removeMemberFromGroup = async (groupId: string, userId: string) => {
    const res = await fetch(`${API_BASE}/api/iam/groups/${groupId}/members/${userId}`, {
      method: 'DELETE',
    })
    if (res.ok) {
      showSuccess('Member removed from group')
      await loadGroupMembers(groupId)
      await loadAll()
    }
  }

  const createAcl = async () => {
    if (!aclPrincipalId.trim()) {
      showError('Enter ACL principal id')
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/iam/acls`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          project_id: aclProjectId || null,
          principal_type: aclPrincipalType,
          principal_id: aclPrincipalId.trim(),
          resource: aclResource.trim(),
          action: aclAction.trim(),
          effect: aclEffect,
        }),
      })
      if (!res.ok) {
        showError(await getErrorMessage(res, 'Failed to create ACL'))
        return
      }
      showSuccess('ACL added')
      await loadAll()
    } catch {
      showError('Failed to create ACL')
    }
  }

  const deleteAcl = async (aclId: string) => {
    const res = await fetch(`${API_BASE}/api/iam/acls/${aclId}`, { method: 'DELETE' })
    if (res.ok) {
      showSuccess('ACL removed')
      await loadAll()
    }
  }

  const updateUser = async (userId: string, patch: Record<string, string>, successMsg = 'User updated') => {
    const res = await fetch(`${API_BASE}/api/iam/users/${userId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (!res.ok) {
      showError(await getErrorMessage(res, 'Failed to update user'))
      return
    }
    showSuccess(successMsg)
    await loadAll()
  }

  const updateUserStatus = (userId: string, status: string) => updateUser(userId, { status })

  const setUserPassword = async (user: UserRecord) => {
    const password = window.prompt(`New password for ${user.email} (min 8 characters)`)
    if (!password) return
    await updateUser(user.id, { password }, 'Password set — their existing sessions were signed out')
  }

  const deleteUser = async (userId: string) => {
    const res = await fetch(`${API_BASE}/api/iam/users/${userId}`, { method: 'DELETE' })
    if (!res.ok) {
      showError(await getErrorMessage(res, 'Failed to delete user'))
      return
    }
    showSuccess('User deleted')
    await loadAll()
  }

  const renameGroup = async (group: GroupRecord) => {
    const nextName = window.prompt('Rename group', group.name)
    if (!nextName || !nextName.trim() || nextName.trim() === group.name) return
    const res = await fetch(`${API_BASE}/api/iam/groups/${group.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: nextName.trim() }),
    })
    if (res.ok) {
      showSuccess('Group renamed')
      await loadAll()
    }
  }

  const deleteGroup = async (groupId: string) => {
    const res = await fetch(`${API_BASE}/api/iam/groups/${groupId}`, { method: 'DELETE' })
    if (res.ok) {
      showSuccess('Group deleted')
      if (selectedGroupId === groupId) setSelectedGroupId('')
      await loadAll()
    }
  }

  const renameProject = async (project: ProjectRecord) => {
    const nextName = window.prompt('Rename project', project.name)
    if (!nextName || !nextName.trim() || nextName.trim() === project.name) return
    const res = await fetch(`${API_BASE}/api/iam/projects/${project.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: nextName.trim() }),
    })
    if (res.ok) {
      showSuccess('Project renamed')
      await loadAll()
    }
  }

  const deleteProject = async (projectId: string) => {
    if (!window.confirm(`Delete project ${projectId}?\n\nIts pipelines, versions, secrets, API keys, schedules, webhooks and access rules are deleted too. The audit log is kept.`)) return
    const res = await fetch(`${API_BASE}/api/iam/projects/${projectId}`, { method: 'DELETE' })
    if (res.ok) {
      showSuccess(`Project deleted${removedSummary((await res.json()).removed)}`)
      await loadAll()
      return
    }
    const payload = await res.json().catch(() => ({}))
    showError(payload?.detail || 'Failed to delete project')
  }

  const runAccessCheck = async () => {
    if (!checkUserId || !checkProjectId || !checkResource.trim() || !checkAction.trim()) return
    const res = await fetch(`${API_BASE}/api/iam/access-check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: checkUserId,
        project_id: checkProjectId,
        resource: checkResource.trim(),
        action: checkAction.trim(),
      }),
    })
    if (!res.ok) {
      setCheckResult({ allowed: false, detail: 'Failed to evaluate access' })
      return
    }
    const payload = await res.json()
    setCheckResult({
      allowed: Boolean(payload?.allowed),
      detail: `${payload?.user_id || checkUserId} -> ${payload?.resource || checkResource}:${payload?.action || checkAction} in ${payload?.project_id || checkProjectId}`,
    })
  }

  const createTenant = async () => {
    if (!newTenantName.trim()) {
      showError('Enter tenant name')
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/iam/tenants`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newTenantName.trim(), slug: newTenantSlug.trim() || undefined }),
      })
      if (!res.ok) {
        showError(await getErrorMessage(res, 'Failed to create tenant'))
        return
      }
      setNewTenantName('')
      setNewTenantSlug('')
      showSuccess('Tenant created')
      await loadAll()
      await refreshContext()
      return
    } catch {
      showError('Failed to create tenant')
    }
  }

  const renameTenant = async (tenant: TenantRecord) => {
    const nextName = window.prompt('Rename tenant', tenant.name)
    if (!nextName || !nextName.trim() || nextName.trim() === tenant.name) return
    const res = await fetch(`${API_BASE}/api/iam/tenants/${tenant.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: nextName.trim() }),
    })
    if (res.ok) {
      showSuccess('Tenant updated')
      await loadAll()
      await refreshContext()
      return
    }
    const payload = await res.json().catch(() => ({}))
    showError(payload?.detail || 'Failed to update tenant')
  }

  const deleteTenant = async (tenantId: string) => {
    if (!window.confirm(`Delete workspace ${tenantId}?\n\nEverything in it is deleted: projects, pipelines, secrets, API keys, members and groups. The audit log is kept.`)) return
    const res = await fetch(`${API_BASE}/api/iam/tenants/${tenantId}`, { method: 'DELETE' })
    if (res.ok) {
      showSuccess(`Tenant deleted${removedSummary((await res.json()).removed)}`)
      await loadAll()
      await refreshContext()
      return
    }
    const payload = await res.json().catch(() => ({}))
    showError(payload?.detail || 'Failed to delete tenant')
  }

  return (
    <div className="ops-iam-admin">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8, marginBottom: 10 }}>
        <button type="button" className="ops-refresh-btn" onClick={loadAll}>↻ Reload</button>
      </div>

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <span className="ops-count-badge">Tenant: {scope.tenantId}</span>
        <span className="ops-count-badge">Project: {scope.projectId}</span>
        <span className="ops-count-badge">User: {scope.userId}</span>
        <span className="ops-count-badge">{canAdmin ? 'IAM admin' : 'Read-only (needs iam:admin)'}</span>
      </div>

      {statusMsg && (
        <div
          style={{
            fontSize: 12,
            marginBottom: 10,
            borderRadius: 8,
            padding: '8px 10px',
            border: statusType === 'error' ? '1px solid #fecaca' : statusType === 'success' ? '1px solid #bbf7d0' : '1px solid #bfdbfe',
            background: statusType === 'error' ? '#fef2f2' : statusType === 'success' ? '#f0fdf4' : '#eff6ff',
            color: statusType === 'error' ? '#b91c1c' : statusType === 'success' ? '#166534' : '#1d4ed8',
          }}
        >
          {statusMsg}
        </div>
      )}

      {section === 'workspaces' && (
      <div className="ops-panel" style={{ marginBottom: 12 }}>
        <div className="ops-toolbar"><span className="ops-panel-title">Workspaces (tenants)</span></div>
        <div style={{ padding: 10, display: 'flex', gap: 6 }}>
          <input className="ops-select" style={{ flex: 1 }} placeholder="Tenant name" value={newTenantName} onChange={(e) => setNewTenantName(e.target.value)} />
          <input className="ops-select" style={{ flex: 1 }} placeholder="Slug (optional)" value={newTenantSlug} onChange={(e) => setNewTenantSlug(e.target.value)} />
          <button type="button" className="ops-refresh-btn" onClick={createTenant} disabled={!newTenantName.trim()}>Add</button>
        </div>
        <div className="ops-list" style={{ padding: 10 }}>
          {tenants.map((t) => (
            <div key={t.id} style={{ fontSize: 12, padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <strong>{t.name} ({t.id})</strong>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button type="button" className="ops-link-btn" onClick={() => renameTenant(t)}>Rename</button>
                  <button type="button" className="ops-link-btn" onClick={() => deleteTenant(t.id)}>Delete</button>
                </div>
              </div>
              <span style={{ color: '#64748b' }}>slug: {t.slug} · status: {t.status}</span>
            </div>
          ))}
        </div>
      </div>
      )}

      {section === 'members' && (
        <div className="ops-panel" style={{ minHeight: 260 }}>
          <div className="ops-toolbar"><span className="ops-panel-title">Users</span></div>
          <div style={{ padding: 10, display: 'flex', gap: 6 }}>
            <input className="ops-select" style={{ flex: 1 }} placeholder="Email" value={newUserEmail} onChange={(e) => setNewUserEmail(e.target.value)} />
            <input className="ops-select" style={{ flex: 1 }} placeholder="Display name" value={newUserName} onChange={(e) => setNewUserName(e.target.value)} />
            <input className="ops-select" style={{ flex: 1 }} type="password" autoComplete="new-password" placeholder="Password (optional)" value={newUserPassword} onChange={(e) => setNewUserPassword(e.target.value)} />
            <select className="ops-select" value={newUserRole} onChange={(e) => setNewUserRole(e.target.value)}>
              {TENANT_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
            <button type="button" className="ops-refresh-btn" onClick={createUser} disabled={!newUserEmail.trim() || !newUserName.trim()}>Add</button>
          </div>
          <div className="ops-list" style={{ padding: 10 }}>
            {users.map((u) => (
              <div key={u.id} style={{ fontSize: 12, padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <strong>{u.display_name} ({u.id})</strong>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <select
                      className="ops-select"
                      style={{ padding: '1px 4px', fontSize: 11 }}
                      value={u.tenant_role}
                      onChange={(e) => updateUser(u.id, { role: e.target.value }, 'Role updated')}
                    >
                      {TENANT_ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                    <button type="button" className="ops-link-btn" onClick={() => setUserPassword(u)}>Set password</button>
                    <button type="button" className="ops-link-btn" onClick={() => updateUserStatus(u.id, u.status === 'active' ? 'disabled' : 'active')}>
                      {u.status === 'active' ? 'Disable' : 'Enable'}
                    </button>
                    <button type="button" className="ops-link-btn" onClick={() => deleteUser(u.id)}>Delete</button>
                  </div>
                </div>
                <span style={{ color: '#64748b' }}>{u.email} · role: {u.tenant_role} · status: {u.status}{u.has_password ? '' : ' · no password yet'}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {section === 'workspaces' && (
        <div className="ops-panel" style={{ minHeight: 260 }}>
          <div className="ops-toolbar"><span className="ops-panel-title">Projects</span></div>
          <div style={{ padding: 10, display: 'flex', gap: 6 }}>
            <input className="ops-select" style={{ flex: 1 }} placeholder="Project name" value={newProjectName} onChange={(e) => setNewProjectName(e.target.value)} />
            <input className="ops-select" style={{ flex: 1 }} placeholder="Description" value={newProjectDesc} onChange={(e) => setNewProjectDesc(e.target.value)} />
            <button type="button" className="ops-refresh-btn" onClick={createProject} disabled={!newProjectName.trim()}>Add</button>
          </div>
          <div className="ops-list" style={{ padding: 10 }}>
            {projects.map((p) => (
              <div key={p.id} style={{ fontSize: 12, padding: '6px 0', borderBottom: '1px solid #f1f5f9' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <strong>{p.name} ({p.id})</strong>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button type="button" className="ops-link-btn" onClick={() => renameProject(p)}>Rename</button>
                    <button type="button" className="ops-link-btn" onClick={() => deleteProject(p.id)}>Delete</button>
                  </div>
                </div>
                <span style={{ color: '#64748b' }}>{p.description || 'No description'} · {p.status}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {section === 'members' && (
      <>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
        <div className="ops-panel" style={{ minHeight: 260 }}>
          <div className="ops-toolbar"><span className="ops-panel-title">Groups</span></div>
          <div style={{ padding: 10, display: 'flex', gap: 6 }}>
            <input className="ops-select" style={{ flex: 1 }} placeholder="Group name" value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} />
            <input className="ops-select" style={{ flex: 1 }} placeholder="Description" value={newGroupDesc} onChange={(e) => setNewGroupDesc(e.target.value)} />
            <button type="button" className="ops-refresh-btn" onClick={createGroup} disabled={!newGroupName.trim()}>Add</button>
          </div>

          <div style={{ padding: '0 10px 10px' }}>
            <select className="ops-select" style={{ width: '100%' }} value={selectedGroupId} onChange={(e) => setSelectedGroupId(e.target.value)}>
              <option value="">Select group</option>
              {groups.map((g) => <option key={g.id} value={g.id}>{g.name} ({g.member_count || 0})</option>)}
            </select>
            {selectedGroupId && (
              <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                <button type="button" className="ops-link-btn" onClick={() => {
                  const current = groups.find((g) => g.id === selectedGroupId)
                  if (current) void renameGroup(current)
                }}>Rename group</button>
                <button type="button" className="ops-link-btn" onClick={() => deleteGroup(selectedGroupId)}>Delete group</button>
              </div>
            )}
          </div>

          {selectedGroupId && (
            <div style={{ padding: '0 10px 10px', display: 'flex', gap: 6 }}>
              <select className="ops-select" style={{ flex: 1 }} onChange={(e) => addMemberToGroup(selectedGroupId, e.target.value)} defaultValue="">
                <option value="">Add member...</option>
                {userOptions.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
              </select>
            </div>
          )}

          <div className="ops-list" style={{ padding: 10 }}>
            {(groupMembers[selectedGroupId] ?? []).map((m) => (
              <div key={m.id} style={{ fontSize: 12, padding: '6px 0', borderBottom: '1px solid #f1f5f9', display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span>{m.display_name} ({m.id})</span>
                <button type="button" className="ops-link-btn" onClick={() => removeMemberFromGroup(selectedGroupId, m.id)}>Remove</button>
              </div>
            ))}
          </div>
        </div>

        <div className="ops-panel" style={{ minHeight: 260 }}>
          <div className="ops-toolbar"><span className="ops-panel-title">ACLs</span></div>
          <div style={{ padding: 10, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
            <select className="ops-select" value={aclProjectId} onChange={(e) => setAclProjectId(e.target.value)}>
              <option value="">Tenant-wide</option>
              {projectOptions.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <select className="ops-select" value={aclPrincipalType} onChange={(e) => setAclPrincipalType(e.target.value)}>
              <option value="user">user</option>
              <option value="group">group</option>
            </select>
            <input className="ops-select" placeholder="principal id" value={aclPrincipalId} onChange={(e) => setAclPrincipalId(e.target.value)} />
            <input className="ops-select" placeholder="resource (apps/tools/mcp/*)" value={aclResource} onChange={(e) => setAclResource(e.target.value)} />
            <input className="ops-select" placeholder="action (read/write/execute/*)" value={aclAction} onChange={(e) => setAclAction(e.target.value)} />
            <select className="ops-select" value={aclEffect} onChange={(e) => setAclEffect(e.target.value)}>
              <option value="allow">allow</option>
              <option value="deny">deny</option>
            </select>
            <button type="button" className="ops-refresh-btn" onClick={createAcl} style={{ gridColumn: '1 / span 2' }} disabled={!aclPrincipalId.trim()}>Add ACL</button>
          </div>

          <div className="ops-list" style={{ padding: 10 }}>
            {acls.map((a) => (
              <div key={a.id} style={{ fontSize: 12, padding: '6px 0', borderBottom: '1px solid #f1f5f9', display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span>
                  [{a.effect}] {a.principal_type}:{a.principal_id} → {a.resource}:{a.action}
                  {a.project_id ? ` (project=${a.project_id})` : ' (tenant-wide)'}
                </span>
                <button type="button" className="ops-link-btn" onClick={() => deleteAcl(a.id)}>Delete</button>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="ops-panel" style={{ marginTop: 12 }}>
        <div className="ops-toolbar"><span className="ops-panel-title">Access Check</span></div>
        <div style={{ padding: 10, display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr auto', gap: 6 }}>
          <select className="ops-select" value={checkUserId} onChange={(e) => setCheckUserId(e.target.value)}>
            <option value="">user</option>
            {userOptions.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
          </select>
          <select className="ops-select" value={checkProjectId} onChange={(e) => setCheckProjectId(e.target.value)}>
            <option value="">project</option>
            {projectOptions.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <input className="ops-select" value={checkResource} onChange={(e) => setCheckResource(e.target.value)} placeholder="resource" />
          <input className="ops-select" value={checkAction} onChange={(e) => setCheckAction(e.target.value)} placeholder="action" />
          <button type="button" className="ops-refresh-btn" onClick={runAccessCheck}>Evaluate</button>
        </div>
        {checkResult && (
          <div style={{ padding: '0 10px 10px', fontSize: 12, color: checkResult.allowed ? '#15803d' : '#b91c1c' }}>
            {checkResult.allowed ? 'ALLOW' : 'DENY'}: {checkResult.detail}
          </div>
        )}
      </div>
      </>
      )}
    </div>
  )
}
