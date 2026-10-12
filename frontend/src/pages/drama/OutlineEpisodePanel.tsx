/** 剧情大纲：左栏分集目录 + 右栏本集创意/摘要/剧本（对齐截图样式） */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  FileText,
  Lightbulb,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Maximize2,
  Pencil,
} from 'lucide-react'
import { dramaApi, resolveDramaMediaUrl, type DramaEpisode, type DramaEpisodeBody, type DramaProject, type DramaScript } from '../../api/drama'
import { FragmentPlanSkillModal } from '../../components/drama/FragmentPlanSkillModal'
import { dialog } from '../../lib/dialog'
import {
  buildEpisodeContentUpdate,
  buildOutlineDirectory,
  episodeBodyCharLen,
  isSubstantialEpisodeBody,
  isSubstantialEpisodeCreative,
  mergeDirectoryEpisodeBodies,
  MIN_EPISODE_BODY_CHARS,
  MIN_EPISODE_CREATIVE_CHARS,
  parseEpisodeBodies,
} from './dramaWorkspaceUtils'
import { sumFragmentContentDuration } from './dramaEpisodeEditUtils'
import { OutlineScriptParseModal, OutlineScriptPreview } from './outlineScriptPreview'

type SectionKey = 'creative' | 'summary' | 'body'

/** 分集目录用的镜头合计文案 */
function formatOutlineShotDuration(sec: number): string {
  if (sec <= 0) return '—'
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return s ? `${m}分${s}秒` : `${m}分钟`
}

type OutlineEpisodePanelProps = {
  projectId: number
  script: DramaScript | null
  episodeCount: number
  summaryReady: boolean
  episodeGenerating: boolean
  imageStyleLabel?: string
  storyType?: string
  onScriptChange: (script: DramaScript) => void
  onProjectChange: (project: DramaProject) => void
  onError: (msg: string) => void
  onOpenEpisodes: () => void
  children?: (parts: { directory: ReactNode; bodies: ReactNode }) => ReactNode
}

type SectionCardProps = {
  sectionKey: SectionKey
  icon: ReactNode
  title: string
  subtitle: string
  text: string
  editing: boolean
  draft: string
  open: boolean
  busy: boolean
  /** 禁用「生成」按钮；其他集生成中时仍可编辑本集 */
  generateBusy?: boolean
  placeholder: string
  regenerateLabel: string
  onToggle: () => void
  onEdit: () => void
  onCancel: () => void
  onSave: () => void
  onDraftChange: (v: string) => void
  onRegenerate: () => void
  onCopy: () => void
  /** 剧本区：解析预览 + 分段编辑 */
  scriptPreview?: ReactNode
}

// 分区卡片：图标标题 + 编辑/生成/复制/折叠
function SectionCard({
  sectionKey,
  icon,
  title,
  subtitle,
  text,
  editing,
  draft,
  open,
  busy,
  generateBusy,
  placeholder,
  regenerateLabel,
  onToggle,
  onEdit,
  onCancel,
  onSave,
  onDraftChange,
  onRegenerate,
  onCopy,
  scriptPreview,
}: SectionCardProps) {
  const genBusy = generateBusy ?? busy
  return (
    <article className={`drama-outline-section${open ? ' is-open' : ''}`}>
      <header className="drama-outline-section-head">
        <div className="drama-outline-section-title">
          <span className={`drama-outline-section-icon is-${sectionKey}`} aria-hidden>
            {icon}
          </span>
          <div>
            <strong>{title}</strong>
            <p>{subtitle}</p>
          </div>
        </div>
        <div className="drama-outline-section-actions">
          <button type="button" className="drama-outline-text-btn" disabled={busy} onClick={onEdit}>
            <Pencil size={14} strokeWidth={2} />
            编辑
          </button>
          <button type="button" className="drama-outline-text-btn" disabled={genBusy} onClick={onRegenerate}>
            <RefreshCw size={14} strokeWidth={2} />
            {regenerateLabel}
          </button>
          <button type="button" className="drama-outline-text-btn" onClick={onCopy}>
            <Copy size={14} strokeWidth={2} />
            复制
          </button>
          <button
            type="button"
            className="drama-outline-text-btn drama-outline-text-btn-icon"
            onClick={onToggle}
            aria-label={sectionKey === 'body' ? '弹窗解析' : open ? '收起' : '展开'}
          >
            {sectionKey === 'body' ? (
              <Maximize2 size={14} strokeWidth={2} />
            ) : open ? (
              <ChevronUp size={14} strokeWidth={2} />
            ) : (
              <ChevronDown size={14} strokeWidth={2} />
            )}
            {sectionKey === 'body' ? '解析预览' : open ? '收起' : '展开'}
          </button>
        </div>
      </header>
      {open ? (
        <div className="drama-outline-section-body">
          {editing ? (
            <>
              <textarea
                className="drama-ep-section-textarea"
                value={draft}
                onChange={(e) => onDraftChange(e.target.value)}
                rows={sectionKey === 'body' ? 14 : 8}
                placeholder={placeholder}
                disabled={busy}
              />
              <div className="drama-ep-section-edit-actions">
                <button type="button" className="drama-btn-ghost" disabled={busy} onClick={onCancel}>
                  取消
                </button>
                <button type="button" className="drama-btn-primary" disabled={busy} onClick={onSave}>
                  保存
                </button>
              </div>
            </>
          ) : scriptPreview ? (
            scriptPreview
          ) : (
            <p className="drama-pre drama-outline-section-text">{text.trim() || placeholder}</p>
          )}
        </div>
      ) : null}
    </article>
  )
}
// 分集目录 + 本集三卡片
export function OutlineEpisodePanel({
  projectId,
  script,
  episodeCount,
  summaryReady,
  episodeGenerating,
  imageStyleLabel,
  storyType,
  onScriptChange,
  onProjectChange,
  onError,
  onOpenEpisodes,
  children,
}: OutlineEpisodePanelProps) {
  const navigate = useNavigate()
  const [activeEpisodeNumber, setActiveEpisodeNumber] = useState(1)
  const [openSections, setOpenSections] = useState<Set<SectionKey>>(
    () => new Set(['creative', 'summary', 'body']),
  )
  const [editingSection, setEditingSection] = useState<SectionKey | null>(null)
  const [sectionDraft, setSectionDraft] = useState('')
  const [titleDraft, setTitleDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [adding, setAdding] = useState(false)
  const [generatingMode, setGeneratingMode] = useState<string | null>(null)
  const [generatingEpisodeNumber, setGeneratingEpisodeNumber] = useState<number | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [enterSkillOpen, setEnterSkillOpen] = useState(false)
  const [localError, setLocalError] = useState('')
  const [localNotice, setLocalNotice] = useState('')
  const [scriptModalOpen, setScriptModalOpen] = useState(false)
  const [episodeCovers, setEpisodeCovers] = useState<Record<number, string>>({})
  const [episodeShotStats, setEpisodeShotStats] = useState<
    Record<number, { fragmentCount: number; totalSec: number }>
  >({})

  const episodeBodies = parseEpisodeBodies(script)
  const directoryEpisodes = buildOutlineDirectory(episodeBodies, episodeCount)
  const displayEpisodes = mergeDirectoryEpisodeBodies(directoryEpisodes, episodeBodies)
  const selected =
    displayEpisodes.find((ep) => ep.episodeNumber === activeEpisodeNumber) || displayEpisodes[0] || null

  useEffect(() => {
    if (!selected) return
    if (!displayEpisodes.some((ep) => ep.episodeNumber === activeEpisodeNumber) && displayEpisodes[0]) {
      setActiveEpisodeNumber(displayEpisodes[0].episodeNumber || 1)
    }
  }, [displayEpisodes, activeEpisodeNumber, selected])

  useEffect(() => {
    setEditingSection(null)
    setSectionDraft('')
    setTitleDraft(selected?.title || '')
    setLocalError('')
    setLocalNotice('')
    setScriptModalOpen(false)
  }, [selected?.episodeNumber])

  // 拉取已切分分集，用首镜封面/成片作目录缩略图
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        let rows: DramaEpisode[] = await dramaApi.listEpisodes(projectId)
        if (!rows.length) {
          try {
            rows = await dramaApi.seedEpisodes(projectId, false)
          } catch {
            rows = []
          }
        }
        if (cancelled) return
        const map: Record<number, string> = {}
        const shotMap: Record<number, { fragmentCount: number; totalSec: number }> = {}
        for (const ep of rows) {
          const epNo = Number(ep.params?.episodeNumber) || 0
          if (!epNo) continue
          const frags = [...(ep.fragments || [])].sort(
            (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0),
          )
          if (frags.length > 0) {
            const totalSec = frags.reduce((sum, f) => {
              const stored = Number(f.duration_sec)
              if (Number.isFinite(stored) && stored > 0) return sum + Math.round(stored)
              return sum + sumFragmentContentDuration(f.content || '')
            }, 0)
            shotMap[epNo] = { fragmentCount: frags.length, totalSec }
          }
          const first = frags.find((f) => (f.cover || '').trim() || (f.video || '').trim())
          if (!first) continue
          const raw = (first.cover || first.video || '').trim()
          if (raw) map[epNo] = resolveDramaMediaUrl(raw)
        }
        setEpisodeCovers(map)
        setEpisodeShotStats(shotMap)
      } catch {
        if (!cancelled) {
          setEpisodeCovers({})
          setEpisodeShotStats({})
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [projectId, script?.id, episodeCount])

  const selectedGenerating =
    Boolean(generatingMode) && generatingEpisodeNumber === (selected?.episodeNumber ?? null)
  const anyEpisodeGenerating = Boolean(generatingMode)
  const effectiveCreative =
    editingSection === 'creative' ? sectionDraft : selected?.creative || ''
  const effectiveSummary =
    editingSection === 'summary' ? sectionDraft : selected?.summary || ''
  const canGenerateBody =
    episodeBodyCharLen(effectiveCreative) >= 10 || episodeBodyCharLen(effectiveSummary) >= 40
  const canAdd =
    summaryReady &&
    !episodeGenerating &&
    !adding &&
    !anyEpisodeGenerating &&
    !confirming &&
    directoryEpisodes.length < 120

  // 仅锁正在生成的那一集；其他集可浏览/编辑（单集任务全局串行，故禁止并行再点生成）
  const busy = episodeGenerating || selectedGenerating || confirming || saving || adding
  const generateBusy = episodeGenerating || anyEpisodeGenerating || confirming || saving || adding

  async function pollOptimize(tokenEpisode: number) {
    const started = Date.now()
    let lastErr: Error | null = null
    while (Date.now() - started < 8 * 60 * 1000) {
      await new Promise((r) => setTimeout(r, 2000))
      try {
        const cur = await dramaApi.getScript(projectId)
        onScriptChange(cur)
        lastErr = null
        const st = String((cur.params || {}).episode_optimize_status || '')
        const num = Number((cur.params || {}).episode_optimize_number || 0)
        if (num === tokenEpisode && st === 'completed') return cur
        if (num === tokenEpisode && st === 'failed') {
          throw new Error(String((cur.params || {}).episode_optimize_error || '生成失败'))
        }
        if (st !== 'generating') return cur
      } catch (err) {
        // 瞬时网络失败不中断轮询，避免 Failed to fetch 把界面卡在「生成中」
        lastErr = err instanceof Error ? err : new Error('轮询失败')
      }
    }
    throw lastErr || new Error('生成超时，请稍后刷新')
  }

  async function saveBodies(nextBodies: DramaEpisodeBody[]) {
    const updated = await dramaApi.updateScript(projectId, {
      episode_content: buildEpisodeContentUpdate(script, nextBodies),
    })
    onScriptChange(updated)
    return updated
  }

  async function handleAddEpisode() {
    if (!canAdd) return
    setAdding(true)
    setLocalError('')
    try {
      const res = await dramaApi.addEpisode({ project_id: projectId })
      onScriptChange(res.script)
      const p = await dramaApi.getProject(projectId)
      onProjectChange(p)
      setActiveEpisodeNumber(res.episode_number)
      setEditingSection('creative')
      setSectionDraft('')
      onOpenEpisodes()
    } catch (err) {
      const msg = err instanceof Error ? err.message : '加集失败'
      setLocalError(msg)
      onError(msg)
    } finally {
      setAdding(false)
    }
  }

  async function handleSaveSection(section: SectionKey) {
    if (!selected?.episodeNumber) return
    setSaving(true)
    setLocalError('')
    try {
      const num = selected.episodeNumber
      const next = displayEpisodes.map((ep) => {
        if (ep.episodeNumber !== num) return ep
        if (section === 'creative') return { ...ep, creative: sectionDraft, title: titleDraft || ep.title }
        if (section === 'summary') return { ...ep, summary: sectionDraft, title: titleDraft || ep.title }
        return { ...ep, body: sectionDraft, title: titleDraft || ep.title }
      })
      await saveBodies(next)
      setEditingSection(null)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '保存失败'
      setLocalError(msg)
      onError(msg)
    } finally {
      setSaving(false)
    }
  }

  async function handleGenerate(mode: 'summary' | 'body' | 'full' | 'brief') {
    if (!selected?.episodeNumber) return
    const creative = editingSection === 'creative' ? sectionDraft : selected.creative || ''
    const summary = editingSection === 'summary' ? sectionDraft : selected.summary || ''
    if ((mode === 'summary' || mode === 'full') && !isSubstantialEpisodeCreative(creative)) {
      setLocalError(`本集原始创意至少 ${MIN_EPISODE_CREATIVE_CHARS} 字`)
      return
    }
    // 与后端 run_episode_body_from_brief 一致：创意≥10 或摘要≥40
    if (mode === 'body' && episodeBodyCharLen(creative) < 10 && episodeBodyCharLen(summary) < 40) {
      setLocalError('请先填写本集创意或摘要，再生成剧本正文')
      return
    }
    if (mode === 'brief' && !isSubstantialEpisodeBody(selected.body)) {
      setLocalError(`剧本内容需满 ${MIN_EPISODE_BODY_CHARS} 字后再补齐创意与摘要`)
      return
    }
    if (mode === 'full') {
      const ok = await dialog.confirm({
        title: '重新生成整集',
        message:
          '将按本集创意重写摘要与剧本正文。若本集已进入分镜，之后重新分镜会覆盖并清空已生成镜头。是否继续？',
        confirmText: '重新生成',
        tone: 'danger',
      })
      if (!ok) return
    }
    const targetEpisode = selected.episodeNumber
    setGeneratingMode(mode)
    setGeneratingEpisodeNumber(targetEpisode)
    setLocalError('')
    setLocalNotice('')
    try {
      // 生成前落盘创意/摘要/标题草稿，避免 body 模式只读库内空字段
      if (
        editingSection === 'creative' ||
        editingSection === 'summary' ||
        titleDraft !== selected.title
      ) {
        const next = displayEpisodes.map((ep) =>
          ep.episodeNumber === targetEpisode
            ? {
                ...ep,
                creative: editingSection === 'creative' ? sectionDraft : ep.creative,
                summary: editingSection === 'summary' ? sectionDraft : ep.summary,
                title: titleDraft || ep.title,
              }
            : ep,
        )
        await saveBodies(next)
        setEditingSection(null)
      }
      await dramaApi.episodeScript({
        project_id: projectId,
        episode_number: targetEpisode,
        generate_mode: mode,
        creative: creative || undefined,
        title: titleDraft || selected.title,
      })
      const cur = await pollOptimize(targetEpisode)
      const created = Number((cur.params || {}).episode_optimize_assets_created || 0)
      if ((mode === 'body' || mode === 'full') && created > 0) {
        setLocalNotice(`新建 ${created} 个角色/场景，已进资产库`)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '生成失败'
      setLocalError(msg)
      onError(msg)
    } finally {
      setGeneratingMode(null)
      setGeneratingEpisodeNumber(null)
    }
  }

  async function handleConfirmEnter() {
    if (!selected?.episodeNumber) return
    if (!isSubstantialEpisodeBody(selected.body)) {
      setLocalError(`剧本内容需满 ${MIN_EPISODE_BODY_CHARS} 字后再进入分镜`)
      return
    }
    setLocalError('')
    setConfirming(true)
    try {
      // 本集已有分镜：直接进入，不再弹 Skill / 重切
      const rows = await dramaApi.listEpisodes(projectId)
      const existing = rows.find(
        (ep) => Number(ep.params?.episodeNumber) === Number(selected.episodeNumber),
      )
      if (existing && (existing.fragments || []).length > 0) {
        navigate(`/drama/projects/${projectId}/episodes/${existing.id}`)
        return
      }
      setEnterSkillOpen(true)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '进入分镜失败'
      setLocalError(msg)
      onError(msg)
    } finally {
      setConfirming(false)
    }
  }

  // 首次进入：确认剧本 + 按所选 Skill 做 AI 分镜
  async function startEnterWithSkills(skillIds: number[]) {
    if (!selected?.episodeNumber) return
    setEnterSkillOpen(false)
    setConfirming(true)
    setLocalError('')
    try {
      const res = await dramaApi.confirmEpisodeFromScript({
        project_id: projectId,
        episode_number: selected.episodeNumber,
      })
      const episodeId = res.episode.id
      try {
        await dramaApi.planEpisodeFragments(episodeId, {
          force: true,
          fallback_rules: true,
          skill_ids: skillIds,
        })
      } catch (planErr) {
        onError(planErr instanceof Error ? planErr.message : 'AI 分镜入队失败，已进入规则分镜')
      }
      navigate(`/drama/projects/${projectId}/episodes/${episodeId}`)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '进入分镜失败'
      setLocalError(msg)
      onError(msg)
    } finally {
      setConfirming(false)
    }
  }

  async function handleSaveScenes(nextBody: string) {
    if (!selected?.episodeNumber) return
    setSaving(true)
    setLocalError('')
    try {
      const num = selected.episodeNumber
      const next = displayEpisodes.map((ep) =>
        ep.episodeNumber === num ? { ...ep, body: nextBody, title: titleDraft || ep.title } : ep,
      )
      await saveBodies(next)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '保存失败'
      setLocalError(msg)
      onError(msg)
      throw err
    } finally {
      setSaving(false)
    }
  }

  function toggleSection(key: SectionKey) {
    if (key === 'body') {
      setScriptModalOpen(true)
      setOpenSections((prev) => new Set(prev).add('body'))
      return
    }
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function startEdit(section: SectionKey) {
    if (!selected) return
    setEditingSection(section)
    setSectionDraft(
      section === 'creative'
        ? selected.creative || ''
        : section === 'summary'
          ? selected.summary || ''
          : selected.body || '',
    )
    setOpenSections((prev) => new Set(prev).add(section))
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text || '')
    } catch {
      setLocalError('复制失败')
    }
  }

  const metaTags = useMemo(() => {
    const tags: string[] = []
    if (storyType) tags.push(storyType)
    if (selected?.origin === 'manual') tags.push('手动加集')
    else if (selected?.body) tags.push('自动生成')
    return tags
  }, [storyType, selected])

  const bodyReady = isSubstantialEpisodeBody(selected?.body)
  const charHint = selected
    ? [
        selected.creative ? `创意 ${episodeBodyCharLen(selected.creative)} 字` : null,
        selected.summary ? `摘要 ${episodeBodyCharLen(selected.summary)} 字` : null,
        selected.body ? `剧本 ${episodeBodyCharLen(selected.body)} 字` : null,
      ]
        .filter(Boolean)
        .join(' · ')
    : ''

  const directory = (
    <aside className="drama-outline-sidebar">
      <div className="drama-outline-sidebar-head">
        <div>
          <h3>分集目录</h3>
          <p>共 {directoryEpisodes.length} 集</p>
        </div>
        {summaryReady ? (
          <button
            type="button"
            className="drama-outline-add-btn"
            disabled={!canAdd}
            onClick={() => void handleAddEpisode()}
          >
            <Plus size={14} strokeWidth={2.5} />
            {adding ? '添加中' : '加集'}
          </button>
        ) : null}
      </div>
      <ul className="drama-outline-ep-list">
        {directoryEpisodes.map((ep) => {
          const body = displayEpisodes.find((x) => x.episodeNumber === ep.episodeNumber)
          const ready = isSubstantialEpisodeBody(body?.body)
          const active = activeEpisodeNumber === ep.episodeNumber
          const shot = episodeShotStats[ep.episodeNumber || 0]
          const statusLabel = shot && shot.fragmentCount > 0 && shot.totalSec > 0
            ? `${shot.fragmentCount} 镜 · ${formatOutlineShotDuration(shot.totalSec)}`
            : ready
              ? '正文已就绪'
              : body?.creative
                ? '待生成剧本'
                : '待填写创意'
          return (
            <li key={ep.episodeNumber}>
              <button
                type="button"
                className={`drama-outline-ep-card${active ? ' is-active' : ''}`}
                onClick={() => {
                  onOpenEpisodes()
                  setActiveEpisodeNumber(ep.episodeNumber)
                }}
              >
                <span className="drama-outline-ep-thumb" aria-hidden>
                  {(() => {
                    const cover = episodeCovers[ep.episodeNumber || 0]
                    if (!cover) return ep.episodeNumber
                    if (/\.(mp4|webm|mov)(\?|$)/i.test(cover)) {
                      return <video src={cover} muted playsInline preload="metadata" />
                    }
                    return <img src={cover} alt="" />
                  })()}
                </span>
                <span className="drama-outline-ep-meta">
                  <strong>第 {ep.episodeNumber} 集</strong>
                  <small>{ep.title || '未命名'}</small>
                  <em className={shot && shot.fragmentCount > 0 ? 'is-shot' : undefined}>
                    {statusLabel}
                  </em>
                </span>
                <span className="drama-outline-ep-more" aria-hidden>
                  <MoreHorizontal size={16} />
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </aside>
  )

  const bodies = !selected ? (
    <div className="drama-outline-detail-empty">
      <p>{summaryReady ? '暂无分集，请点击「加集」或等待自动生成。' : '请先完成整剧创意与剧本摘要。'}</p>
    </div>
  ) : (
    <section className="drama-outline-detail">
      <header className="drama-outline-detail-head">
        <div className="drama-outline-detail-title">
          {editingSection ? (
            <input
              className="drama-title-input"
              value={titleDraft}
              onChange={(e) => setTitleDraft(e.target.value)}
              placeholder="集名"
            />
          ) : (
            <h2>
              第 {selected.episodeNumber} 集
              {selected.title ? `：${selected.title}` : ''}
            </h2>
          )}
          {imageStyleLabel ? <span className="drama-outline-style-badge">{imageStyleLabel}</span> : null}
          <div className="drama-outline-detail-meta">
            {charHint ? <span>{charHint}</span> : <span>尚未填写本集内容</span>}
            {metaTags.map((tag) => (
              <span key={tag} className="drama-outline-tag">
                {tag}
              </span>
            ))}
          </div>
        </div>
        <div className="drama-outline-detail-actions">
          <span className={`drama-outline-saved${bodyReady ? ' is-ready' : ''}`}>
            <Check size={14} strokeWidth={2.5} />
            {bodyReady ? '可进分镜' : saving ? '保存中' : '已同步'}
          </span>
          {bodyReady &&
          (!isSubstantialEpisodeCreative(selected.creative) ||
            episodeBodyCharLen(selected.summary) < 40) ? (
            <button
              type="button"
              className="drama-btn-ghost"
              disabled={generateBusy}
              onClick={() => void handleGenerate('brief')}
            >
              {selectedGenerating && generatingMode === 'brief' ? '补齐中…' : '补齐创意与摘要'}
            </button>
          ) : null}
          <button
            type="button"
            className="drama-outline-regen-btn"
            disabled={generateBusy || !isSubstantialEpisodeCreative(selected.creative)}
            onClick={() => void handleGenerate('full')}
          >
            <RefreshCw size={15} strokeWidth={2.25} />
            {selectedGenerating && generatingMode === 'full' ? '生成中…' : '重新生成整集'}
          </button>
          <button
            type="button"
            className="drama-btn-ghost"
            disabled={busy || !bodyReady}
            onClick={() => void handleConfirmEnter()}
          >
            {confirming ? '进入中…' : '进入分镜'}
          </button>
        </div>
      </header>

      {localError ? <p className="drama-error">{localError}</p> : null}
      {localNotice ? <p className="drama-outline-notice">{localNotice}</p> : null}
      {episodeGenerating ? <p className="drama-loader">全集剧本生成中，可先浏览已完成的集…</p> : null}
      {selectedGenerating ? (
        <p className="drama-loader">本集生成中（{generatingMode}）…</p>
      ) : anyEpisodeGenerating && generatingEpisodeNumber ? (
        <p className="drama-loader">
          第 {generatingEpisodeNumber} 集生成中，可先浏览/编辑本集（生成请等该集完成）
        </p>
      ) : null}

      <div className="drama-outline-sections">
        <SectionCard
          sectionKey="creative"
          icon={<Lightbulb size={18} strokeWidth={1.9} />}
          title="原始创意"
          subtitle="本集故事起点与核心冲突"
          text={selected.creative || ''}
          editing={editingSection === 'creative'}
          draft={sectionDraft}
          open={openSections.has('creative')}
          busy={busy}
          generateBusy={generateBusy}
          placeholder={`填写本集创意（至少 ${MIN_EPISODE_CREATIVE_CHARS} 字）`}
          regenerateLabel={
            selectedGenerating && generatingMode === 'brief'
              ? '补齐中…'
              : selectedGenerating && generatingMode === 'summary'
                ? '生成中…'
                : isSubstantialEpisodeCreative(selected.creative)
                  ? '生成摘要'
                  : '补齐创意与摘要'
          }
          onToggle={() => toggleSection('creative')}
          onEdit={() => startEdit('creative')}
          onCancel={() => setEditingSection(null)}
          onSave={() => void handleSaveSection('creative')}
          onDraftChange={setSectionDraft}
          onRegenerate={() =>
            void handleGenerate(
              isSubstantialEpisodeCreative(selected.creative) ? 'summary' : 'brief',
            )
          }
          onCopy={() => void copyText(selected.creative || '')}
        />
        <SectionCard
          sectionKey="summary"
          icon={<BookOpen size={18} strokeWidth={1.9} />}
          title="剧情摘要"
          subtitle="人物、冲突、转折与结尾钩子"
          text={selected.summary || ''}
          editing={editingSection === 'summary'}
          draft={sectionDraft}
          open={openSections.has('summary')}
          busy={busy}
          generateBusy={generateBusy}
          placeholder="本集剧情摘要"
          regenerateLabel={
            selectedGenerating && generatingMode === 'brief'
              ? '补齐中…'
              : selectedGenerating && generatingMode === 'summary'
                ? '生成中…'
                : isSubstantialEpisodeCreative(selected.creative)
                  ? '重新生成'
                  : '补齐创意与摘要'
          }
          onToggle={() => toggleSection('summary')}
          onEdit={() => startEdit('summary')}
          onCancel={() => setEditingSection(null)}
          onSave={() => void handleSaveSection('summary')}
          onDraftChange={setSectionDraft}
          onRegenerate={() =>
            void handleGenerate(
              isSubstantialEpisodeCreative(selected.creative) ? 'summary' : 'brief',
            )
          }
          onCopy={() => void copyText(selected.summary || '')}
        />
        <SectionCard
          sectionKey="body"
          icon={<FileText size={18} strokeWidth={1.9} />}
          title="剧本内容"
          subtitle="含对白与画面描述的拍摄正文（按场次解析，可分段编辑）"
          text={selected.body || ''}
          editing={editingSection === 'body'}
          draft={sectionDraft}
          open={openSections.has('body')}
          busy={busy}
          generateBusy={generateBusy || !canGenerateBody}
          placeholder={`拍摄剧本正文（进入分镜需满 ${MIN_EPISODE_BODY_CHARS} 字）`}
          regenerateLabel={selectedGenerating && generatingMode === 'body' ? '生成中…' : '生成剧本'}
          onToggle={() => toggleSection('body')}
          onEdit={() => startEdit('body')}
          onCancel={() => setEditingSection(null)}
          onSave={() => void handleSaveSection('body')}
          onDraftChange={setSectionDraft}
          onRegenerate={() => void handleGenerate('body')}
          onCopy={() => void copyText(selected.body || '')}
          scriptPreview={
            <OutlineScriptPreview
              text={selected.body || ''}
              empty={`拍摄剧本正文（进入分镜需满 ${MIN_EPISODE_BODY_CHARS} 字）`}
              busy={busy}
              shotStats={episodeShotStats[selected.episodeNumber || 0] || null}
              onSaveScenes={handleSaveScenes}
            />
          }
        />
      </div>
      <OutlineScriptParseModal
        open={scriptModalOpen}
        onClose={() => setScriptModalOpen(false)}
        title={`第 ${selected.episodeNumber} 集 · 剧本解析`}
        text={selected.body || ''}
      />
    </section>
  )

  if (children) {
    return (
      <>
        {children({ directory, bodies })}
        <FragmentPlanSkillModal
          open={enterSkillOpen}
          title="进入分镜"
          message="将确认本集剧本并切分分镜。可勾选本次使用的 Skill；确认后会覆盖该集已有分镜与已生成镜头（若有）。"
          confirmText={confirming ? '进入中…' : '开始分镜'}
          onCancel={() => {
            if (!confirming) setEnterSkillOpen(false)
          }}
          onConfirm={(skillIds) => void startEnterWithSkills(skillIds)}
        />
      </>
    )
  }
  return (
    <div className="drama-outline drama-outline-v2">
      {directory}
      <div className="drama-outline-main">{bodies}</div>
      <FragmentPlanSkillModal
        open={enterSkillOpen}
        title="进入分镜"
        message="将确认本集剧本并切分分镜。可勾选本次使用的 Skill；确认后会覆盖该集已有分镜与已生成镜头（若有）。"
        confirmText={confirming ? '进入中…' : '开始分镜'}
        onCancel={() => {
          if (!confirming) setEnterSkillOpen(false)
        }}
        onConfirm={(skillIds) => void startEnterWithSkills(skillIds)}
      />
    </div>
  )
}
