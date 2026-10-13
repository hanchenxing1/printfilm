/** 前台计费开关状态：与后台「支付与计费」开关（billing_enabled）保持一致 */
import { useEffect, useState } from 'react'
import { api } from '../api'

let cached: boolean | null = null

export function cachedBillingEnabled(): boolean | null {
  return cached
}

/** 其他组件拿到 wallet 后回填缓存，避免 hook 重复请求 */
export function primeBillingEnabled(value: boolean) {
  cached = value
}

/**
 * 读取后台计费开关。已登录时拉 /api/billing/wallet 取 billing_enabled，
 * 模块级缓存一次（开关在后台修改后刷新页面即生效）。
 * 未登录 / 拉取失败返回 null，调用方按本地版（免费）兜底。
 */
export function useBillingEnabled(): boolean | null {
  const [val, setVal] = useState<boolean | null>(cached)
  useEffect(() => {
    if (cached != null || !localStorage.getItem('token')) return
    let cancelled = false
    api
      .wallet()
      .then((w) => {
        cached = Boolean(w.billing_enabled)
        if (!cancelled) setVal(cached)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])
  return val
}
