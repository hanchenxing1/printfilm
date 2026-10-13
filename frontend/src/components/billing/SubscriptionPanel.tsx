import { useCallback, useEffect, useMemo, useState } from 'react'
import PaymentBrandIcon from './PaymentBrandIcon'
import PaymentModal, { type PayCheckout } from './PaymentModal'
import {
  api,
  type BillingOrder,
  type BillingSku,
  type SubscriptionState,
  type Wallet,
} from '../../api'
import { primeBillingEnabled } from '../../lib/billingState'
import type { PerksUsage } from '../../api'

type PayType = 'alipay' | 'wxpay'

type Props = {
  variant?: 'panel' | 'compact'
}

type SubOrder = BillingOrder & { sku_label?: string }

// 快捷充值档位（元）；自定义输入范围 ¥10–¥5000（后端 topup_custom 校验）
const TOPUP_QUICK_YUAN = [10, 49, 99, 199]
const TOPUP_MIN_YUAN = 10
const TOPUP_MAX_YUAN = 5000

const SKU_LABELS: Record<string, string> = {
  topup_custom: '余额充值',
  sub_plus_day: 'Plus 日卡',
  sub_plus_week: 'Plus 周卡',
  sub_plus_month: 'Plus 月卡',
  sub_plus_year: 'Plus 年卡',
  sub_pro_day: 'Pro 日卡',
  sub_pro_week: 'Pro 周卡',
  sub_pro_month: 'Pro 月卡',
  sub_pro_year: 'Pro 年卡',
}

const PLAN_LABELS: Record<string, string> = {
  free: '免费',
  plus: 'Plus',
  pro: 'Pro',
}

const PERIOD_LABELS: Record<number, string> = {
  1: '日卡',
  7: '周卡',
  30: '月卡',
  365: '年卡',
}

const STATUS_CN: Record<string, string> = {
  pending: '待支付',
  paid: '已到账',
  closed: '已关闭',
}

const SUB_STATUS_CN: Record<string, string> = {
  active: '生效中',
  lapsed: '已失效',
  cancelled: '已取消',
}

function yuan(fen: number) {
  return (fen / 100).toFixed(2)
}

function yuanShort(fen: number) {
  const v = fen / 100
  return Number.isInteger(v) ? String(v) : v.toFixed(2)
}

function formatTime(iso?: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(
    d.getMinutes(),
  )}`
}

/** 权益文案：推理免费 / 生图 N 次 / 视频 M 分钟优先生成 */
function perksText(sku: BillingSku): string[] {
  const perks = sku.perks || {}
  const out: string[] = []
  if (perks.llm_free) out.push('推理免费')
  if (perks.image_calls_per_day) out.push(`生图 ${perks.image_calls_per_day} 次/日`)
  if (perks.video_priority_minutes_per_day)
    out.push(`视频 ${perks.video_priority_minutes_per_day} 分钟/日优先生成`)
  return out
}

/** 权益行「今日已用」用量：按权益文本前缀匹配生图/视频，挂实时用量 */
function perkUsageExtra(p: string, perks: Record<string, unknown>, used?: PerksUsage): string | null {
  if (!used) return null
  const imageLimit = (perks.image_calls_per_day as number) || 0
  const videoLimitMin = (perks.video_priority_minutes_per_day as number) || 0
  if (p.startsWith('生图') && imageLimit > 0)
    return `今日已用 ${used.image_calls} / ${imageLimit} 次`
  if (p.startsWith('视频') && videoLimitMin > 0) {
    const usedSec = Math.min(used.video_seconds, videoLimitMin * 60)
    return `今日已用 ${(usedSec / 60).toFixed(1)} / ${videoLimitMin} 分钟`
  }
  return null
}

/** 订阅与余额面板：余额充值（快捷+自定义金额）+ 订阅（Plus/Pro 周期自选）+ 记录列表 */
export default function SubscriptionPanel({ variant = 'compact' }: Props) {
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [skus, setSkus] = useState<BillingSku[]>([])
  const [orders, setOrders] = useState<SubOrder[]>([])
  const [ordersLoading, setOrdersLoading] = useState(false)
  const [subState, setSubState] = useState<SubscriptionState | null>(null)
  const [payType, setPayType] = useState<PayType>('alipay')
  const [busy, setBusy] = useState<string | null>(null)
  const [cancelBusy, setCancelBusy] = useState(false)
  const [checkout, setCheckout] = useState<PayCheckout | null>(null)
  const [error, setError] = useState('')
  const [hint, setHint] = useState('')
  // 余额充值：快捷档位 + 自定义金额
  const [customAmount, setCustomAmount] = useState<string>('')
  // 订阅周期自选
  const [plusPeriod, setPlusPeriod] = useState<number>(30)
  const [proPeriod, setProPeriod] = useState<number>(30)

  const loggedIn = Boolean(localStorage.getItem('token'))
  const billingOn = Boolean(wallet?.billing_enabled)

  const subSkus = skus.filter((s) => s.kind === 'subscription')
  const plusSkus = useMemo(
    () => subSkus.filter((s) => s.plan === 'plus'),
    [skus],
  )
  const proSkus = useMemo(() => subSkus.filter((s) => s.plan === 'pro'), [skus])
  const plusSku = plusSkus.find((s) => (s.period_days ?? 0) === plusPeriod) ?? plusSkus[0]
  const proSku = proSkus.find((s) => (s.period_days ?? 0) === proPeriod) ?? proSkus[0]
  const currentSub = subState?.subscription && subState.active ? subState.subscription : null

  // 自定义金额解析（元 → 分）
  const customAmountFen = useMemo(() => {
    const v = Number(customAmount)
    if (!Number.isFinite(v) || v <= 0) return null
    const fen = Math.round(v * 100)
    if (fen < TOPUP_MIN_YUAN * 100 || fen > TOPUP_MAX_YUAN * 100) return null
    return fen
  }, [customAmount])

  const loadWallet = useCallback(() => {
    api
      .wallet()
      .then((w) => {
        setWallet(w)
        primeBillingEnabled(Boolean(w.billing_enabled))
      })
      .catch(() => undefined)
  }, [])

  const loadSub = useCallback(() => {
    api
      .subscriptionStatus()
      .then(setSubState)
      .catch(() => undefined)
  }, [])

  const loadOrders = useCallback(() => {
    setOrdersLoading(true)
    api
      .listBillingOrders(50)
      .then((r) => setOrders(r.orders || []))
      .catch(() => undefined)
      .finally(() => setOrdersLoading(false))
  }, [])

  useEffect(() => {
    if (!loggedIn) return
    loadWallet()
    loadOrders()
    loadSub()
    api
      .billingSkus()
      .then((r) => setSkus(r.skus || []))
      .catch(() => undefined)
  }, [loggedIn, loadWallet, loadOrders, loadSub])

  /** 统一开单入口：充值传 amount_fen，订阅不传 */
  async function openOrder(skuId: string, label: string, amountFen?: number) {
    if (!loggedIn) {
      window.location.href = `/auth?next=${encodeURIComponent('/settings?tab=subscription')}`
      return
    }
    setBusy(skuId)
    setError('')
    try {
      const order = await api.createBillingOrder(skuId, payType, amountFen)
      setCheckout({
        out_trade_no: order.out_trade_no,
        sku_id: order.sku_id || skuId,
        sku_name: label,
        pay_type: order.pay_type,
        amount_fen: order.amount_fen,
        credit_fen: order.credit_fen,
        pay_mode: order.pay_mode || (order.qr_payload || order.qrcode ? 'qr' : 'redirect'),
        qr_payload: order.qr_payload || order.qrcode || order.img || '',
        payurl: order.payurl || order.submit_url || '',
        img: order.img,
        expire_seconds: order.expire_seconds ?? 300,
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : '下单失败，请稍后重试')
    } finally {
      setBusy(null)
    }
  }

  /** 余额充值（topup_custom，快捷档位或自定义金额） */
  function payTopup() {
    if (customAmountFen === null) {
      setError(`请输入 ¥${TOPUP_MIN_YUAN}–¥${TOPUP_MAX_YUAN} 之间的充值金额`)
      return
    }
    void openOrder(
      'topup_custom',
      `余额充值 ¥${(customAmountFen / 100).toFixed(2)}`,
      customAmountFen,
    )
  }

  /** 订阅开通（按所选周期对应 SKU） */
  function paySub(sku: BillingSku | undefined) {
    if (!sku) return
    void openOrder(sku.id, SKU_LABELS[sku.id] || sku.name)
  }

  async function onPaid() {
    const isSub =
      checkout && subSkus.some((s) => s.id === checkout.sku_id)
        ? true
        : checkout && checkout.sku_id === 'topup_custom'
          ? false
          : null
    setHint(
      isSub
        ? '支付成功，订阅已开通。每个周期结束自动从余额续费，余额不足将降级为免费版。'
        : '支付成功，余额已到账。',
    )
    setCheckout(null)
    loadWallet()
    loadOrders()
    loadSub()
  }

  async function onCancel() {
    if (!loggedIn || cancelBusy) return
    setCancelBusy(true)
    setError('')
    try {
      await api.cancelSubscription()
      setHint('已取消自动续费，当期权益保留至到期日。')
      loadSub()
    } catch (e) {
      setError(e instanceof Error ? e.message : '取消失败，请稍后重试')
    } finally {
      setCancelBusy(false)
    }
  }

  /** 订阅模块（Plus / Pro 各 1 个，周期自选） */
  function renderPlanGroup(title: string, group: BillingSku[], period: number, onPeriod: (d: number) => void, sku: BillingSku | undefined) {
    if (group.length === 0) return null
    return (
      <div className="pf-sub-plan">
        <h4 className="pf-sub-plan-title">{title}</h4>
        {sku ? (
          <>
            <div className="pf-sub-period-picker" role="group" aria-label={`${title} 周期`}>
              {group.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  className={`pf-sub-period-opt${(s.period_days ?? 0) === period ? ' is-active' : ''}`}
                  onClick={() => onPeriod(s.period_days ?? 30)}
                >
                  {PERIOD_LABELS[s.period_days ?? 30] || '月卡'}
                  <em>¥{yuanShort(s.amount_fen)}</em>
                </button>
              ))}
            </div>
            <div className="pf-sub-plan-card">
              <div className="pf-sub-plan-card-head">
                <strong>{PERIOD_LABELS[sku.period_days ?? 30] || '月卡'}</strong>
                <span className="pf-sub-sku-price">
                  <i>¥</i>
                  {yuanShort(sku.amount_fen)}
                  <em>/期</em>
                </span>
              </div>
              <ul className="pf-sub-perks">
                {perksText(sku).map((p) => (
                  <li key={p}>{p}</li>
                ))}
                <li className="pf-sub-perks-note">额度用完降级免费版视频生成（需排队）</li>
              </ul>
              <button
                type="button"
                className="pf-btn pf-btn-lime pf-btn-sm"
                disabled={Boolean(busy)}
                onClick={() => paySub(sku)}
              >
                {busy === sku.id ? '下单中…' : currentSub?.sku_id === sku.id ? '续订' : '开通'}
              </button>
            </div>
          </>
        ) : null}
      </div>
    )
  }

  return (
    <div className={`pf-sub-panel${variant === 'panel' ? ' is-panel' : ''}`}>
      {/* 余额充值模块 */}
      <section className="pf-sub-wallet" aria-label="余额充值">
        <header className="pf-sub-wallet-head">
          <h3>余额充值</h3>
          <p className="pf-muted">{billingOn ? '按量计费，余额永久有效' : '按量计费暂未开启，全部功能免费使用'}</p>
        </header>

        <div className="pf-sub-balance">
          <div className="pf-sub-balance-item">
            <span className="pf-muted">可用余额</span>
            <strong>¥{wallet ? yuan(wallet.balance_fen) : '—'}</strong>
          </div>
          <div className="pf-sub-balance-item">
            <span className="pf-muted">冻结中</span>
            <strong>¥{wallet ? yuan(wallet.frozen_fen) : '—'}</strong>
          </div>
          {(wallet && (wallet.grant_fen ?? 0) > 0) ? (
            <div className="pf-sub-balance-item">
              <span className="pf-muted">
                注册专属额度
                {wallet.grant_expire_at ? `（${formatTime(wallet.grant_expire_at)} 前有效）` : ''}
              </span>
              <strong>¥{yuan(wallet.grant_fen ?? 0)}</strong>
            </div>
          ) : null}
          <div className="pf-sub-balance-item">
            <span className="pf-muted">当前方案</span>
            <strong>{PLAN_LABELS[wallet?.plan || 'free'] || wallet?.plan || '免费'}</strong>
          </div>
        </div>

        {billingOn ? (
          <>
            <div className="pf-sub-pay-tabs" role="tablist" aria-label="支付渠道">
              <button
                type="button"
                role="tab"
                aria-selected={payType === 'alipay'}
                className={`pf-sub-pay-tab${payType === 'alipay' ? ' is-active' : ''}`}
                onClick={() => setPayType('alipay')}
              >
                <PaymentBrandIcon brand="alipay" size="sm" />
                <span>支付宝</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={payType === 'wxpay'}
                className={`pf-sub-pay-tab${payType === 'wxpay' ? ' is-active' : ''}`}
                onClick={() => setPayType('wxpay')}
              >
                <PaymentBrandIcon brand="wxpay" size="sm" />
                <span>微信支付</span>
              </button>
            </div>

            {hint ? <p className="pf-sub-hint">{hint}</p> : null}
            {error ? <p className="pf-error">{error}</p> : null}

            {/* 充值金额：快捷档位 + 自定义输入 */}
            <div className="pf-sub-amount-options" role="group" aria-label="快捷金额">
              {TOPUP_QUICK_YUAN.map((v) => (
                <button
                  key={v}
                  type="button"
                  className={`pf-sub-amount-opt${customAmount === String(v) ? ' is-active' : ''}`}
                  onClick={() => setCustomAmount(String(v))}
                >
                  ¥{v}
                </button>
              ))}
            </div>
            <label className="pf-sub-custom-amount">
              <span className="pf-muted">自定义金额（¥{TOPUP_MIN_YUAN}–¥{TOPUP_MAX_YUAN}）</span>
              <span className="pf-sub-custom-amount-box">
                <span className="yen">¥</span>
                <input
                  type="number"
                  min={TOPUP_MIN_YUAN}
                  max={TOPUP_MAX_YUAN}
                  step={1}
                  inputMode="decimal"
                  placeholder={`${TOPUP_MIN_YUAN}–${TOPUP_MAX_YUAN}`}
                  value={customAmount}
                  onChange={(e) => setCustomAmount(e.target.value)}
                />
              </span>
            </label>
            <div className="pf-sub-sku-row">
              <span className="pf-sub-sku-price">
                <i>¥</i>
                {customAmountFen !== null ? yuanShort(customAmountFen) : '—'}
              </span>
              <button
                type="button"
                className="pf-btn pf-btn-lime pf-btn-sm"
                disabled={Boolean(busy) || customAmountFen === null}
                onClick={payTopup}
              >
                {busy === 'topup_custom' ? '下单中…' : '充值'}
              </button>
            </div>
          </>
        ) : (
          <p className="pf-sub-free">当前未启用计费与会员限制，全部功能免费使用，无需充值。</p>
        )}
      </section>

      {/* 当前订阅状态 */}
      {billingOn ? (
        <section className="pf-sub-status" aria-label="当前订阅">
          <header className="pf-sub-wallet-head">
            <h3>我的订阅</h3>
          </header>
          {currentSub ? (
            <div className="pf-sub-status-card">
              <div className="pf-sub-status-main">
                <strong>
                  {PLAN_LABELS[currentSub.plan] || currentSub.plan}
                  {PERIOD_LABELS[currentSub.period_days] ? ` · ${PERIOD_LABELS[currentSub.period_days]}` : ''}
                </strong>
                <span className={`pf-sub-order-status is-${currentSub.status}`}>
                  {SUB_STATUS_CN[currentSub.status] || currentSub.status}
                </span>
              </div>
              <ul className="pf-sub-perks">
                {perksText({ perks: currentSub.perks } as BillingSku).map((p) => (
                  <li key={p}>
                    {p}
                    {(() => {
                      const extra = perkUsageExtra(p, currentSub.perks, subState?.perks_usage)
                      return extra ? <em className="pf-sub-perk-used"> · {extra}</em> : null
                    })()}
                  </li>
                ))}
              </ul>
              <div className="pf-sub-status-meta">
                <span className="pf-muted">到期时间</span>
                <em>{formatTime(currentSub.expires_at)}</em>
                {currentSub.auto_renew ? (
                  <span className="pf-muted">
                    自动续费开启，每期 ¥{yuanShort(currentSub.amount_fen)} 从余额扣除
                  </span>
                ) : (
                  <span className="pf-muted">自动续费已关闭</span>
                )}
              </div>
              {currentSub.auto_renew ? (
                <button
                  type="button"
                  className="pf-btn pf-btn-ghost pf-btn-sm"
                  disabled={cancelBusy}
                  onClick={() => void onCancel()}
                >
                  {cancelBusy ? '取消中…' : '取消自动续费'}
                </button>
              ) : null}
            </div>
          ) : (
            <p className="pf-muted">尚未开通订阅。开通后每个周期结束自动从余额续费，余额不足时降级为免费版。</p>
          )}
        </section>
      ) : null}

      {/* 订阅档位（Plus / Pro 周期自选） */}
      {billingOn ? (
        <section className="pf-sub-plans" aria-label="订阅档位">
          <header className="pf-sub-wallet-head">
            <h3>订阅档位</h3>
            <p className="pf-muted">开通后自动续费：每期从余额扣款，扣款失败订阅失效并降级免费版。</p>
          </header>
          {renderPlanGroup('Plus', plusSkus, plusPeriod, setPlusPeriod, plusSku)}
          {renderPlanGroup('Pro', proSkus, proPeriod, setProPeriod, proSku)}
        </section>
      ) : null}

      {/* 订阅 / 充值记录列表 */}
      <section className="pf-sub-orders" aria-label="订阅与充值记录">
        <header className="pf-sub-orders-head">
          <h3>订阅与充值记录</h3>
          <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm" onClick={loadOrders}>
            刷新
          </button>
        </header>

        {ordersLoading ? <p className="pf-muted">加载中…</p> : null}
        {!ordersLoading && orders.length === 0 ? (
          <p className="pf-muted">暂无订阅与充值记录</p>
        ) : null}

        {!ordersLoading && orders.length > 0 ? (
          <ul className="pf-sub-order-list">
            {orders.map((o) => (
              <li key={o.out_trade_no} className="pf-sub-order">
                <div className="pf-sub-order-main">
                  <strong>{SKU_LABELS[o.sku_id] || o.sku_name}</strong>
                  <span className="pf-muted">{formatTime(o.paid_at || o.created_at)}</span>
                </div>
                <div className="pf-sub-order-meta">
                  <em>¥{yuan(o.amount_fen)}</em>
                  {o.credit_fen > 0 ? <span className="pf-muted">到账 ¥{yuan(o.credit_fen)}</span> : (
                    <span className="pf-muted">订阅开通</span>
                  )}
                  <span className={`pf-sub-order-status is-${o.status}`}>
                    {STATUS_CN[o.status] || o.status}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <PaymentModal
        open={Boolean(checkout)}
        checkout={checkout}
        onClose={() => setCheckout(null)}
        onPaid={() => void onPaid()}
      />
    </div>
  )
}
