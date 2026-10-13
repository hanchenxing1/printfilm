/**
 * 单机开源版：Agnes API Key 首次引导 & 设置页。
 *
 * 触发时机：
 *   - 应用启动后首次加载 → 调 /api/settings/health，若 agnes.configured === false
 *     则全屏引导用户粘贴 Agnes key，保存后进入主界面。
 *   - 主界面右上角「设置」齿轮 → 打开同一组件（弹窗形态）管理 key。
 */
import { useCallback, useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_BASE || ''

type AgnesHealth = {
  ok: boolean
  agnes: {
    configured: boolean
    key_count: number
    text_model?: string | null
    image_model?: string | null
    video_model?: string | null
    base_url?: string | null
  }
}

type AgnesKeyStatus = {
  configured: boolean
  count: number
  masked: string[]
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${body.slice(0, 200)}`)
  }
  return res.json()
}

export async function fetchAgnesHealth(): Promise<AgnesHealth | null> {
  try {
    return await api<AgnesHealth>('/api/settings/health')
  } catch {
    return null
  }
}

export async function fetchAgnesKeyStatus(): Promise<AgnesKeyStatus> {
  return api<AgnesKeyStatus>('/api/settings/agnes-keys')
}

export async function saveAgnesKey(key: string): Promise<AgnesKeyStatus> {
  return api<AgnesKeyStatus>('/api/settings/agnes-keys', {
    method: 'PUT',
    body: JSON.stringify({ keys: [key] }),
  })
}

export async function testAgnesKey(key?: string): Promise<{ ok: boolean; message: string }> {
  const qs = key ? `?key=${encodeURIComponent(key)}` : ''
  return api<{ ok: boolean; message: string }>(`/api/settings/agnes-test${qs}`)
}

export function AgnesKeyOnboarding({ onDone }: { onDone: () => void }) {
  const [key, setKey] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleTest = useCallback(async () => {
    if (!key.trim()) return
    setTesting(true)
    setError('')
    setTestResult(null)
    try {
      const r = await testAgnesKey(key.trim())
      setTestResult(r)
      if (r.ok) setError('')
    } catch (e) {
      setError(String(e))
    } finally {
      setTesting(false)
    }
  }, [key])

  const handleSave = useCallback(async () => {
    if (!key.trim() || saving) return
    setSaving(true)
    setError('')
    try {
      await saveAgnesKey(key.trim())
      onDone()
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }, [key, onDone, saving])

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        background: '#0d0f14',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif',
        color: '#e4e6eb',
      }}
    >
      <div
        style={{
          width: 'min(520px, 92vw)',
          background: '#16181f',
          border: '1px solid #2a2d38',
          borderRadius: 16,
          padding: '36px 32px',
          boxShadow: '0 24px 64px rgba(0,0,0,.55)',
        }}
      >
        {/* 品牌头 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 10,
              background: 'linear-gradient(135deg,#4f6ef7,#a78bfa)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 20,
              fontWeight: 800,
              color: '#fff',
            }}
          >
            P
          </div>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>PRINTFILM 单机版</div>
            <div style={{ fontSize: 12, color: '#8b9099' }}>
              需要 Agnes AI API Key 才能生成文字 / 图像 / 视频
            </div>
          </div>
        </div>

        {/* 说明 */}
        <p style={{ fontSize: 13, lineHeight: 1.7, color: '#a3a8b5', margin: '0 0 20px' }}>
          请输入你的 Agnes AI API Key（可在{' '}
          <a
            href="https://apihub.agnes-ai.com"
            target="_blank"
            rel="noreferrer"
            style={{ color: '#7c8cf8' }}
          >
            apihub.agnes-ai.com
          </a>{' '}
          获取）。Key 仅保存在本机，不会上传到任何服务器。
        </p>

        {/* 输入框 */}
        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 12, color: '#8b9099', marginBottom: 6, display: 'block' }}>
            Agnes API Key
          </label>
          <input
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="sk-xxx..."
            style={{
              width: '100%',
              boxSizing: 'border-box',
              background: '#1e2029',
              border: '1px solid #2e3140',
              borderRadius: 8,
              padding: '10px 12px',
              fontSize: 14,
              color: '#e4e6eb',
              outline: 'none',
            }}
            onKeyDown={(e) => e.key === 'Enter' && handleSave()}
          />
        </div>

        {/* 测试结果 */}
        {testResult && (
          <div
            style={{
              fontSize: 12,
              padding: '8px 12px',
              borderRadius: 8,
              marginBottom: 12,
              background: testResult.ok ? '#1a2a1f' : '#2a1a1f',
              border: `1px solid ${testResult.ok ? '#2d4a35' : '#4a2d35'}`,
              color: testResult.ok ? '#6fe8a0' : '#ff8a8a',
            }}
          >
            {testResult.message}
          </div>
        )}
        {error && (
          <div
            style={{
              fontSize: 12,
              padding: '8px 12px',
              borderRadius: 8,
              marginBottom: 12,
              background: '#2a1a1f',
              border: '1px solid #4a2d35',
              color: '#ff8a8a',
            }}
          >
            {error}
          </div>
        )}

        {/* 操作按钮 */}
        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={handleTest}
            disabled={!key.trim() || testing}
            style={{
              flex: 1,
              padding: '10px 0',
              borderRadius: 8,
              border: '1px solid #3a3d4d',
              background: '#1e2029',
              color: key.trim() ? '#c4c9d4' : '#555',
              fontSize: 13,
              cursor: testing ? 'wait' : key.trim() ? 'pointer' : 'not-allowed',
            }}
          >
            {testing ? '验证中…' : '验证 Key'}
          </button>
          <button
            onClick={handleSave}
            disabled={!key.trim() || saving}
            style={{
              flex: 1,
              padding: '10px 0',
              borderRadius: 8,
              border: 'none',
              background: key.trim() ? '#4f6ef7' : '#2a2d38',
              color: key.trim() ? '#fff' : '#666',
              fontSize: 13,
              fontWeight: 600,
              cursor: key.trim() && !saving ? 'pointer' : 'not-allowed',
            }}
          >
            {saving ? '保存中…' : '保存并进入'}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * 嵌入主 App 的 Agnes 状态浮标（右下角小徽标），
 * 若 agnes 未配置则点击弹出 onboarding 复用。
 */
export function AgnesStatusBadge({
  onOpenSettings,
}: {
  onOpenSettings: () => void
}) {
  const [status, setStatus] = useState<AgnesKeyStatus | null>(null)

  useEffect(() => {
    fetchAgnesKeyStatus().then(setStatus).catch(() => setStatus(null))
  }, [])

  if (!status || !status.configured) {
    return (
      <button
        onClick={onOpenSettings}
        style={{
          position: 'fixed',
          bottom: 16,
          right: 16,
          zIndex: 9000,
          background: '#4f6ef7',
          color: '#fff',
          border: 'none',
          borderRadius: 999,
          padding: '8px 16px',
          fontSize: 12,
          fontWeight: 600,
          cursor: 'pointer',
          boxShadow: '0 4px 16px rgba(79,110,247,.4)',
        }}
      >
        ⚙ 配置 Agnes Key
      </button>
    )
  }

  // 已配置：显示小绿点
  return (
    <button
      onClick={onOpenSettings}
      title={`Agnes 已配置（${status.count} 把 key）`}
      style={{
        position: 'fixed',
        bottom: 16,
        right: 16,
        zIndex: 9000,
        width: 28,
        height: 28,
        borderRadius: '50%',
        background: '#1a2a1f',
        border: '1px solid #2d4a35',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'pointer',
      }}
    >
      <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#4ade80' }} />
    </button>
  )
}
