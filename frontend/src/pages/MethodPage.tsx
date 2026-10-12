/** 获客短视频宣传页：方法论结构 + 开始使用 / 回到 GEO */
import { useEffect, type ReactNode } from 'react'
import { ArrowRight, ArrowUpRight } from 'lucide-react'
import LanguageSwitch from '../components/layout/LanguageSwitch'
import { useI18n } from '../i18n'
import {
  METHOD_GEO_URL,
  METHOD_LANDING,
  METHOD_START_URL,
  type MethodLandingCopy,
} from '../lib/methodLanding'
import './method/method.css'

const PAGE_URL = 'https://www.printfilm.com/method'

// 注入本页 title / description；延迟一拍以免被 I18nProvider 的默认 meta 覆盖
function useMethodMeta(copy: MethodLandingCopy) {
  useEffect(() => {
    const descEl = document.querySelector('meta[name="description"]')
    const prevTitle = document.title
    const prevDesc = descEl?.getAttribute('content')

    // 写入宣传页 SEO 文案
    function apply() {
      document.title = copy.metaTitle
      descEl?.setAttribute('content', copy.metaDescription)
    }

    apply()
    const timer = window.setTimeout(apply, 0)
    return () => {
      window.clearTimeout(timer)
      document.title = prevTitle
      if (descEl && prevDesc) descEl.setAttribute('content', prevDesc)
    }
  }, [copy.metaTitle, copy.metaDescription])
}

// 外链按钮：开始使用 / 回到 GEO
function MethodCta({
  href,
  className,
  children,
}: {
  href: string
  className: string
  children: ReactNode
}) {
  return (
    <a className={className} href={href} rel="noopener noreferrer">
      {children}
    </a>
  )
}

/** 获客短视频宣传页主体：方法论章节 + 双 CTA */
export default function MethodPage() {
  const { locale } = useI18n()
  const copy = METHOD_LANDING[locale]
  useMethodMeta(copy)

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'Article',
    headline: copy.jsonLdHeadline,
    description: copy.metaDescription,
    inLanguage: locale === 'zh' ? 'zh-CN' : 'en',
    author: { '@type': 'Organization', name: 'PRINTFILM' },
    publisher: { '@type': 'Organization', name: 'PRINTFILM' },
    mainEntityOfPage: { '@type': 'WebPage', '@id': PAGE_URL },
    about: copy.toc.map((item) => ({ '@type': 'Thing', name: item.label })),
  }

  return (
    <div className="pf-method">
      <script type="application/ld+json">{JSON.stringify(jsonLd)}</script>
      <a className="pf-method-skip" href="#method-main">
        {copy.skip}
      </a>

      <header className="pf-method-nav">
        <a className="pf-method-brand" href={METHOD_START_URL} rel="noopener noreferrer">
          <img src="/logo.svg" alt="" />
          <span className="pf-method-word">
            <strong>PRINTFILM</strong>
            <span>{copy.brandLine}</span>
          </span>
        </a>
        <div className="pf-method-nav-actions">
          <LanguageSwitch />
          <MethodCta href={METHOD_START_URL} className="pf-method-btn is-lime">
            {copy.startCta}
            <ArrowRight size={15} strokeWidth={2.2} aria-hidden />
          </MethodCta>
          <MethodCta href={METHOD_GEO_URL} className="pf-method-btn is-ghost">
            {copy.geoCta}
            <ArrowUpRight size={15} strokeWidth={2.2} aria-hidden />
          </MethodCta>
        </div>
      </header>

      <main className="pf-method-main" id="method-main">
        <section className="pf-method-hero">
          <p className="pf-method-kicker">{copy.kicker}</p>
          <h1>{copy.title}</h1>
          <p className="pf-method-lede">
            {copy.ledeBefore}
            <em>{copy.ledeEm}</em>
            {copy.ledeAfter}
          </p>
        </section>

        <aside className="pf-method-notice">
          <strong>{copy.noticeTitle}</strong>
          <p>{copy.noticeBody}</p>
        </aside>

        <ul className="pf-method-toc">
          {copy.toc.map((item) => (
            <li key={item.href}>
              <a href={item.href}>{item.label}</a>
            </li>
          ))}
        </ul>

        <section className="pf-method-section" id="sop">
          <p className="pf-method-kicker">{copy.sopKicker}</p>
          <h2>{copy.sopTitle}</h2>
          <p className="pf-method-lead">
            {copy.sopLeadBefore}
            <em>{copy.sopLeadEm}</em>
          </p>
          <ol className="pf-method-steps">
            {copy.sopSteps.map((step) => (
              <li key={step.title}>
                <h3>{step.title}</h3>
                <p>{step.body}</p>
                {step.note ? <p className="pf-method-note">{step.note}</p> : null}
              </li>
            ))}
          </ol>
          <aside className="pf-method-callout">
            <strong>{copy.sopCalloutTitle}</strong>
            <p>{copy.sopCalloutBody}</p>
          </aside>
        </section>

        <section className="pf-method-section" id="geo">
          <p className="pf-method-kicker">{copy.geoKicker}</p>
          <h2>{copy.geoTitle}</h2>
          <p className="pf-method-lead">{copy.geoLead}</p>
          <div className="pf-method-grid">
            {copy.geoCards.map((card) => (
              <article key={card.title}>
                <h3>{card.title}</h3>
                <p>{card.body}</p>
              </article>
            ))}
          </div>
          <aside className="pf-method-callout">
            <strong>{copy.geoCalloutTitle}</strong>
            <p>{copy.geoCalloutBody}</p>
          </aside>
        </section>

        <section className="pf-method-section" id="dist">
          <p className="pf-method-kicker">{copy.distKicker}</p>
          <h2>{copy.distTitle}</h2>
          <p className="pf-method-lead">{copy.distLead}</p>
          <div className="pf-method-table-wrap">
            <table className="pf-method-table">
              <caption className="pf-method-caption">{copy.distTableCaption}</caption>
              <thead>
                <tr>
                  {copy.distTableHead.map((head) => (
                    <th key={head} scope="col">
                      {head}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {copy.distRows.map((row) => (
                  <tr key={row.platform}>
                    <th scope="row">{row.platform}</th>
                    <td>{row.form}</td>
                    <td>{row.focus}</td>
                    <td>{row.owner}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <aside className="pf-method-callout">
            <strong>{copy.distCalloutTitle}</strong>
            <p>{copy.distCalloutBody}</p>
          </aside>
        </section>

        <section className="pf-method-section" id="pace">
          <p className="pf-method-kicker">{copy.paceKicker}</p>
          <h2>{copy.paceTitle}</h2>
          <p className="pf-method-lead">{copy.paceLead}</p>
          <div className="pf-method-split">
            <section>
              <h3>{copy.paceIncludeTitle}</h3>
              <ul>
                {copy.paceInclude.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
            <section>
              <h3>{copy.paceExcludeTitle}</h3>
              <ul>
                {copy.paceExclude.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          </div>
          <aside className="pf-method-callout">
            <strong>{copy.paceCalloutTitle}</strong>
            <p>{copy.paceCalloutBody}</p>
          </aside>
        </section>

        <section className="pf-method-section" id="qc">
          <p className="pf-method-kicker">{copy.qcKicker}</p>
          <h2>{copy.qcTitle}</h2>
          <p className="pf-method-lead">{copy.qcLead}</p>
          <div className="pf-method-grid">
            {copy.qcCards.map((card) => (
              <article key={card.title}>
                <h3>{card.title}</h3>
                <p>{card.body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="pf-method-section" id="bound">
          <p className="pf-method-kicker">{copy.boundKicker}</p>
          <h2>{copy.boundTitle}</h2>
          <p className="pf-method-lead">{copy.boundLead}</p>
          <ul className="pf-method-bound">
            {copy.boundItems.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>

        <section className="pf-method-close">
          <div>
            <h2>{copy.closeTitle}</h2>
            <p>{copy.closeBody}</p>
          </div>
          <div className="pf-method-cta">
            <MethodCta href={METHOD_START_URL} className="pf-method-btn is-lime is-lg">
              {copy.startCta}
              <ArrowRight size={16} strokeWidth={2.2} aria-hidden />
            </MethodCta>
            <MethodCta href={METHOD_GEO_URL} className="pf-method-btn is-ghost is-lg">
              {copy.geoCta}
              <ArrowUpRight size={16} strokeWidth={2.2} aria-hidden />
            </MethodCta>
          </div>
        </section>
      </main>

      <footer className="pf-method-foot">
        <div className="pf-method-foot-inner">
          <p className="pf-method-copy">
            © {new Date().getFullYear()} {copy.footCopy}
          </p>
          <p>{copy.footAbout}</p>
          <p>{copy.footLegal}</p>
        </div>
      </footer>
    </div>
  )
}
