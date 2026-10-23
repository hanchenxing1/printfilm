import { dialog } from './dialog'


/** 是否为余额不足 / 计费拦截类错误 */
export function isBillingError(message: string) {
  return /余额不足|请先充值|402|insufficient_balance/i.test(message)
}

/** 本地版未启用计费：余额类错误不再引导充值 */

/**
 * 弹出余额不足提示；若用户选择去充值则跳转定价页。
 * @returns 是否已按计费错误处理
 */
export async function handleBillingError(
  err: unknown,
  navigate?: (path: string) => void,
): Promise<boolean> {
  const message = err instanceof Error ? err.message : String(err || '')
  if (!isBillingError(message)) return false
  // 本地版不计费，原样提示即可（navigate 参数保留兼容）
  void navigate
  await dialog.alert({
    title: '提示',
    message: message || '本次生成未成功，请重试。',
    confirmText: '知道了',
  })
  return true
}

/**
 * API 层全局拦截：402 / 余额不足时弹出充值引导（不吞掉原错误）。
 */
export function notifyBillingErrorIfNeeded(status: number, message: string) {
  if (status === 402 || isBillingError(message)) {
    void handleBillingError(new Error(message))
  }
}
