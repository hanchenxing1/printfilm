import type { CSSProperties } from 'react'
import { isBillingError } from '../../lib/billingError'

type Props = {
  message: string | null | undefined
  className?: string
  style?: CSSProperties
  /** 使用 span 而非 p（工具栏条内联错误） */
  inline?: boolean
}

/** 错误提示（本地版未启用计费，余额类错误按普通错误展示，不再引导充值） */
export default function BillingErrorNotice({
  message,
  className = 'pf-error',
  style,
  inline = false,
}: Props) {
  const text = String(message || '').trim()
  if (!text) return null
  const Tag = inline ? 'span' : 'p'
  if (!isBillingError(text)) {
    return (
      <Tag className={className} style={style} role={inline ? undefined : 'alert'}>
        {text}
      </Tag>
    )
  }
  return (
    <Tag className={className} style={style} role={inline ? undefined : 'alert'}>
      {text}
    </Tag>
  )
}
