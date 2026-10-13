import { useCallback, useEffect, useState } from 'react'

/* ============================================================
 * 可视化后端管理台（/admin）
 * 自包含：独立登录（admin 凭据），不依赖主站 AppShell。
 * 数据源：/api/health、/api/admin/* 系列端点。
 * ============================================================ */

const ADMIN_TOKEN_KEY = 'admin_token'
const ADMIN_EMAIL_KEY = 'admin_email'

type Tab = 'overview' | 'tasks' | 'users' | 'subscription' | 'agnes'

interface HealthInfo {
  ok: boolean
  app: string
  models: { llm?: string; image?: string; video?: string; audio?: string }
  quality?: Record<string, string>
  task_runtime?: Record<string, unknown>
}

interface Dashboard {
  user_count: number
  usage_calls_today: number
  usage_calls_month: number
  usage_calls_total: number
  project_status_counts: Record<string, number>
  drama_project_count: number
  top_users?: Array<{ user_id: number; email: string | null; calls: number }>
  daily?: Array<{ date: string; calls: number; charge_fen: number }>
}

interface TaskStats {
  pending_count: number
  active_count: number
  running_count: number
  succeeded_count: number
  failed_count: number
  cancelled_count: number
  scheduler: string
  poller: string
  runtime_healthy: boolean
  max_concurrency: number
}

interface TaskItem {
  id: number
  domain: string
  task_type: string
  status: string
  user_email?: string | null
  created_at?: string | null
  updated_at?: string | null
  error_message?: string | null
}

interface UserItem {
  id: number
  email: string
  nickname: string
  plan: string
  role: string
  balance_fen: number
  quota_left: number
  created_at?: string | null
}

interface AgnesStatus {
  enabled: boolean
  base_url: string
  text_model: string
  image_model: string
  video_model: string
  key_count: number
  keys: string[]
  proxy_pool: {
    url: string
    ok: boolean
    healthy: number
    nodes: number
    exit_ips: number
    unreachable?: boolean
  } | null
  pool_client?: { configured_keys: number; bad_keys: number[] } | null
}

interface AgnesTestResult {
  ok: boolean
  message: string
  latency_ms: number
  key: string
}

function readToken(): string | null {
  return localStorage.getItem(ADMIN_TOKEN_KEY)
}

// 本地开发走 127.0.0.1:8000（vite dev 无 /api 反代）；生产走同源（nginx 反代 /api→8000）
const ADMIN_API_BASE = import.meta.env.DEV ? 'http://127.0.0.1:8000' : ''

function call<T>(token: string, path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${token}`,
  }
  return fetch(`${ADMIN_API_BASE}${path}`, { ...init, headers }).then(async (res) => {
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `HTTP ${res.status}`)
    }
    return (await res.json()) as T
  })
}

const FEN_TO_YUAN = (fen: number) => '¥' + (fen / 100).toFixed(2)

function statusBadge(s: string) {
  const cls =
    s === 'succeeded' || s === 'done' || s === 'admin'
      ? 's-ok'
      : s === 'failed'
        ? 's-bad'
        : s === 'running' || s === 'active' || s === 'leased'
          ? 's-run'
          : 's-idle'
  return <span className={`badge ${cls}`}>{s}</span>
}

export default function AdminPage() {
  const [token, setToken] = useState<string | null>(readToken())
  const [tab, setTab] = useState<Tab>('overview')
  const [email, setEmail] = useState(() => localStorage.getItem(ADMIN_EMAIL_KEY) || 'admin@local.dev')
  const [password, setPassword] = useState('')
  const [authErr, setAuthErr] = useState('')
  const [authBusy, setAuthBusy] = useState(false)

  useEffect(() => {
    if (!token) return
    document.title = 'Printfilm 管理台'
  }, [token])

  const doLogin = async () => {
    setAuthBusy(true)
    setAuthErr('')
    try {
      const res = await fetch(`${ADMIN_API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (!res.ok) throw new Error(`登录失败（${res.status}）`)
      const data = await res.json()
      localStorage.setItem(ADMIN_TOKEN_KEY, data.access_token)
      localStorage.setItem(ADMIN_EMAIL_KEY, email)
      setToken(data.access_token)
    } catch (e) {
      setAuthErr(e instanceof Error ? e.message : String(e))
    } finally {
      setAuthBusy(false)
    }
  }

  const doLogout = () => {
    localStorage.removeItem(ADMIN_TOKEN_KEY)
    setToken(null)
  }

  if (!token) {
    return (
      <div className="adm-root adm-login">
        <div className="adm-login-card">
          <div className="adm-logo">◈</div>
          <h1>Printfilm 管理台</h1>
          <p>输入管理员账号登录（需 role=admin）</p>
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@local.dev"
            className="adm-input"
          />
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && doLogin()}
            placeholder="密码"
            className="adm-input"
          />
          {authErr && <div className="adm-err">{authErr}</div>}
          <button className="adm-btn adm-btn-primary" onClick={doLogin} disabled={authBusy}>
            {authBusy ? '登录中…' : '登录管理台'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="adm-root">
      <header className="adm-topbar">
        <div className="adm-topbar-left">
          <span className="adm-logo-sm">◈</span>
          <strong>Printfilm 管理台</strong>
        </div>
        <nav className="adm-tabs">
          <button className={tab === 'overview' ? 'on' : ''} onClick={() => setTab('overview')}>
            概览
          </button>
          <button className={tab === 'tasks' ? 'on' : ''} onClick={() => setTab('tasks')}>
            任务
          </button>
          <button className={tab === 'users' ? 'on' : ''} onClick={() => setTab('users')}>
            用户
          </button>
          <button className={tab === 'subscription' ? 'on' : ''} onClick={() => setTab('subscription')}>
            订阅管理
          </button>
          <button className={tab === 'agnes' ? 'on' : ''} onClick={() => setTab('agnes')}>
            Agnes Key 池
          </button>
        </nav>
        <button className="adm-btn adm-logout" onClick={doLogout}>
          退出
        </button>
      </header>

      <main className="adm-main">
        {tab === 'overview' && <OverviewTab token={token} />}
        {tab === 'tasks' && <TasksTab token={token} />}
        {tab === 'users' && <UsersTab token={token} />}
        {tab === 'subscription' && <SubscriptionTab token={token} />}
        {tab === 'agnes' && <AgnesTab token={token} />}
      </main>
    </div>
  )
}

/* ---------------- 概览 ---------------- */
function OverviewTab({ token }: { token: string }) {
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [dash, setDash] = useState<Dashboard | null>(null)
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    try {
      const [h, d] = await Promise.all([
        call<HealthInfo>(token, '/api/health'),
        call<Dashboard>(token, '/api/admin/stats?days=30'),
      ])
      setHealth(h)
      setDash(d)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }, [token])

  useEffect(() => {
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [load])

  const stat = (label: string, value: React.ReactNode, sub?: string) => (
    <div className="adm-card stat">
      <div className="stat-num">{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  )

  return (
    <>
      {err && <div className="adm-err">概览加载失败：{err}</div>}
      <div className="adm-grid stats">
        {dash
          ? [
              stat('用户数', dash.user_count),
              stat('项目状态', Object.entries(dash.project_status_counts).length ? '' : '—',
                Object.entries(dash.project_status_counts)
                  .map(([k, v]) => `${k} ${v}`)
                  .join(' · ') || '暂无项目'),
              stat('漫剧项目', dash.drama_project_count),
              stat('今日调用', dash.usage_calls_today, `本月 ${dash.usage_calls_month} · 累计 ${dash.usage_calls_total}`),
            ]
          : [stat('…', '加载中')]
        }
      </div>

      <div className="adm-grid cols2">
        <div className="adm-card">
          <h3>服务健康</h3>
          {health ? (
            <ul className="adm-kv">
              <li>
                <span>运行状态</span>
                <b className={health.ok ? 'ok' : 'bad'}>{health.ok ? 'healthy' : 'unhealthy'}</b>
              </li>
              <li>
                <span>任务运行时</span>
                <b>{(health.task_runtime?.scheduler as string) || '—'}</b>
              </li>
              <li>
                <span>文本模型</span>
                <b>{health.models?.llm || '—'}</b>
              </li>
              <li>
                <span>图像模型</span>
                <b>{health.models?.image || '—'}</b>
              </li>
              <li>
                <span>视频模型</span>
                <b>{health.models?.video || '—'}</b>
              </li>
              <li>
                <span>应用</span>
                <b>{health.app}</b>
              </li>
            </ul>
          ) : (
            <div className="adm-muted">加载中…</div>
          )}
        </div>
        <div className="adm-card">
          <h3>用户排行（按调用，30 天）</h3>
          {dash?.top_users?.length ? (
            <ol className="adm-rank">
              {dash.top_users.slice(0, 6).map((u, i) => (
                <li key={u.user_id}>
                  <span className="rank-i">{i + 1}</span>
                  <span className="rank-mail">{u.email || `#${u.user_id}`}</span>
                  <b>{u.calls}</b>
                </li>
              ))}
            </ol>
          ) : (
            <div className="adm-muted">暂无数据</div>
          )}
        </div>
      </div>
    </>
  )
}

/* ---------------- 任务 ---------------- */
function TasksTab({ token }: { token: string }) {
  const [stats, setStats] = useState<TaskStats | null>(null)
  const [items, setItems] = useState<TaskItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState('')
  const [busyId, setBusyId] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      const [s, l] = await Promise.all([
        call<TaskStats>(token, '/api/admin/tasks/stats'),
        call<{ items: TaskItem[]; meta: { total: number } }>(
          token,
          `/api/admin/tasks?page=${page}&page_size=20${statusFilter ? `&status=${statusFilter}` : ''}`,
        ),
      ])
      setStats(s)
      setItems(l.items)
      setTotal(l.meta.total)
    } catch {
      /* keep prior */
    }
  }, [token, page, statusFilter])

  useEffect(() => {
    load()
  }, [load])

  const cancelTask = async (id: number) => {
    setBusyId(id)
    try {
      await call(token, `/api/admin/tasks/${id}/cancel`, { method: 'POST' })
      load()
    } catch {
      /* ignore */
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <div className="adm-grid stats">
        {stats
          ? [
              <div className="adm-card stat"><div className="stat-num">{stats.running_count}</div><div className="stat-label">运行中</div></div>,
              <div className="adm-card stat"><div className="stat-num">{stats.pending_count}</div><div className="stat-label">排队中</div></div>,
              <div className="adm-card stat"><div className="stat-num ok-text">{stats.succeeded_count}</div><div className="stat-label">成功</div></div>,
              <div className="adm-card stat"><div className="stat-num bad-text">{stats.failed_count}</div><div className="stat-label">失败</div></div>,
              <div className="adm-card stat">
                <div className="stat-num">{stats.runtime_healthy ? '✓' : '✗'}</div>
                <div className="stat-label">运行时</div>
                <div className="stat-sub">{stats.scheduler} · 并发 {stats.max_concurrency}</div>
              </div>,
            ]
          : [
              <div className="adm-card stat"><div className="stat-num">…</div><div className="stat-label">加载中</div></div>,
            ]}
      </div>

      <div className="adm-card table-card">
        <div className="table-head">
          <h3>任务列表</h3>
          <div className="filters">
            <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}>
              <option value="">全部状态</option>
              <option value="pending">pending</option>
              <option value="running">running</option>
              <option value="succeeded">succeeded</option>
              <option value="failed">failed</option>
            </select>
          </div>
        </div>
        <table className="adm-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>领域</th>
              <th>类型</th>
              <th>状态</th>
              <th>提交人</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((t) => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>{t.domain}</td>
                <td>{t.task_type}</td>
                <td>{statusBadge(t.status)}</td>
                <td>{t.user_email || '—'}</td>
                <td>{t.updated_at ? new Date(t.updated_at).toLocaleString('zh-CN') : '—'}</td>
                <td>
                  {['pending', 'running', 'leased'].includes(t.status) && (
                    <button
                      className="adm-btn adm-btn-sm"
                      onClick={() => cancelTask(t.id)}
                      disabled={busyId === t.id}
                    >
                      {busyId === t.id ? '取消中…' : '取消'}
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={7} className="adm-muted" style={{ textAlign: 'center', padding: '2rem' }}>暂无任务</td></tr>
            )}
          </tbody>
        </table>
        <div className="pager">
          <button className="adm-btn adm-btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</button>
          <span>第 {page} 页 · 共 {total} 条</span>
          <button className="adm-btn adm-btn-sm" disabled={items.length < 20} onClick={() => setPage((p) => p + 1)}>下一页</button>
        </div>
      </div>
    </>
  )
}

/* ---------------- 用户 ---------------- */
function UsersTab({ token }: { token: string }) {
  const [items, setItems] = useState<UserItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [q, setQ] = useState('')

  const load = useCallback(async () => {
    try {
      const l = await call<{ items: UserItem[]; meta: { total: number } }>(
        token,
        `/api/admin/users?page=${page}&page_size=20${q ? `&q=${encodeURIComponent(q)}` : ''}`,
      )
      setItems(l.items)
      setTotal(l.meta.total)
    } catch {
      /* keep */
    }
  }, [token, page, q])

  useEffect(() => {
    load()
  }, [load])

  const patchRole = async (u: UserItem) => {
    const next = u.role === 'admin' ? 'user' : 'admin'
    try {
      await call(token, `/api/admin/users/${u.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ role: next }),
      })
      load()
    } catch (e) {
      alert(`修改失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }

  return (
    <div className="adm-card table-card">
      <div className="table-head">
        <h3>用户（{total}）</h3>
        <input className="adm-input sm" placeholder="搜索邮箱 / 昵称" value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} />
      </div>
      <table className="adm-table">
        <thead>
          <tr>
            <th>ID</th><th>邮箱</th><th>昵称</th><th>套餐</th><th>角色</th>
            <th>余额</th><th>额度</th><th>注册时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {items.map((u) => (
            <tr key={u.id}>
              <td>{u.id}</td>
              <td>{u.email}</td>
              <td>{u.nickname}</td>
              <td>{u.plan}</td>
              <td>{statusBadge(u.role === 'admin' ? 'admin' : 'user') as unknown as string}</td>
              <td>{FEN_TO_YUAN(u.balance_fen)}</td>
              <td>{u.quota_left}</td>
              <td>{u.created_at ? new Date(u.created_at).toLocaleDateString('zh-CN') : '—'}</td>
              <td>
                <button className="adm-btn adm-btn-sm" onClick={() => patchRole(u)}>
                  {u.role === 'admin' ? '降为普通用户' : '设为管理员'}
                </button>
              </td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={9} className="adm-muted" style={{ textAlign: 'center', padding: '2rem' }}>暂无用户</td></tr>}
        </tbody>
      </table>
      <div className="pager">
        <button className="adm-btn adm-btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>上一页</button>
        <span>第 {page} 页 · 共 {total} 条</span>
        <button className="adm-btn adm-btn-sm" disabled={items.length < 20} onClick={() => setPage((p) => p + 1)}>下一页</button>
      </div>
    </div>
  )
}

/* ---------------- 订阅管理 ---------------- */
interface SubSku {
  sku_id: string
  plan: string
  title: string
  amount_fen: number
  period_days: number
  perks: Record<string, unknown>
}

interface SubStatus {
  sku_id?: string
  plan?: string
  status?: string
  amount_fen?: number
  period_days?: number
  perks?: Record<string, unknown>
  expires_at?: string | null
  last_renewed_at?: string | null
  auto_renew?: boolean
}

function SubscriptionTab({ token }: { token: string }) {
  const [skus, setSkus] = useState<SubSku[]>([])
  const [uid, setUid] = useState('')
  const [sku, setSku] = useState('')
  const [autoRenew, setAutoRenew] = useState(false)
  const [info, setInfo] = useState<{ user: { id: number; email: string; nickname: string | null; plan: string; balance_fen: number }; subscription: SubStatus | null } | null>(null)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)

  const loadSkus = useCallback(async () => {
    try {
      const r = await call<{ skus: SubSku[] }>(token, '/api/admin/subscription/skus')
      setSkus(r.skus)
      if (r.skus.length && !sku) setSku(r.skus[0].sku_id)
    } catch (e) {
      setMsg(`加载 SKU 失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }, [token, sku])

  useEffect(() => {
    loadSkus()
  }, [loadSkus])

  const loadUser = async () => {
    const n = Number(uid.trim())
    if (!Number.isFinite(n) || n <= 0) {
      setMsg('请输入用户 ID')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      const r = await call<typeof info>(token, `/api/admin/subscription/users/${n}`)
      setInfo(r)
    } catch (e) {
      setInfo(null)
      setMsg(`查询失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const activate = async () => {
    const n = Number(uid.trim())
    if (!Number.isFinite(n) || n <= 0 || !sku) {
      setMsg('请选择用户 ID 与订阅档位')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      await call(token, '/api/admin/subscription/activate', {
        method: 'POST',
        body: JSON.stringify({ user_id: n, sku_id: sku, auto_renew: autoRenew }),
      })
      setMsg('已开通')
      await loadUser()
    } catch (e) {
      setMsg(`开通失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const cancel = async () => {
    const n = Number(uid.trim())
    if (!Number.isFinite(n) || n <= 0) return
    setBusy(true)
    setMsg('')
    try {
      const r = await call<{ cancelled: boolean }>(token, '/api/admin/subscription/cancel', {
        method: 'POST',
        body: JSON.stringify({ user_id: n }),
      })
      setMsg(r.cancelled ? '已取消自动续费（当期权益保留到到期）' : '该用户无活跃订阅')
      await loadUser()
    } catch (e) {
      setMsg(`取消失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const cur = skus.find((s) => s.sku_id === sku)

  return (
    <div className="adm-card">
      <div className="table-head">
        <h3>订阅管理（手动开通，无需支付）</h3>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        <input
          className="adm-input sm"
          placeholder="用户 ID"
          value={uid}
          onChange={(e) => setUid(e.target.value)}
          style={{ width: 160 }}
        />
        <button className="adm-btn adm-btn-sm" onClick={loadUser} disabled={busy}>
          查询
        </button>
      </div>

      <div style={{ marginBottom: 12 }}>
        <label style={{ marginRight: 8 }}>订阅档位：</label>
        <select className="adm-input sm" value={sku} onChange={(e) => setSku(e.target.value)} style={{ width: 240 }}>
          {skus.map((s) => (
            <option key={s.sku_id} value={s.sku_id}>
              {s.title}（¥{(s.amount_fen / 100).toFixed(0)} · {s.period_days} 天 · {s.plan}）
            </option>
          ))}
        </select>
        <label style={{ marginLeft: 16, whiteSpace: 'nowrap' }}>
          <input type="checkbox" checked={autoRenew} onChange={(e) => setAutoRenew(e.target.checked)} />
          到期自动续费（从用户余额扣费）
        </label>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
        <button className="adm-btn" onClick={activate} disabled={busy}>
          一键开通 / 延长
        </button>
        <button className="adm-btn adm-btn-sm" onClick={cancel} disabled={busy}>
          取消自动续费
        </button>
      </div>

      {cur && (
        <div className="adm-muted" style={{ marginBottom: 12 }}>
          当前档位权益：{JSON.stringify(cur.perks)}
        </div>
      )}

      {info && (
        <div className="adm-muted" style={{ marginBottom: 12, lineHeight: 1.8 }}>
          <div>
            用户 {info.user.id}：{info.user.email}（{info.user.nickname || '—'}）· 套餐 {info.user.plan} · 余额{' '}
            {FEN_TO_YUAN(info.user.balance_fen)}
          </div>
          {info.subscription ? (
            <div>
              订阅：{info.subscription.sku_id}（{info.subscription.plan}）· 状态 {info.subscription.status} · 到期{' '}
              {info.subscription.expires_at ? new Date(info.subscription.expires_at).toLocaleString('zh-CN') : '—'} · 自动续费{' '}
              {info.subscription.auto_renew ? '开' : '关'}
            </div>
          ) : (
            <div>无订阅记录</div>
          )}
        </div>
      )}

      {msg && <div className="adm-muted">{msg}</div>}
    </div>
  )
}

/* ---------------- Agnes Key 池 ---------------- */
function AgnesTab({ token }: { token: string }) {
  const [st, setSt] = useState<AgnesStatus | null>(null)
  const [test, setTest] = useState<AgnesTestResult | null>(null)
  const [importText, setImportText] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const load = useCallback(async () => {
    try {
      setSt(await call<AgnesStatus>(token, '/api/admin/agnes'))
    } catch (e) {
      setMsg(`加载失败：${e instanceof Error ? e.message : String(e)}`)
    }
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  const doTest = async () => {
    setBusy(true)
    setTest(null)
    try {
      const r = await call<AgnesTestResult>(token, '/api/admin/agnes/test', { method: 'POST' })
      setTest(r)
    } catch (e) {
      setTest({ ok: false, message: String(e), latency_ms: 0, key: '' })
    } finally {
      setBusy(false)
    }
  }

  const doImport = async () => {
    const keys = importText
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (keys.length === 0) {
      setMsg('请粘贴至少一个 key（每行或逗号分隔）')
      return
    }
    setBusy(true)
    setMsg('')
    try {
      await call(token, '/api/admin/agnes/keys', { method: 'POST', body: JSON.stringify({ keys }) })
      setImportText('')
      setMsg(`已导入 ${keys.length} 把 key，热更新生效`)
      await load()
    } catch (e) {
      setMsg(`导入失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  const pool = st?.proxy_pool
  return (
    <>
      <div className="adm-grid cols2">
        <div className="adm-card">
          <h3>Agnes 引擎配置</h3>
          {st ? (
            <ul className="adm-kv">
              <li><span>启用</span><b className={st.enabled ? 'ok' : 'bad'}>{st.enabled ? '是（走 Agnes 池）' : '否（走 TokenFree）'}</b></li>
              <li><span>端点</span><b>{st.base_url}</b></li>
              <li><span>文本 / 图像 / 视频</span><b>{st.text_model} · {st.image_model} · {st.video_model}</b></li>
              <li>
                <span>Key 池大小</span>
                <b>{st.key_count} 把</b>
              </li>
            </ul>
          ) : (
            <div className="adm-muted">加载中…</div>
          )}
        </div>

        <div className="adm-card">
          <h3>出口代理池（5010 动态 IP 池）</h3>
          {st?.proxy_pool ? (
            <ul className="adm-kv">
              <li><span>地址</span><b>{pool?.url}</b></li>
              <li><span>状态</span><b className={pool?.ok ? 'ok' : 'bad'}>{pool?.ok ? `健康（${pool.healthy}/${pool.nodes} 节点）` : pool?.unreachable ? '不可达' : '异常'}</b></li>
              <li><span>出口 IP</span><b>{pool?.exit_ips} 个</b></li>
            </ul>
          ) : (
            <div className="adm-muted">未启用代理池（直连）</div>
          )}
          <div className="adm-actions">
            <button className="adm-btn adm-btn-primary" onClick={doTest} disabled={busy}>
              {test ? '再次测试' : '测试一条 key'}
            </button>
            {test && (
              <span className={`adm-test ${test.ok ? 'ok' : 'bad'}`}>
                {test.ok ? `✓ ${test.latency_ms}ms · ${test.key}` : `✗ ${test.message}`}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="adm-card">
        <h3>Key 脱敏清单（{st?.key_count ?? 0} 把）</h3>
        {st && st.keys.length ? (
          <div className="adm-keylist">
            {st.keys.map((k, i) => (
              <code key={i}>{k}</code>
            ))}
          </div>
        ) : (
          <div className="adm-muted">池中无 key</div>
        )}
      </div>

      <div className="adm-card">
        <h3>一键导入 / 覆盖 Key 池</h3>
        <p className="adm-hint">粘贴新的 sk- key（每行或逗号分隔），保存后写入 .env 并热更新 agnes 客户端（无需重启后端）。</p>
        <textarea
          className="adm-textarea"
          rows={5}
          placeholder={'sk-xxx\nsk-yyy'}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
        />
        <div className="adm-actions">
          <button className="adm-btn adm-btn-primary" onClick={doImport} disabled={busy}>
            {busy ? '写入中…' : '导入并热更新'}
          </button>
          {msg && <span className="adm-msg">{msg}</span>}
        </div>
      </div>
    </>
  )
}
