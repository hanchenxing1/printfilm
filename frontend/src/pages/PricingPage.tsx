import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  Building2,
  Check,
  CreditCard,
  Infinity,
  ShieldCheck,
  Zap,
} from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import PaymentBrandIcon from '../components/billing/PaymentBrandIcon'
import PaymentModal, { type PayCheckout } from '../components/billing/PaymentModal'
import PricingWalletCard from '../components/billing/PricingWalletCard'
import TopupHistoryModal from '../components/billing/TopupHistoryModal'
import { api, type BillingSku, type UsageSummary, type Wallet } from '../api'
import { useI18n } from '../i18n'

type PayType = 'alipay' | 'wxpay'

type SkuView = BillingSku & { recommended?: boolean }

const HERO_FEATURE_KEYS = ['featInstant', 'featSafe', 'featForever'] as const

// 快捷充值档位（元）；自定义输入范围 ¥10–¥5000（后端 topup_custom 校验）
const TOPUP_QUICK_YUAN = [10, 49, 99, 199]
const TOPUP_MIN_YUAN = 10
const TOPUP_MAX_YUAN = 5000

function yuan(fen: number) {
  return (fen / 100).toFixed(2)
}

const PERIOD_NAME: Record<number, string> = {
  1: '日卡',
  7: '周卡',
  30: '月卡',
  365: '年卡',
}

/** 权益文案：推理免费 / 生图 N 次 / 视频 M 分钟优先生成 */
function perkText(sku: BillingSku): string {
  const perks = sku.perks || {}
  const out: string[] = []
  if (perks.llm_free) out.push('推理免费')
  if (perks.image_calls_per_day) out.push(`生图 ${perks.image_calls_per_day} 次/日`)
  if (perks.video_priority_minutes_per_day)
    out.push(`视频 ${perks.video_priority_minutes_per_day} 分钟/日优先生成`)
  return out.join(' · ')
}

/** 定价与充值页：余额充值（快捷+自定义）/ Plus 订阅（周期自选）/ Pro 订阅（周期自选） */
export default function PricingPage() {
  const nav = useNavigate()
  const { t, m } = useI18n()
  const [params] = useSearchParams()
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [usage, setUsage] = useState<UsageSummary | null>(null)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [skus, setSkus] = useState<SkuView[]>([])
  const [payType, setPayType] = useState<PayType>('alipay')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [hint, setHint] = useState('')
  const [payTip, setPayTip] = useState('')
  const [checkout, setCheckout] = useState<PayCheckout | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const loggedIn = Boolean(localStorage.getItem('token'))

  // 余额充值：快捷档位 + 自定义金额（输入框，单位元）
  const [customAmount, setCustomAmount] = useState<string>('')
  // 订阅周期自选：默认月卡
  const [plusPeriod, setPlusPeriod] = useState<number>(30)
  const [proPeriod, setProPeriod] = useState<number>(30)

  const plusSkus = useMemo(() => skus.filter((s) => s.kind === 'subscription' && s.plan === 'plus'), [skus])
  const proSkus = useMemo(() => skus.filter((s) => s.kind === 'subscription' && s.plan === 'pro'), [skus])
  const plusSku = plusSkus.find((s) => (s.period_days ?? 0) === plusPeriod) ?? plusSkus[0]
  const proSku = proSkus.find((s) => (s.period_days ?? 0) === proPeriod) ?? proSkus[0]

  // 自定义金额解析（元 → 分）
  const customAmountFen = useMemo(() => {
    const v = Number(customAmount)
    if (!Number.isFinite(v) || v <= 0) return null
    const fen = Math.round(v * 100)
    if (fen < TOPUP_MIN_YUAN * 100 || fen > TOPUP_MAX_YUAN * 100) return null
    return fen
  }, [customAmount])

  async function refresh() {
    if (!loggedIn) {
      setWallet(null)
      setUsage(null)
      setUpdatedAt(null)
      return
    }
    try {
      const [w, u] = await Promise.all([api.wallet(), api.usageSummary()])
      setWallet(w)
      setUsage(u)
      setUpdatedAt(new Date())
    } catch {
      /* ignore */
    }
  }

  useEffect(() => {
    api.billingSkus().then((r) => setSkus((r.skus || []) as SkuView[]))
    refresh()
    if (params.get('paid') === '1') {
      setHint(t('pricing.paidHint'))
      const timerId = window.setInterval(() => refresh(), 2500)
      return () => window.clearInterval(timerId)
    }
  }, [])

  /** 统一开单入口：充值传 amount_fen，订阅不传 */
  async function openOrder(skuId: string, label: string, amountFen?: number) {
    if (!loggedIn) {
      nav(`/auth?next=${encodeURIComponent(`/pricing#sku-${skuId}`)}`)
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
      setError(e instanceof Error ? e.message : t('pricing.orderFailed'))
    } finally {
      setBusy(null)
    }
  }

  /** 余额充值：快捷档位/自定义金额 → topup_custom */
  function payTopup() {
    if (customAmountFen === null) {
      setError(`请输入 ¥${TOPUP_MIN_YUAN}–¥${TOPUP_MAX_YUAN} 之间的充值金额`)
      return
    }
    const label = m.pricing.skus['topup_custom'] || '余额充值'
    void openOrder(
      'topup_custom',
      `${label} ¥${(customAmountFen / 100).toFixed(2)}`,
      customAmountFen,
    )
  }

  /** 订阅开通：按所选周期对应的 SKU 下单 */
  function paySub(sku: SkuView | undefined) {
    if (!sku) return
    void openOrder(sku.id, sku.name)
  }

  function pickPay(type: PayType) {
    setPayType(type)
    setPayTip('')
  }

  function pickUnavailable(label: string) {
    setPayTip(t('pricing.unavailable', { label }))
  }

  async function onPaid() {
    setHint(t('pricing.paidOk'))
    setCheckout(null)
    await refresh()
  }

  return (
    <AppShell active="pricing" hideFooter wide>
      <div className="pf-pricing-page">
        <section className="pf-pricing-hero-band">
          <div className="pf-pricing-hero-inner">
            <div className="pf-pricing-hero-copy">
              <h1>{t('pricing.title')}</h1>
              <p>{t('pricing.lead')}</p>
              <ul className="pf-pricing-hero-features">
                {HERO_FEATURE_KEYS.map((key, i) => {
                  const icons = [Zap, ShieldCheck, Infinity] as const
                  const Icon = icons[i]
                  return (
                  <li key={key}>
                    <span className="pf-pricing-hero-feature-icon" aria-hidden>
                      <Icon size={15} strokeWidth={2.2} />
                    </span>
                    {t(`pricing.${key}`)}
                  </li>
                  )
                })}
              </ul>
              {!loggedIn ? (
                <p className="pf-pricing-guest-tip">
                  {t('pricing.guestPrefix')}
                  <Link to="/auth?next=%2Fpricing">{t('pricing.guestLogin')}</Link>
                  {t('pricing.guestSuffix')}
                </p>
              ) : null}
            </div>
            <PricingWalletCard
              wallet={wallet}
              usage={usage}
              loggedIn={loggedIn}
              updatedAt={updatedAt}
              onHistory={() => setHistoryOpen(true)}
            />
          </div>
        </section>

        <div className="pf-pricing-body">
          {hint ? <p className="pf-pricing-hint">{hint}</p> : null}
          {error ? <p className="pf-error pf-pricing-error">{error}</p> : null}

          <section className="pf-pricing-pay-section" aria-label={t('pricing.payMethods')}>
            <header className="pf-pricing-section-head is-row">
              <h2>{t('pricing.payMethods')}</h2>
              <div className="pf-pricing-pay-trust">
                <ShieldCheck size={16} aria-hidden />
                <span>{t('pricing.paySafe')}</span>
              </div>
            </header>

            {payTip ? <p className="pf-pricing-pay-tip">{payTip}</p> : null}

            <div className="pf-pricing-pay-grid">
              <button
                type="button"
                className={`pf-pricing-pay-tile${payType === 'alipay' ? ' is-active' : ''}`}
                onClick={() => pickPay('alipay')}
                aria-pressed={payType === 'alipay'}
              >
                <PaymentBrandIcon brand="alipay" size="md" />
                <span className="pf-pricing-pay-tile-label">{t('pricing.alipay')}</span>
                <span className="pf-pricing-pay-tile-badge">{t('pricing.recommended')}</span>
                {payType === 'alipay' ? (
                  <span className="pf-pricing-pay-tile-check" aria-hidden>
                    <Check size={14} strokeWidth={3} />
                  </span>
                ) : null}
              </button>

              <button
                type="button"
                className={`pf-pricing-pay-tile${payType === 'wxpay' ? ' is-active' : ''}`}
                onClick={() => pickPay('wxpay')}
                aria-pressed={payType === 'wxpay'}
              >
                <PaymentBrandIcon brand="wxpay" size="md" />
                <span className="pf-pricing-pay-tile-label">{t('pricing.wechat')}</span>
                {payType === 'wxpay' ? (
                  <span className="pf-pricing-pay-tile-check" aria-hidden>
                    <Check size={14} strokeWidth={3} />
                  </span>
                ) : null}
              </button>

              <button
                type="button"
                className="pf-pricing-pay-tile is-disabled"
                title={t('pricing.soonTitle')}
                onClick={() => pickUnavailable(t('pricing.unionpay'))}
              >
                <PaymentBrandIcon brand="unionpay" size="md" />
                <span className="pf-pricing-pay-tile-label">{t('pricing.unionpay')}</span>
                <span className="pf-pricing-pay-tile-soon">{t('common.comingSoon')}</span>
              </button>

              <button
                type="button"
                className="pf-pricing-pay-tile is-disabled"
                title={t('pricing.transferTitle')}
                onClick={() => pickUnavailable(t('pricing.transfer'))}
              >
                <span className="pf-pricing-pay-tile-icon" aria-hidden>
                  <Building2 size={22} strokeWidth={1.8} />
                </span>
                <span className="pf-pricing-pay-tile-label">{t('pricing.transfer')}</span>
                <span className="pf-pricing-pay-tile-sub">{t('pricing.enterprise')}</span>
              </button>
            </div>
          </section>

          <section className="pf-pricing-skus" id="pricing-skus">
            <header className="pf-pricing-section-head">
              <h2>{t('pricing.chooseAmount')}</h2>
            </header>

            <div className="pf-pricing-sku-grid pf-pricing-sku-grid-mods">
              {/* 模块 1：余额充值（快捷档位 + 自定义金额） */}
              <article
                id="sku-topup_custom"
                className="pf-pricing-sku-card is-recommended"
              >
                <span className="pf-pricing-rec-badge">{t('pricing.recommended')}</span>
                <p className="pf-pricing-sku-tier">{m.pricing.skus['topup_custom'] || '余额充值'}</p>
                <p className="pf-pricing-sku-hint">{t('pricing.topupHint')}</p>

                <div className="pf-pricing-amount-options" role="group" aria-label="快捷金额">
                  {TOPUP_QUICK_YUAN.map((v) => (
                    <button
                      key={v}
                      type="button"
                      className={`pf-pricing-amount-opt${customAmount === String(v) ? ' is-active' : ''}`}
                      onClick={() => setCustomAmount(String(v))}
                    >
                      ¥{v}
                    </button>
                  ))}
                </div>

                <label className="pf-pricing-custom-amount">
                  <span className="pf-pricing-custom-amount-label">自定义金额</span>
                  <span className="pf-pricing-custom-amount-box">
                    <span className="yen">¥</span>
                    <input
                      type="number"
                      min={TOPUP_MIN_YUAN}
                      max={TOPUP_MAX_YUAN}
                      step={1}
                      inputMode="decimal"
                      placeholder={`¥${TOPUP_MIN_YUAN}–¥${TOPUP_MAX_YUAN}`}
                      value={customAmount}
                      onChange={(e) => setCustomAmount(e.target.value)}
                    />
                  </span>
                </label>

                <p className="pf-pricing-sku-credit">
                  {customAmountFen !== null ? (
                    <>
                      {t('pricing.credit')} <em>¥{yuan(customAmountFen)}</em>
                    </>
                  ) : (
                    <em className="pf-muted">选择或输入金额</em>
                  )}
                </p>
                <button
                  type="button"
                  className="pf-pricing-sku-cta is-primary"
                  disabled={Boolean(busy) || customAmountFen === null}
                  onClick={payTopup}
                >
                  {busy === 'topup_custom' ? t('pricing.ordering') : t('pricing.payNow')}
                </button>
              </article>

              {/* 模块 2：Plus 订阅（周期自选） */}
              {plusSku ? (
                <article id={`sku-${plusSku.id}`} className="pf-pricing-sku-card is-sub">
                  <p className="pf-pricing-sku-tier">Plus</p>
                  <p className="pf-pricing-sku-hint">{perkText(plusSku)}</p>

                  <div className="pf-pricing-period-picker" role="group" aria-label="Plus 周期">
                    {plusSkus.map((sku) => (
                      <button
                        key={sku.id}
                        type="button"
                        className={`pf-pricing-period-opt${(sku.period_days ?? 0) === plusPeriod ? ' is-active' : ''}`}
                        onClick={() => setPlusPeriod(sku.period_days ?? 30)}
                      >
                        {PERIOD_NAME[sku.period_days ?? 30] || PERIOD_NAME[30]}
                        <em>¥{(sku.amount_fen / 100).toFixed(0)}</em>
                      </button>
                    ))}
                  </div>

                  <div className="pf-pricing-sku-price">
                    <span className="yen">¥</span>
                    <strong>{(plusSku.amount_fen / 100).toFixed(0)}</strong>
                    <span className="pf-pricing-sku-period">
                      /{PERIOD_NAME[plusSku.period_days ?? 30] || PERIOD_NAME[30]}
                    </span>
                  </div>
                  <p className="pf-pricing-sku-credit">
                    自动续费 <em>¥{yuan(plusSku.amount_fen)}/期</em>
                  </p>
                  <button
                    type="button"
                    className="pf-pricing-sku-cta"
                    disabled={Boolean(busy)}
                    onClick={() => paySub(plusSku)}
                  >
                    {busy === plusSku.id ? t('pricing.ordering') : '开通 Plus'}
                  </button>
                </article>
              ) : null}

              {/* 模块 3：Pro 订阅（周期自选） */}
              {proSku ? (
                <article id={`sku-${proSku.id}`} className="pf-pricing-sku-card is-sub">
                  <p className="pf-pricing-sku-tier">Pro</p>
                  <p className="pf-pricing-sku-hint">{perkText(proSku)}</p>

                  <div className="pf-pricing-period-picker" role="group" aria-label="Pro 周期">
                    {proSkus.map((sku) => (
                      <button
                        key={sku.id}
                        type="button"
                        className={`pf-pricing-period-opt${(sku.period_days ?? 0) === proPeriod ? ' is-active' : ''}`}
                        onClick={() => setProPeriod(sku.period_days ?? 30)}
                      >
                        {PERIOD_NAME[sku.period_days ?? 30] || PERIOD_NAME[30]}
                        <em>¥{(sku.amount_fen / 100).toFixed(0)}</em>
                      </button>
                    ))}
                  </div>

                  <div className="pf-pricing-sku-price">
                    <span className="yen">¥</span>
                    <strong>{(proSku.amount_fen / 100).toFixed(0)}</strong>
                    <span className="pf-pricing-sku-period">
                      /{PERIOD_NAME[proSku.period_days ?? 30] || PERIOD_NAME[30]}
                    </span>
                  </div>
                  <p className="pf-pricing-sku-credit">
                    自动续费 <em>¥{yuan(proSku.amount_fen)}/期</em>
                  </p>
                  <button
                    type="button"
                    className="pf-pricing-sku-cta"
                    disabled={Boolean(busy)}
                    onClick={() => paySub(proSku)}
                  >
                    {busy === proSku.id ? t('pricing.ordering') : '开通 Pro'}
                  </button>
                </article>
              ) : null}
            </div>
          </section>

          <section className="pf-pricing-info">
            <article className="pf-pricing-info-card">
              <div className="pf-pricing-info-visual is-billing" aria-hidden>
                <CreditCard size={28} strokeWidth={1.6} />
              </div>
              <div>
                <h3>{t('pricing.billingTitle')}</h3>
                <ul>
                  <li>{t('pricing.billing1')}</li>
                  <li>{t('pricing.billing2')}</li>
                  <li>{t('pricing.billing3')}</li>
                </ul>
              </div>
            </article>
            <article className="pf-pricing-info-card">
              <div className="pf-pricing-info-visual is-value" aria-hidden>
                <Check size={28} strokeWidth={2.5} />
              </div>
              <div>
                <h3>{t('pricing.whyTitle')}</h3>
                <ul className="pf-pricing-checks">
                  <li>{t('pricing.why1')}</li>
                  <li>{t('pricing.why2')}</li>
                  <li>{t('pricing.why3')}</li>
                </ul>
              </div>
            </article>
          </section>

          <footer className="pf-pricing-site-foot">
            <p className="pf-pricing-site-brand">
              <Link to="/">PRINTFILM</Link>
              <span> · {t('pricing.footBrand')}</span>
            </p>
            <nav className="pf-pricing-site-links" aria-label={t('footer.links')}>
              <Link to="/terms">{t('footer.terms')}</Link>
              <Link to="/privacy">{t('footer.privacy')}</Link>
              <Link to="/contact">{t('footer.contact')}</Link>
            </nav>
            <p className="pf-pricing-site-copy">© {new Date().getFullYear()} PRINTFILM. All rights reserved.</p>
          </footer>
        </div>
      </div>

      <PaymentModal
        open={Boolean(checkout)}
        checkout={checkout}
        onClose={() => setCheckout(null)}
        onPaid={() => void onPaid()}
      />
      <TopupHistoryModal open={historyOpen} onClose={() => setHistoryOpen(false)} />
    </AppShell>
  )
}
