/**
 * 双端在线更新提示浮层（旧壳 fallback 通道）。
 *
 * 双端壳（桌面 Electron / 移动 Capacitor）加载的都是 aidj.aiwyq.bond 站点本身，
 * 因此把「检测线上是否有新版本安装包」做成站点内组件，156 每次发布新版后
 * （管理端调 POST /api/admin/update/release 登记）已安装的 PC/手机用户下次打开 App
 * 会自动弹出更新提示，无需重打客户端安装包。
 *
 * 渠道分工（避免双弹）：
 *   - 新壳（UA 带 PRINTFILM-Desktop/x.x.x 或 PRINTFILM-Mobile/x.x marker）→ 原生代码负责
 *     （Electron main.js 弹原生 dialog / Android MainActivity 弹 AlertDialog），
 *     本组件检测到 marker 直接不弹，避免与原生渠道双重提示。
 *   - 旧壳（UA 无 marker，例如 1.0 版 APK 或旧桌面壳）→ 原生代码没有更新检测逻辑，
 *     由本浮层兜底弹提示。
 *
 * - 普通浏览器访问不弹（UA 非 Electron/Capacitor 直接返回 null）。
 * - 去重：用 localStorage 记录「已看过的最新版本号」，同一版本只弹一次。
 */
import { useEffect, useRef, useState } from 'react'

type Platform = 'desktop' | 'mobile'

type UpdateInfo = {
  has_release: boolean
  update_available: boolean
  force: boolean
  latest_version: string
  url: string
  notes: string
  published_at?: string | null
}

const SEEN_KEY = 'pf_update_seen_version'

function detectShell(): Platform | 'web' {
  const ua = navigator.userAgent || ''
  if (ua.includes('Electron') || ua.includes('PRINTFILM-Desktop')) return 'desktop'
  if (ua.includes('Capacitor') || ua.includes('PRINTFILM-Mobile') || ua.includes('Android'))
    return 'mobile'
  return 'web'
}

/** 新壳 UA 标记：检测到则原生代码已负责更新提示，浮层不弹。 */
function nativeUpdateManaged(): boolean {
  const ua = navigator.userAgent || ''
  return ua.includes('PRINTFILM-Desktop/') || ua.includes('PRINTFILM-Mobile/')
}

export function AppUpdateBanner() {
  // 单机开源版：无在线更新，直接返回 null
  if (typeof window !== 'undefined' && (window as any).__PRINTFILM_STANDALONE__) return null
  const platform = useRef<Platform | 'web'>(detectShell())
  const [info, setInfo] = useState<UpdateInfo | null>(null)
  const [dismissed, setDismissed] = useState(false)

  useEffect(() => {
    if (platform.current === 'web') return
    // 新壳由原生负责，本浮层不弹，避免双弹
    if (nativeUpdateManaged()) return
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(
          `/api/update/check?platform=${encodeURIComponent(platform.current)}`,
          { method: 'GET', headers: { Accept: 'application/json' } },
        )
        if (!res.ok) return
        const data: UpdateInfo = await res.json()
        if (cancelled) return
        const seen = localStorage.getItem(SEEN_KEY)
        const fresh =
          data.has_release && (data.force || data.latest_version !== seen)
        if (fresh) setInfo(data)
      } catch {
        /* 网络失败不打扰用户 */
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  function remember() {
    if (info?.latest_version) {
      try {
        localStorage.setItem(SEEN_KEY, info.latest_version)
      } catch {
        /* ignore */
      }
    }
    setDismissed(true)
  }

  function openInstaller() {
    if (!info?.url) return
    window.open(info.url, '_blank', 'noopener,noreferrer')
    remember()
  }

  if (platform.current === 'web') return null
  if (nativeUpdateManaged()) return null // 新壳由原生弹框负责
  if (!info || dismissed) return null

  const isDesktop = platform.current === 'desktop'
  const title = isDesktop ? 'PRINTFILM 桌面端' : 'PRINTFILM 手机版'

  return (
    <div className="pf-appupdate-root" role="alertdialog" aria-label="发现新版本">
      <div className="pf-appupdate-card">
        <div className="pf-appupdate-mark" aria-hidden>
          ⟳
        </div>
        <div className="pf-appupdate-body">
          <strong>{info.force ? '需要更新' : '发现新版本'}</strong>
          <p>
            {title} 检测到 v{info.latest_version}
            {info.notes ? `：${info.notes}` : ' 已发布。'}
          </p>
        </div>
        <div className="pf-appupdate-actions">
          <button
            type="button"
            className="pf-appupdate-btn pf-appupdate-btn-primary"
            onClick={openInstaller}
          >
            立即更新
          </button>
          <button type="button" className="pf-appupdate-btn" onClick={remember}>
            稍后再说
          </button>
        </div>
      </div>
    </div>
  )
}
