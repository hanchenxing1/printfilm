/** 大纲页：剧本按场次解析展示 / 分段编辑 / 弹窗预览 */
import { useMemo, useState } from 'react'
import { Pencil } from 'lucide-react'
import Modal from '../../components/ui/Modal'

export type OutlineSceneBlock = {
  /** 原始整段（含场头行），写回时原样拼接 */
  raw: string
  label: string
  title: string
  body: string
}

export type ScriptLineKind = 'meta' | 'action' | 'dialogue' | 'empty' | 'other'

export type ParsedScriptLine = {
  kind: ScriptLineKind
  text: string
  speaker?: string
  paren?: string
  dialogue?: string
}

/** 解析后单场统计：估时 / 对白 / 动作 / 出场 / 内外景 */
export type OutlineSceneStats = {
  estimatedSec: number
  dialogueCount: number
  actionCount: number
  cast: string[]
  location: string
}

/** 已进分镜时的镜头合计（优先于文本估算） */
export type OutlineShotDurationStats = {
  fragmentCount: number
  totalSec: number
}

const SPEAKER_COLORS = ['#059669', '#dc2626', '#ea580c', '#2563eb', '#7c3aed', '#db2777']
const SCENE_DURATION_MIN = 4
const SCENE_DURATION_MAX = 120
/** 与后端 build_fragments 行时长 clamp / 打包上限对齐 */
const LINE_DURATION_MIN = 3
const LINE_DURATION_MAX = 15
const FRAGMENT_SOFT_MAX = 15
const FRAGMENT_TOTAL_MAX = 15

// 角色名稳定配色
export function speakerColor(name: string): string {
  let h = 0
  for (let i = 0; i < name.length; i += 1) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return SPEAKER_COLORS[h % SPEAKER_COLORS.length]
}

// 从拍摄剧本正文拆出场次块
export function parseOutlineSceneBlocks(text: string): OutlineSceneBlock[] {
  const raw = (text || '').trim()
  if (!raw) return []
  const parts = raw.split(/(?=^#{1,3}\s*场)/m).map((p) => p.trim()).filter(Boolean)
  if (parts.length <= 1 && !/^#{1,3}\s*场/.test(raw)) {
    return [{ raw, label: '全文', title: '', body: raw }]
  }
  return parts.map((part, index) => {
    const lines = part.split(/\r?\n/)
    const head = (lines[0] || '').replace(/^#+\s*/, '').trim()
    const labelMatch = head.match(/^场\s*([^\s：:]+)/)
    const label = labelMatch ? `场 ${labelMatch[1]}` : `场 ${index + 1}`
    const title = head.replace(/^场\s*[^\s：:]+[：:\s]*/, '').trim()
    const body = lines.slice(1).join('\n').trim()
    return { raw: part, label, title, body }
  })
}

// 场次块拼回完整正文
export function joinOutlineSceneBlocks(blocks: OutlineSceneBlock[]): string {
  return blocks.map((b) => b.raw.trim()).filter(Boolean).join('\n\n')
}

// 解析单行：动作 / 对白 / 元信息
export function parseScriptLine(line: string): ParsedScriptLine {
  const text = line ?? ''
  const trimmed = text.trim()
  if (!trimmed) return { kind: 'empty', text }
  if (
    /^(出场人物|时间|地点|内外景)/.test(trimmed) ||
    /^[日夜早晚晨黄昏傍晚凌晨清晨午晚]\s*[内外]/.test(trimmed)
  ) {
    return { kind: 'meta', text: trimmed }
  }
  if (/^[△▲■□●○]/.test(trimmed) || trimmed.startsWith('△')) {
    return { kind: 'action', text: trimmed }
  }
  if (/^【/.test(trimmed)) {
    return { kind: 'action', text: trimmed }
  }
  const dlg = trimmed.match(/^([^：:(（]{1,20})\s*(?:[（(]([^)）]*)[)）])?\s*[：:]\s*(.*)$/)
  if (dlg) {
    return {
      kind: 'dialogue',
      text: trimmed,
      speaker: dlg[1].trim(),
      paren: (dlg[2] || '').trim() || undefined,
      dialogue: (dlg[3] || '').trim(),
    }
  }
  return { kind: 'other', text: trimmed }
}

function compactLen(text: string): number {
  return (text || '').replace(/\s+/g, '').length
}

/** 单行粗估秒数（对齐后端 build_fragments 量级，供大纲预览） */
function estimateLineSec(line: ParsedScriptLine): number {
  if (line.kind === 'empty' || line.kind === 'meta') return 0
  if (line.kind === 'action') {
    const t = line.text.trim()
    if (t.startsWith('【空镜')) return 4
    if (t.startsWith('△') || /^[△▲]/.test(t)) return 2
    return Math.min(10, Math.max(2, Math.floor(compactLen(t) / 12)))
  }
  if (line.kind === 'dialogue') {
    const body = `${line.paren || ''}${line.dialogue || line.text}`
    return Math.min(12, Math.max(3, Math.floor(compactLen(body) / 10)))
  }
  return Math.min(10, Math.max(2, Math.floor(compactLen(line.text) / 12)))
}

function clampLineDuration(sec: number): number {
  if (sec <= 0) return 0
  return Math.min(LINE_DURATION_MAX, Math.max(LINE_DURATION_MIN, sec))
}

/** 按分镜打包规则汇总时长（避免「逐行相加」与真实镜数脱节） */
function packEstimatedSec(lineSecs: number[]): number {
  let total = 0
  let used = 0
  for (const raw of lineSecs) {
    const block = clampLineDuration(raw)
    if (block <= 0) continue
    if (used > 0 && used >= FRAGMENT_SOFT_MAX && used + block > FRAGMENT_SOFT_MAX) {
      total += used
      used = 0
    }
    if (used > 0 && used + block > FRAGMENT_TOTAL_MAX) {
      total += used
      used = 0
    }
    let take = block
    if (take > FRAGMENT_TOTAL_MAX) take = FRAGMENT_TOTAL_MAX
    if (used + take > FRAGMENT_TOTAL_MAX) take = FRAGMENT_TOTAL_MAX - used
    if (take <= 0) {
      total += used
      used = 0
      take = Math.min(block, FRAGMENT_TOTAL_MAX)
    }
    used += take
  }
  if (used > 0) total += used
  return total
}

function parseCastNames(raw: string): string[] {
  return raw
    .split(/[、,，/／|｜]+/)
    .map((n) => n.trim())
    .filter(Boolean)
}

/** 统计一场：估时、对白/动作数、出场人物、内外景 */
export function summarizeOutlineScene(body: string): OutlineSceneStats {
  const lines = (body || '').split(/\r?\n/).map((line) => parseScriptLine(line))
  const lineSecs: number[] = []
  let dialogueCount = 0
  let actionCount = 0
  let cast: string[] = []
  let location = ''

  for (const line of lines) {
    lineSecs.push(estimateLineSec(line))
    if (line.kind === 'dialogue') dialogueCount += 1
    if (line.kind === 'action') actionCount += 1
    if (line.kind === 'meta') {
      const castMatch = line.text.match(/^出场人物[：:]\s*(.+)$/)
      if (castMatch) cast = parseCastNames(castMatch[1])
      const locMatch = line.text.match(
        /^(?:日|夜|晨|黄昏|傍晚|凌晨|清晨|午|晚)?\s*(?:内|外|内外)\s+(.+)$/,
      )
      if (locMatch && !location) location = locMatch[1].split(/[／/]/)[0].trim()
      else if (/^[日夜早晚]/.test(line.text) && !location) location = line.text
    }
  }

  let estimatedSec = packEstimatedSec(lineSecs)
  if (estimatedSec > 0) {
    estimatedSec = Math.min(SCENE_DURATION_MAX, Math.max(SCENE_DURATION_MIN, estimatedSec))
  }

  return { estimatedSec, dialogueCount, actionCount, cast, location }
}

function formatClockDuration(sec: number): string {
  if (sec <= 0) return '—'
  if (sec < 60) return `${sec}s`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return s ? `${m}分${s}秒` : `${m}分钟`
}

function formatEstimateDuration(sec: number): string {
  if (sec <= 0) return '约 —'
  return `约 ${formatClockDuration(sec)}`
}

// 渲染解析后的剧本行
function ScriptLines({ text }: { text: string }) {
  const lines = useMemo(
    () => text.split(/\r?\n/).map((line) => parseScriptLine(line)),
    [text],
  )
  return (
    <div className="drama-outline-script-lines">
      {lines.map((line, i) => {
        if (line.kind === 'empty') return <div key={i} className="drama-outline-script-gap" />
        if (line.kind === 'meta') {
          return (
            <p key={i} className="drama-outline-script-meta">
              {line.text}
            </p>
          )
        }
        if (line.kind === 'action') {
          return (
            <p key={i} className="drama-outline-script-action">
              {line.text}
            </p>
          )
        }
        if (line.kind === 'dialogue' && line.speaker) {
          return (
            <p key={i} className="drama-outline-script-dialogue">
              <span className="drama-outline-script-speaker" style={{ color: speakerColor(line.speaker) }}>
                {line.speaker}
                {line.paren ? `（${line.paren}）` : ''}
              </span>
              <span className="drama-outline-script-colon">：</span>
              <span>{line.dialogue}</span>
            </p>
          )
        }
        return (
          <p key={i} className="drama-outline-script-other">
            {line.text}
          </p>
        )
      })}
    </div>
  )
}

/** 场次信息条：对白 / 动作 / 内外景 / 出场 */
function SceneStatsBar({ stats }: { stats: OutlineSceneStats }) {
  const items: string[] = []
  if (stats.dialogueCount > 0) items.push(`${stats.dialogueCount} 句对白`)
  if (stats.actionCount > 0) items.push(`${stats.actionCount} 段动作`)
  if (stats.location) items.push(stats.location)
  if (stats.cast.length) items.push(stats.cast.slice(0, 6).join('、'))
  if (!items.length) return null
  return (
    <div className="drama-outline-scene-stats" aria-label="本场解析信息">
      {items.map((item) => (
        <span key={item} className="drama-outline-scene-stat">
          {item}
        </span>
      ))}
    </div>
  )
}

type OutlineScriptPreviewProps = {
  text: string
  empty: string
  busy?: boolean
  /** 已切分分镜时优先展示镜头合计时长 */
  shotStats?: OutlineShotDurationStats | null
  /** 分段保存：返回更新后的完整 body */
  onSaveScenes?: (nextBody: string) => Promise<void> | void
}

// 场次卡片列表 + 分段编辑
export function OutlineScriptPreview({
  text,
  empty,
  busy,
  shotStats,
  onSaveScenes,
}: OutlineScriptPreviewProps) {
  const blocks = useMemo(() => parseOutlineSceneBlocks(text), [text])
  const blockStats = useMemo(
    () => blocks.map((b) => summarizeOutlineScene(b.body)),
    [blocks],
  )
  const estimateTotalSec = useMemo(
    () => blockStats.reduce((sum, s) => sum + (s.estimatedSec || 0), 0),
    [blockStats],
  )
  const hasShotDuration = Boolean(shotStats && shotStats.fragmentCount > 0 && shotStats.totalSec > 0)
  const displayTotalSec = hasShotDuration ? shotStats!.totalSec : estimateTotalSec
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)

  function startEdit(index: number) {
    setEditingIndex(index)
    setDraft(blocks[index]?.raw || '')
  }

  async function saveEdit() {
    if (editingIndex == null || !onSaveScenes) return
    setSaving(true)
    try {
      const next = blocks.map((b, i) =>
        i === editingIndex ? { ...b, raw: draft.trim() } : b,
      )
      await onSaveScenes(joinOutlineSceneBlocks(next))
      setEditingIndex(null)
    } finally {
      setSaving(false)
    }
  }

  if (!text.trim()) {
    return <p className="drama-outline-section-empty">{empty}</p>
  }

  const summaryBar =
    blocks.length > 0 ? (
      <div className="drama-outline-script-summary">
        <span>{blocks[0].label === '全文' ? '1 段' : `${blocks.length} 场`}</span>
        {hasShotDuration ? (
          <span>
            {shotStats!.fragmentCount} 镜 · 合计 {formatClockDuration(displayTotalSec)}
          </span>
        ) : displayTotalSec > 0 ? (
          <span>合计 {formatClockDuration(displayTotalSec)}</span>
        ) : null}
        <span className="drama-outline-script-summary-hint">
          {hasShotDuration
            ? '时长取自已切分镜头'
            : '时长为解析估算，进分镜后以镜头为准'}
        </span>
      </div>
    ) : null

  if (blocks.length === 1 && blocks[0].label === '全文') {
    return (
      <div className="drama-outline-scene">
        {summaryBar}
        <div className="drama-outline-scene-toolbar">
          {onSaveScenes ? (
            <button
              type="button"
              className="drama-outline-text-btn"
              disabled={busy || saving}
              onClick={() => startEdit(0)}
            >
              <Pencil size={13} />
              编辑本段
            </button>
          ) : null}
        </div>
        {editingIndex === 0 ? (
          <SceneEditBox
            draft={draft}
            saving={saving || Boolean(busy)}
            onChange={setDraft}
            onCancel={() => setEditingIndex(null)}
            onSave={() => void saveEdit()}
          />
        ) : (
          <>
            <SceneStatsBar stats={blockStats[0]} />
            <ScriptLines text={blocks[0].body} />
          </>
        )}
      </div>
    )
  }

  return (
    <div className="drama-outline-scenes">
      {summaryBar}
      {blocks.map((block, i) => (
        <article key={`${block.label}-${i}`} className="drama-outline-scene">
          <header className="drama-outline-scene-head">
            <span className="drama-outline-scene-badge">{block.label}</span>
            {block.title ? <strong>{block.title}</strong> : null}
            {blockStats[i]?.estimatedSec && !hasShotDuration ? (
              <span className="drama-outline-scene-duration">
                {formatEstimateDuration(blockStats[i].estimatedSec)}
              </span>
            ) : null}
            {onSaveScenes ? (
              <button
                type="button"
                className="drama-outline-text-btn drama-outline-scene-edit"
                disabled={busy || saving}
                onClick={() => startEdit(i)}
              >
                <Pencil size={13} />
                编辑本场
              </button>
            ) : null}
          </header>
          {editingIndex === i ? (
            <SceneEditBox
              draft={draft}
              saving={saving || Boolean(busy)}
              onChange={setDraft}
              onCancel={() => setEditingIndex(null)}
              onSave={() => void saveEdit()}
            />
          ) : (
            <>
              <SceneStatsBar stats={blockStats[i]} />
              <ScriptLines text={block.body} />
            </>
          )}
        </article>
      ))}
    </div>
  )
}

function SceneEditBox({
  draft,
  saving,
  onChange,
  onCancel,
  onSave,
}: {
  draft: string
  saving: boolean
  onChange: (v: string) => void
  onCancel: () => void
  onSave: () => void
}) {
  return (
    <div className="drama-outline-scene-edit-box">
      <textarea
        className="drama-ep-section-textarea"
        rows={12}
        value={draft}
        onChange={(e) => onChange(e.target.value)}
        disabled={saving}
      />
      <div className="drama-ep-section-edit-actions">
        <button type="button" className="drama-btn-ghost" disabled={saving} onClick={onCancel}>
          取消
        </button>
        <button type="button" className="drama-btn-primary" disabled={saving} onClick={onSave}>
          {saving ? '保存中…' : '保存本段'}
        </button>
      </div>
    </div>
  )
}

/** 仅弹窗解析预览 */
export function OutlineScriptParseModal({
  open,
  onClose,
  title,
  text,
}: {
  open: boolean
  onClose: () => void
  title: string
  text: string
}) {
  return (
    <Modal open={open} onClose={onClose} title={title} size="xl" className="drama-outline-script-modal">
      <div className="drama-outline-script-modal-body">
        <OutlineScriptPreview text={text} empty="暂无剧本内容" />
      </div>
    </Modal>
  )
}
