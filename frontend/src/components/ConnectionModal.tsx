import { useState } from 'react'
import { API_BASE } from '../types'
import type { ConnectionRecord } from '../types'
import { ConnectionIcon } from './ConnectionIcon'
import { isSealed } from '../utils/secrets'

interface Props {
  connection?: ConnectionRecord
  onSaved: (conn: ConnectionRecord) => void
  onClose: () => void
}

const PROVIDERS: {
  type: ConnectionRecord['type']
  icon: string
  label: string
  defaultName: string
  tag?: string
}[] = [
  { type: 'postgres',   icon: '🐘', label: 'PostgreSQL',  defaultName: 'PostgreSQL Database' },
  { type: 'mysql',      icon: '🐬', label: 'MySQL',        defaultName: 'MySQL Database' },
  { type: 'mongodb',    icon: '🍃', label: 'MongoDB',      defaultName: 'MongoDB Database' },
  { type: 'redis',      icon: '🔴', label: 'Redis',        defaultName: 'Redis Cache' },
  { type: 'snowflake',  icon: '❄️', label: 'Snowflake',    defaultName: 'Snowflake Warehouse', tag: 'DW' },
  { type: 'aws_s3',     icon: '🪣', label: 'AWS S3',       defaultName: 'AWS S3 Bucket', tag: 'Object' },
  { type: 'sqlite',     icon: '💾', label: 'SQLite',       defaultName: 'SQLite Database', tag: 'Local' },
  { type: 'custom_api', icon: '⚡', label: 'Custom REST',  defaultName: 'Enterprise API', tag: 'HTTP' },
]

const PRESETS: Record<string, { label: string; patch: Record<string, any> }[]> = {
  postgres: [
    { label: 'Supabase',  patch: { host: 'db.xxx.supabase.co', port: '5432', ssl: 'require' } },
    { label: 'Neon',      patch: { host: 'ep-xxx.us-east-2.aws.neon.tech', port: '5432', ssl: 'require' } },
    { label: 'AWS RDS',   patch: { host: 'mydb.xxxx.us-east-1.rds.amazonaws.com', port: '5432', ssl: 'prefer' } },
  ],
  mysql: [
    { label: 'AWS RDS MySQL', patch: { host: 'mydb.xxxx.us-east-1.rds.amazonaws.com', port: '3306' } },
    { label: 'PlanetScale',   patch: { host: 'aws.connect.psdb.cloud', port: '3306' } },
  ],
  mongodb: [
    { label: 'MongoDB Atlas', patch: { host: 'cluster0.xxxxx.mongodb.net', port: '27017' } },
    { label: 'Local',         patch: { host: 'localhost', port: '27017' } },
  ],
  redis: [
    { label: 'Redis Cloud', patch: { host: 'redis-xxxxx.c1.us-east-1-2.ec2.cloud.redislabs.com', port: '6379' } },
    { label: 'Upstash',     patch: { host: 'global-xxxxx.upstash.io', port: '6379' } },
    { label: 'Local',       patch: { host: 'localhost', port: '6379' } },
  ],
}

// Saved credentials come back sealed ("enc://…"): show the field empty — leaving it blank keeps them
const plainCredential = (value: unknown) => (isSealed(value) || typeof value !== 'string' ? '' : value)

export function ConnectionModal({ connection, onSaved, onClose }: Props) {
  const isEdit = !!connection

  const [type, setType] = useState<ConnectionRecord['type']>(connection?.type ?? 'postgres')
  const [name, setName] = useState(connection?.name ?? 'PostgreSQL Production')
  const [icon, setIcon] = useState(connection?.icon ?? '🐘')
  const [preset, setPreset] = useState('')
  const [description, setDescription] = useState(connection?.description ?? '')

  // Postgres fields
  const [pgHost, setPgHost] = useState(connection?.config?.host ?? 'localhost')
  const [pgPort, setPgPort] = useState(connection?.config?.port ?? '5432')
  const [pgDatabase, setPgDatabase] = useState(connection?.config?.database ?? 'postgres')
  const [pgUser, setPgUser] = useState(connection?.config?.user ?? 'postgres')
  const [pgPassword, setPgPassword] = useState(plainCredential(connection?.config?.password))
  const [pgSsl, setPgSsl] = useState(connection?.config?.ssl ?? 'prefer')

  // MySQL fields
  const [myHost, setMyHost] = useState(connection?.config?.host ?? 'localhost')
  const [myPort, setMyPort] = useState(connection?.config?.port ?? '3306')
  const [myDatabase, setMyDatabase] = useState(connection?.config?.database ?? '')
  const [myUser, setMyUser] = useState(connection?.config?.user ?? 'root')
  const [myPassword, setMyPassword] = useState(plainCredential(connection?.config?.password))

  // MongoDB fields
  const [mgHost, setMgHost] = useState(connection?.config?.host ?? 'localhost')
  const [mgPort, setMgPort] = useState(connection?.config?.port ?? '27017')
  const [mgDatabase, setMgDatabase] = useState(connection?.config?.database ?? '')
  const [mgUser, setMgUser] = useState(connection?.config?.user ?? '')
  const [mgPassword, setMgPassword] = useState(plainCredential(connection?.config?.password))
  const [mgAuthSource, setMgAuthSource] = useState(connection?.config?.auth_source ?? 'admin')

  // Redis fields
  const [rdHost, setRdHost] = useState(connection?.config?.host ?? 'localhost')
  const [rdPort, setRdPort] = useState(connection?.config?.port ?? '6379')
  const [rdPassword, setRdPassword] = useState(plainCredential(connection?.config?.password))
  const [rdDb, setRdDb] = useState(connection?.config?.db ?? '0')

  // Snowflake fields
  const [snowAccount, setSnowAccount] = useState(connection?.config?.account ?? 'xy12345.us-east-1')
  const [snowWarehouse, setSnowWarehouse] = useState(connection?.config?.warehouse ?? 'COMPUTE_WH')
  const [snowDatabase, setSnowDatabase] = useState(connection?.config?.database ?? 'ANALYTICS_DB')
  const [snowSchema, setSnowSchema] = useState(connection?.config?.schema ?? 'PUBLIC')
  const [snowUser, setSnowUser] = useState(connection?.config?.user ?? 'admin')
  const [snowPassword, setSnowPassword] = useState(plainCredential(connection?.config?.password))
  const [snowRole, setSnowRole] = useState(connection?.config?.role ?? 'ACCOUNTADMIN')

  // AWS S3 fields
  const [s3Region, setS3Region] = useState(connection?.config?.region ?? 'us-east-1')
  const [s3Bucket, setS3Bucket] = useState(connection?.config?.bucket ?? 'company-knowledge-base')
  const [s3AccessKey, setS3AccessKey] = useState(connection?.config?.access_key_id ?? '')
  const [s3SecretKey, setS3SecretKey] = useState(plainCredential(connection?.config?.secret_access_key))

  // SQLite fields
  const [sqlitePath, setSqlitePath] = useState(connection?.config?.path ?? './data/company.db')

  // Custom API fields
  const [apiBaseUrl, setApiBaseUrl] = useState(connection?.config?.base_url ?? 'https://api.example.com')
  const [apiHeaders, setApiHeaders] = useState(
    connection?.config?.headers ? JSON.stringify(connection.config.headers, null, 2) : '{\n  "Authorization": "Bearer token"\n}'
  )

  // Testing / saving state
  const [isTesting, setIsTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  const handleProviderClick = (p: typeof PROVIDERS[number]) => {
    setType(p.type)
    setPreset('')
    setTestResult(null)
    setIcon(p.icon)
    if (!isEdit) setName(p.defaultName)
  }

  const applyPreset = (presetLabel: string) => {
    const list = PRESETS[type] ?? []
    const p = list.find(x => x.label === presetLabel)
    if (!p) return
    setPreset(presetLabel)
    if (type === 'postgres') {
      if (p.patch.host) setPgHost(p.patch.host)
      if (p.patch.port) setPgPort(p.patch.port)
      if (p.patch.ssl)  setPgSsl(p.patch.ssl)
      if (!isEdit) setName(`${p.label} Postgres`)
    } else if (type === 'mysql') {
      if (p.patch.host) setMyHost(p.patch.host)
      if (p.patch.port) setMyPort(p.patch.port)
      if (!isEdit) setName(p.label)
    } else if (type === 'mongodb') {
      if (p.patch.host) setMgHost(p.patch.host)
      if (p.patch.port) setMgPort(p.patch.port)
      if (!isEdit) setName(p.label)
    } else if (type === 'redis') {
      if (p.patch.host) setRdHost(p.patch.host)
      if (p.patch.port) setRdPort(p.patch.port)
      if (!isEdit) setName(p.label)
    }
  }

  const buildConfig = (): Record<string, any> => {
    if (type === 'postgres')   return { host: pgHost, port: pgPort, database: pgDatabase, user: pgUser, password: pgPassword, ssl: pgSsl }
    if (type === 'mysql')      return { host: myHost, port: myPort, database: myDatabase, user: myUser, password: myPassword }
    if (type === 'mongodb')    return { host: mgHost, port: mgPort, database: mgDatabase, user: mgUser, password: mgPassword, auth_source: mgAuthSource }
    if (type === 'redis')      return { host: rdHost, port: rdPort, password: rdPassword, db: rdDb }
    if (type === 'snowflake')  return { account: snowAccount, warehouse: snowWarehouse, database: snowDatabase, schema: snowSchema, user: snowUser, password: snowPassword, role: snowRole }
    if (type === 'aws_s3')     return { region: s3Region, bucket: s3Bucket, access_key_id: s3AccessKey, secret_access_key: s3SecretKey }
    if (type === 'sqlite')     return { path: sqlitePath }
    let parsedHeaders = {}
    try { parsedHeaders = JSON.parse(apiHeaders || '{}') } catch {}
    return { base_url: apiBaseUrl, headers: parsedHeaders }
  }

  const savedCredentialHint = isEdit ? 'Saved (encrypted) — leave blank to keep' : '••••••••'

  const handleTest = async () => {
    setIsTesting(true)
    setTestResult(null)
    setErrorMsg('')
    try {
      const res = await fetch(`${API_BASE}/api/connections/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, config: buildConfig(), connection_id: connection?.id }),
      })
      const data = await res.json()
      setTestResult({ success: data.success, message: data.message || (data.success ? 'Connected successfully!' : 'Connection failed') })
    } catch (err: any) {
      setTestResult({ success: false, message: `Network error: ${err.message}` })
    } finally {
      setIsTesting(false)
    }
  }

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setErrorMsg('Connection name is required.'); return }
    setIsSaving(true)
    setErrorMsg('')
    const payload = { name: name.trim(), type, icon: icon.trim() || '🔗', description: description.trim(), config: buildConfig() }
    try {
      let res: Response
      if (isEdit && connection) {
        res = await fetch(`${API_BASE}/api/connections/${connection.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      } else {
        res = await fetch(`${API_BASE}/api/connections`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
      }
      if (!res.ok) { const err = await res.json(); throw new Error(err.detail || 'Failed to save connection') }
      const saved: ConnectionRecord = await res.json()
      onSaved(saved)
      onClose()
    } catch (err: any) {
      setErrorMsg(err.message || 'Error saving connection')
    } finally {
      setIsSaving(false)
    }
  }

  const currentProvider = PROVIDERS.find(p => p.type === type)!
  const presetList = PRESETS[type] ?? []

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="conn-modal-shell">

        {/* ── Header ── */}
        <div className="conn-modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <ConnectionIcon type={currentProvider.type} size={16} />
            <div>
              <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: '#0f172a' }}>
                {isEdit ? `Edit: ${connection!.name}` : '+ Add Service Connection'}
              </h3>
              <p style={{ margin: 0, fontSize: 11, color: '#64748b', marginTop: 1 }}>
                {isEdit ? `${currentProvider.label} data source` : 'Connect a data source or service to your pipelines'}
              </p>
            </div>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose}>✕</button>
        </div>

        {/* ── Two-column body ── */}
        <div className="conn-modal-body">

          {/* LEFT — provider nav */}
          <nav className="conn-provider-nav">
            <p className="conn-nav-label">Provider</p>
            {PROVIDERS.map(p => (
              <button
                key={p.type}
                type="button"
                className={`conn-nav-item ${type === p.type ? 'active' : ''}`}
                onClick={() => handleProviderClick(p)}
              >
                <ConnectionIcon type={p.type} />
                <span className="conn-nav-name">{p.label}</span>
                {p.tag && <span className="conn-nav-tag">{p.tag}</span>}
              </button>
            ))}
          </nav>

          {/* RIGHT — config form */}
          <form className="conn-config-panel" onSubmit={handleSave}>
            <div className="conn-config-scroll">

              {errorMsg && <div className="ct-save-error" style={{ marginBottom: 10 }}>{errorMsg}</div>}

              {/* Identity row */}
              <div className="conn-section-label">Identity</div>
              <div className="form-row" style={{ gap: 10, marginBottom: 10 }}>
                <div className="form-group flex-1">
                  <label className="field-label">Connection Name *</label>
                  <input type="text" className="field-input" placeholder="e.g. Analytics DB, Production S3..." value={name} onChange={(e) => setName(e.target.value)} required />
                </div>
              </div>
              <div className="form-group" style={{ marginBottom: 14 }}>
                <label className="field-label">Description (optional)</label>
                <input type="text" className="field-input" placeholder="Where is this deployed? (e.g. AWS us-east-1, Supabase, Neon)" value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>

              {/* Quick preset */}
              {presetList.length > 0 && (
                <div className="form-group" style={{ marginBottom: 14 }}>
                  <label className="field-label">Quick Preset</label>
                  <div className="conn-preset-chips">
                    {presetList.map(p => (
                      <button key={p.label} type="button"
                        className={`conn-preset-chip ${preset === p.label ? 'active' : ''}`}
                        onClick={() => applyPreset(p.label)}>
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* ── PostgreSQL ── */}
              {type === 'postgres' && (
                <>
                  <div className="conn-section-label">Connection</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Host *</label>
                      <input type="text" className="field-input font-mono" placeholder="localhost" value={pgHost} onChange={(e) => setPgHost(e.target.value)} required />
                    </div>
                    <div className="form-group" style={{ width: 86 }}>
                      <label className="field-label">Port</label>
                      <input type="text" className="field-input font-mono" placeholder="5432" value={pgPort} onChange={(e) => setPgPort(e.target.value)} />
                    </div>
                  </div>
                  <div className="conn-section-label" style={{ marginTop: 12 }}>Credentials</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Database *</label>
                      <input type="text" className="field-input font-mono" placeholder="postgres" value={pgDatabase} onChange={(e) => setPgDatabase(e.target.value)} required />
                    </div>
                    <div className="form-group flex-1">
                      <label className="field-label">Username *</label>
                      <input type="text" className="field-input font-mono" placeholder="postgres" value={pgUser} onChange={(e) => setPgUser(e.target.value)} required />
                    </div>
                  </div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Password</label>
                      <input type="password" className="field-input font-mono" placeholder={savedCredentialHint} value={pgPassword} onChange={(e) => setPgPassword(e.target.value)} />
                    </div>
                    <div className="form-group" style={{ width: 130 }}>
                      <label className="field-label">SSL Mode</label>
                      <select className="field-select" value={pgSsl} onChange={(e) => setPgSsl(e.target.value)}>
                        <option value="disable">disable</option>
                        <option value="prefer">prefer</option>
                        <option value="require">require</option>
                      </select>
                    </div>
                  </div>
                </>
              )}

              {/* ── MySQL ── */}
              {type === 'mysql' && (
                <>
                  <div className="conn-section-label">Connection</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Host *</label>
                      <input type="text" className="field-input font-mono" placeholder="localhost" value={myHost} onChange={(e) => setMyHost(e.target.value)} required />
                    </div>
                    <div className="form-group" style={{ width: 86 }}>
                      <label className="field-label">Port</label>
                      <input type="text" className="field-input font-mono" placeholder="3306" value={myPort} onChange={(e) => setMyPort(e.target.value)} />
                    </div>
                  </div>
                  <div className="conn-section-label" style={{ marginTop: 12 }}>Credentials</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Database</label>
                      <input type="text" className="field-input font-mono" placeholder="mydb" value={myDatabase} onChange={(e) => setMyDatabase(e.target.value)} />
                    </div>
                    <div className="form-group flex-1">
                      <label className="field-label">Username *</label>
                      <input type="text" className="field-input font-mono" placeholder="root" value={myUser} onChange={(e) => setMyUser(e.target.value)} required />
                    </div>
                  </div>
                  <div className="form-group">
                    <label className="field-label">Password</label>
                    <input type="password" className="field-input font-mono" placeholder={savedCredentialHint} value={myPassword} onChange={(e) => setMyPassword(e.target.value)} />
                  </div>
                </>
              )}

              {/* ── MongoDB ── */}
              {type === 'mongodb' && (
                <>
                  <div className="conn-section-label">Connection</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Host *</label>
                      <input type="text" className="field-input font-mono" placeholder="localhost or cluster0.xxxxx.mongodb.net" value={mgHost} onChange={(e) => setMgHost(e.target.value)} required />
                    </div>
                    <div className="form-group" style={{ width: 86 }}>
                      <label className="field-label">Port</label>
                      <input type="text" className="field-input font-mono" placeholder="27017" value={mgPort} onChange={(e) => setMgPort(e.target.value)} />
                    </div>
                  </div>
                  <div className="conn-section-label" style={{ marginTop: 12 }}>Credentials</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Database</label>
                      <input type="text" className="field-input font-mono" placeholder="my_database" value={mgDatabase} onChange={(e) => setMgDatabase(e.target.value)} />
                    </div>
                    <div className="form-group" style={{ width: 110 }}>
                      <label className="field-label">Auth Source</label>
                      <input type="text" className="field-input font-mono" placeholder="admin" value={mgAuthSource} onChange={(e) => setMgAuthSource(e.target.value)} />
                    </div>
                  </div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Username</label>
                      <input type="text" className="field-input font-mono" placeholder="db_user" value={mgUser} onChange={(e) => setMgUser(e.target.value)} />
                    </div>
                    <div className="form-group flex-1">
                      <label className="field-label">Password</label>
                      <input type="password" className="field-input font-mono" placeholder={savedCredentialHint} value={mgPassword} onChange={(e) => setMgPassword(e.target.value)} />
                    </div>
                  </div>
                </>
              )}

              {/* ── Redis ── */}
              {type === 'redis' && (
                <>
                  <div className="conn-section-label">Connection</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Host *</label>
                      <input type="text" className="field-input font-mono" placeholder="localhost" value={rdHost} onChange={(e) => setRdHost(e.target.value)} required />
                    </div>
                    <div className="form-group" style={{ width: 86 }}>
                      <label className="field-label">Port</label>
                      <input type="text" className="field-input font-mono" placeholder="6379" value={rdPort} onChange={(e) => setRdPort(e.target.value)} />
                    </div>
                    <div className="form-group" style={{ width: 68 }}>
                      <label className="field-label">DB Index</label>
                      <input type="text" className="field-input font-mono" placeholder="0" value={rdDb} onChange={(e) => setRdDb(e.target.value)} />
                    </div>
                  </div>
                  <div className="conn-section-label" style={{ marginTop: 12 }}>Credentials</div>
                  <div className="form-group">
                    <label className="field-label">Password (optional)</label>
                    <input type="password" className="field-input font-mono" placeholder={savedCredentialHint} value={rdPassword} onChange={(e) => setRdPassword(e.target.value)} />
                  </div>
                </>
              )}

              {/* ── Snowflake ── */}
              {type === 'snowflake' && (
                <>
                  <div className="conn-section-label">Account</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Account Identifier *</label>
                      <input type="text" className="field-input font-mono" placeholder="xy12345.us-east-1" value={snowAccount} onChange={(e) => setSnowAccount(e.target.value)} required />
                    </div>
                    <div className="form-group flex-1">
                      <label className="field-label">Warehouse</label>
                      <input type="text" className="field-input font-mono" placeholder="COMPUTE_WH" value={snowWarehouse} onChange={(e) => setSnowWarehouse(e.target.value)} />
                    </div>
                  </div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Database</label>
                      <input type="text" className="field-input font-mono" placeholder="ANALYTICS_DB" value={snowDatabase} onChange={(e) => setSnowDatabase(e.target.value)} />
                    </div>
                    <div className="form-group flex-1">
                      <label className="field-label">Schema</label>
                      <input type="text" className="field-input font-mono" placeholder="PUBLIC" value={snowSchema} onChange={(e) => setSnowSchema(e.target.value)} />
                    </div>
                  </div>
                  <div className="conn-section-label" style={{ marginTop: 12 }}>Credentials</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Username *</label>
                      <input type="text" className="field-input font-mono" placeholder="admin_user" value={snowUser} onChange={(e) => setSnowUser(e.target.value)} required />
                    </div>
                    <div className="form-group flex-1">
                      <label className="field-label">Password</label>
                      <input type="password" className="field-input font-mono" placeholder={savedCredentialHint} value={snowPassword} onChange={(e) => setSnowPassword(e.target.value)} />
                    </div>
                    <div className="form-group" style={{ width: 130 }}>
                      <label className="field-label">Role</label>
                      <input type="text" className="field-input font-mono" placeholder="ACCOUNTADMIN" value={snowRole} onChange={(e) => setSnowRole(e.target.value)} />
                    </div>
                  </div>
                </>
              )}

              {/* ── AWS S3 ── */}
              {type === 'aws_s3' && (
                <>
                  <div className="conn-section-label">Bucket</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">AWS Region *</label>
                      <input type="text" className="field-input font-mono" placeholder="us-east-1" value={s3Region} onChange={(e) => setS3Region(e.target.value)} required />
                    </div>
                    <div className="form-group flex-1">
                      <label className="field-label">Default Bucket</label>
                      <input type="text" className="field-input font-mono" placeholder="my-rag-documents" value={s3Bucket} onChange={(e) => setS3Bucket(e.target.value)} />
                    </div>
                  </div>
                  <div className="conn-section-label" style={{ marginTop: 12 }}>IAM Credentials</div>
                  <div className="form-row" style={{ gap: 10 }}>
                    <div className="form-group flex-1">
                      <label className="field-label">Access Key ID *</label>
                      <input type="text" className="field-input font-mono" placeholder="AKIAIOSFODNN7EXAMPLE" value={s3AccessKey} onChange={(e) => setS3AccessKey(e.target.value)} required />
                    </div>
                    <div className="form-group flex-1">
                      <label className="field-label">Secret Access Key *</label>
                      <input type="password" className="field-input font-mono" placeholder={savedCredentialHint} value={s3SecretKey} onChange={(e) => setS3SecretKey(e.target.value)} required={!isEdit} />
                    </div>
                  </div>
                </>
              )}

              {/* ── SQLite ── */}
              {type === 'sqlite' && (
                <>
                  <div className="conn-section-label">File</div>
                  <div className="form-group">
                    <label className="field-label">Database File Path *</label>
                    <input type="text" className="field-input font-mono" placeholder="./data/app.db or :memory:" value={sqlitePath} onChange={(e) => setSqlitePath(e.target.value)} required />
                  </div>
                </>
              )}

              {/* ── Custom REST ── */}
              {type === 'custom_api' && (
                <>
                  <div className="conn-section-label">Endpoint</div>
                  <div className="form-group">
                    <label className="field-label">Base API URL *</label>
                    <input type="url" className="field-input font-mono" placeholder="https://api.example.com" value={apiBaseUrl} onChange={(e) => setApiBaseUrl(e.target.value)} required />
                  </div>
                  <div className="conn-section-label" style={{ marginTop: 12 }}>Headers (JSON)</div>
                  <div className="form-group">
                    <textarea rows={4} className="field-textarea font-mono" style={{ fontSize: 11 }} value={apiHeaders} onChange={(e) => setApiHeaders(e.target.value)} />
                  </div>
                </>
              )}

              {/* ── Test section ── */}
              <div className="mcp-test-section" style={{ marginTop: 14 }}>
                <div className="mcp-test-header">
                  <button type="button" className="mcp-test-btn" onClick={handleTest} disabled={isTesting}>
                    {isTesting ? '⚡ Testing...' : '🔍 Test Connection'}
                  </button>
                  <span className="field-hint">Performs live network &amp; auth check</span>
                </div>
                {testResult && (
                  <div className={`mcp-test-banner ${testResult.success ? 'success' : 'error'}`} style={{ marginTop: 8 }}>
                    {testResult.message}
                  </div>
                )}
              </div>

            </div>{/* /conn-config-scroll */}

            {/* Footer inside form so submit works */}
            <div className="conn-modal-footer">
              <button type="button" className="cancel-btn" onClick={onClose} disabled={isSaving}>Cancel</button>
              <button type="submit" className="save-btn" disabled={isSaving}>
                {isSaving ? 'Saving...' : isEdit ? 'Update Connection' : 'Save Connection'}
              </button>
            </div>

          </form>
        </div>{/* /conn-modal-body */}
      </div>
    </div>
  )
}
