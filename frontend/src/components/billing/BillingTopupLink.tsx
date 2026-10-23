import type { CSSProperties } from 'react'

type Props = {
  className?: string
  children?: string
  style?: CSSProperties
}

/** 内联计费提示（本地版未启用计费，不再跳转充值页） */
export default function BillingTopupLink({
  className = 'pf-link pf-billing-topup-link',
  children = '本地版不计费，无需充值',
  style,
}: Props) {
  return (
    <span className={className} style={style}>
      {children}
    </span>
  )
}
