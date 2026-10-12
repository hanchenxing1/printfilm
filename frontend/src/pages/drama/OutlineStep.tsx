/** 剧情大纲步骤：自动摘要 + 分集剧本流水线 */
import { useEffect, useRef, useState } from 'react'
import {
  dramaApi,
  type DramaProject,
  type DramaScript,
} from '../../api/drama'
import { getImageStyleLabel, type ImageStyleId } from '../../lib/dramaImageStyles'
import {
  autoMissingEpisodeCount,
  getEpisodeContentStatus,
  getImageStyleId,
  getSummaryStatus,
  hasSubstantialEpisode,
  parseEpisodeBodies,
} from './dramaWorkspaceUtils'
import { dialog } from '../../lib/dialog'
import Modal from '../../components/ui/Modal'
import { DramaImageStyleModal } from './DramaImageStyleModal'
import { DramaProjectSettingsModal } from './DramaProjectSettingsModal'
import { OutlineEpisodePanel } from './OutlineEpisodePanel'

type MetaModalKey = 'source' | 'summary' | 'project'

export type OutlineStepProps = {
  projectId: number
  project: DramaProject
  onProjectChange: (p: DramaProject) => void
  /** 可选：大纲就绪回调（工作区已不再依赖「下一步」） */
  onOutlineReadyChange?: (ready: boolean) => void
  onError: (msg: string) => void
}

// 渲染剧情大纲步骤
export function OutlineStep({
  projectId,
  project,
  onProjectChange,
  onOutlineReadyChange,
  onError,
}: OutlineStepProps) {
  const notifyOutlineReady = (ready: boolean) => onOutlineReadyChange?.(ready)
  const [script, setScript] = useState<DramaScript | null>(project.script || null)
  const [metaModal, setMetaModal] = useState<MetaModalKey | null>(null)
  const [summaryGenerating, setSummaryGenerating] = useState(false)
  const [episodeGenerating, setEpisodeGenerating] = useState(false)
  const [summaryError, setSummaryError] = useState('')
  const [episodeError, setEpisodeError] = useState('')
  const [progress, setProgress] = useState({ done: 0, total: 0 })
  const [summaryEditing, setSummaryEditing] = useState(false)
  const [summaryDraft, setSummaryDraft] = useState<Record<string, unknown> | null>(null)
  const [summarySaving, setSummarySaving] = useState(false)
  const [sourceEditing, setSourceEditing] = useState(false)
  const [sourceDraft, setSourceDraft] = useState('')
  const [sourceSaving, setSourceSaving] = useState(false)
  const pipelineRef = useRef(0)

  const summary = (script?.summary || null) as Record<string, unknown> | null
  const summaryStatus = getSummaryStatus(script)
  const episodeStatus = getEpisodeContentStatus(script)
  const episodeCount =
    Number(
      summary?.episodeCount ||
        (script?.params || {}).episode_count ||
        project.params?.episode_count,
    ) || 0
  const imageStyleId = getImageStyleId(script, project)

  function openSourceModal() {
    setSourceEditing(false)
    setSourceDraft(script?.source || '')
    setMetaModal('source')
  }

  function openSummaryModal() {
    setSummaryEditing(false)
    setMetaModal('summary')
  }

  function closeMetaModal() {
    setMetaModal(null)
    setSourceEditing(false)
    setSummaryEditing(false)
  }

  // 轮询剧本直到条件满足（worker 异步任务）
  async function pollScriptUntil(
    predicate: (s: DramaScript) => boolean,
    runToken?: number,
  ): Promise<DramaScript | null> {
    const started = Date.now()
    while (Date.now() - started < 45 * 60 * 1000) {
      if (runToken !== undefined && runToken !== pipelineRef.current) return null
      const s = await dramaApi.getScript(projectId)
      setScript(s)
      const prog = (s.params || {}).episode_content_progress as
        | { done?: number; total?: number }
        | undefined
      if (prog && (prog.total || prog.done)) {
        setProgress({
          done: Number(prog.done) || 0,
          total: Number(prog.total) || 0,
        })
      }
      if (predicate(s)) return s
      await new Promise((r) => setTimeout(r, 2000))
    }
    throw new Error('等待生成超时，请刷新后重试')
  }

  // 入队并等待剧本摘要完成
  async function runSummary(runToken?: number) {
    setSummaryGenerating(true)
    setSummaryError('')
    try {
      const res = await dramaApi.scriptSummary({ project_id: projectId })
      setScript(res.script)
      const finished = await pollScriptUntil((s) => {
        const st = getSummaryStatus(s)
        return st === 'completed' || st === 'failed'
      }, runToken)
      if (!finished) return null
      if (getSummaryStatus(finished) === 'failed') {
        const msg =
          String((finished.params || {}).summary_error || '') || '剧本摘要生成失败'
        setSummaryError(msg)
        onError(msg)
        throw new Error(msg)
      }
      const p = await dramaApi.getProject(projectId)
      onProjectChange(p)
      return finished
    } catch (err) {
      const msg = err instanceof Error ? err.message : '剧本摘要生成失败'
      setSummaryError(msg)
      onError(msg)
      throw err
    } finally {
      setSummaryGenerating(false)
    }
  }

  // 入队并轮询分集剧本直到完成
  async function runEpisodeScripts(runToken?: number, force = false) {
    setEpisodeGenerating(true)
    setEpisodeError('')
    try {
      const res = await dramaApi.episodeScript({
        project_id: projectId,
        batch_size: 1,
        force,
      })
      setScript(res.script)
      setProgress({ done: res.total_generated, total: res.total_target })
      const finished = await pollScriptUntil((s) => {
        const st = getEpisodeContentStatus(s)
        return st === 'completed' || st === 'failed'
      }, runToken)
      if (!finished) return
      if (getEpisodeContentStatus(finished) === 'failed') {
        const msg =
          String((finished.params || {}).episode_content_error || '') ||
          '分集剧本生成失败'
        setEpisodeError(msg)
        onError(msg)
        notifyOutlineReady(false)
        return
      }
      notifyOutlineReady(true)
      const p = await dramaApi.getProject(projectId)
      onProjectChange(p)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '分集剧本生成失败'
      setEpisodeError(msg)
      onError(msg)
      notifyOutlineReady(false)
    } finally {
      setEpisodeGenerating(false)
    }
  }

  // 手动强制重写全部分集正文
  async function handleRegenerateEpisodes() {
    if (episodeGenerating) return
    const ok = await dialog.confirm({
      title: '重新生成分集剧本',
      message:
        '将清空当前分集正文并按最新剧本摘要重新生成全部集数，已有编辑将丢失。是否继续？',
      confirmText: '重新生成',
      tone: 'danger',
    })
    if (!ok) return
    notifyOutlineReady(false)
    await runEpisodeScripts(undefined, true)
  }

  // 挂载自动流水线：无摘要 → 摘要 → 分集（未满目标集数会续跑；已在 worker 中则只轮询）
  useEffect(() => {
    const token = ++pipelineRef.current
    async function pipeline() {
      let current = script
      const status = getSummaryStatus(current)
      if (!current?.summary && status !== 'completed') {
        try {
          if (status === 'generating') {
            setSummaryGenerating(true)
            current = await pollScriptUntil((s) => {
              const st = getSummaryStatus(s)
              return st === 'completed' || st === 'failed'
            }, token)
            setSummaryGenerating(false)
            if (!current || getSummaryStatus(current) === 'failed') {
              const msg =
                String((current?.params || {}).summary_error || '') || '剧本摘要生成失败'
              setSummaryError(msg)
              onError(msg)
              return
            }
          } else {
            current = await runSummary(token)
          }
        } catch {
          return
        }
        if (!current || token !== pipelineRef.current) return
      }
      const target =
        Number(
          (current?.summary as Record<string, unknown> | null)?.episodeCount ||
            (current?.params || {}).episode_count ||
            project.params?.episode_count,
        ) || 0
      const bodies = parseEpisodeBodies(current)
      const epStatus = getEpisodeContentStatus(current)
      const autoMissing = autoMissingEpisodeCount(bodies, target)
      const complete =
        epStatus !== 'failed' && autoMissing === 0 && hasSubstantialEpisode(bodies)
      if (complete) {
        notifyOutlineReady(true)
        return
      }
      if (current?.summary || getSummaryStatus(current) === 'completed') {
        if (epStatus === 'generating') {
          setEpisodeGenerating(true)
          const finished = await pollScriptUntil((s) => {
            const st = getEpisodeContentStatus(s)
            return st === 'completed' || st === 'failed'
          }, token)
          setEpisodeGenerating(false)
          if (!finished) return
          if (getEpisodeContentStatus(finished) === 'failed') {
            const msg =
              String((finished.params || {}).episode_content_error || '') ||
              '分集剧本生成失败'
            setEpisodeError(msg)
            onError(msg)
            notifyOutlineReady(false)
            return
          }
          notifyOutlineReady(true)
          const p = await dramaApi.getProject(projectId)
          onProjectChange(p)
          return
        }
        await runEpisodeScripts(token)
      }
    }
    void pipeline()
    return () => {
      pipelineRef.current += 1
      notifyOutlineReady(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  // 更新画面风格
  async function handleStyleChange(styleId: string) {
    try {
      const updated = await dramaApi.updateScript(projectId, {
        image_style_id: styleId || undefined,
      })
      setScript(updated)
      const p = await dramaApi.getProject(projectId)
      onProjectChange(p)
    } catch (err) {
      onError(err instanceof Error ? err.message : '风格更新失败')
    }
  }

  // 进入剧本摘要编辑
  function startSummaryEdit() {
    if (!summary) return
    setSummaryDraft(structuredClone(summary) as Record<string, unknown>)
    setSummaryEditing(true)
  }

  // 保存手动编辑的剧本摘要
  async function saveSummaryEdit() {
    if (!summaryDraft) return
    setSummarySaving(true)
    try {
      const updated = await dramaApi.updateScript(projectId, { summary: summaryDraft })
      setScript(updated)
      setSummaryEditing(false)
      setSummaryDraft(null)
      const p = await dramaApi.getProject(projectId)
      onProjectChange(p)
    } catch (err) {
      onError(err instanceof Error ? err.message : '摘要保存失败')
    } finally {
      setSummarySaving(false)
    }
  }

  const characters = Array.isArray(summary?.characters)
    ? (summary.characters as Array<Record<string, unknown>>)
    : []

  async function saveSourceEdit() {
    setSourceSaving(true)
    try {
      const updated = await dramaApi.updateScript(projectId, { source: sourceDraft })
      setScript(updated)
      setSourceEditing(false)
    } catch (err) {
      onError(err instanceof Error ? err.message : '创意保存失败')
    } finally {
      setSourceSaving(false)
    }
  }

  return (
    <div className="drama-outline-page">
      <div className="drama-outline-toolbar">
        <div className="drama-outline-toolbar-left">
          <DramaImageStyleModal
            variant="field"
            fieldLabel="项目风格"
            title="选择项目风格"
            emptyLabel="未选择"
            value={(imageStyleId as ImageStyleId | '') || ''}
            onChange={(id) => void handleStyleChange(id)}
          />
          <span className="drama-outline-toolbar-meta">
            {episodeCount ? `共 ${episodeCount} 集` : '集数待定'}
            {episodeGenerating || episodeStatus === 'generating'
              ? progress.total > 0
                ? ` · 生成中 ${progress.done}/${progress.total}`
                : ' · 分集生成中'
              : ''}
          </span>
        </div>
        <div className="drama-outline-toolbar-actions">
          <button
            type="button"
            className={`drama-outline-chip-btn${metaModal === 'source' ? ' is-on' : ''}`}
            onClick={openSourceModal}
          >
            整剧创意
          </button>
          <button
            type="button"
            className={`drama-outline-chip-btn${metaModal === 'project' ? ' is-on' : ''}`}
            onClick={() => setMetaModal('project')}
          >
            项目设置
          </button>
          <button
            type="button"
            className={`drama-outline-chip-btn${metaModal === 'summary' ? ' is-on' : ''}`}
            onClick={openSummaryModal}
          >
            全局设定
          </button>
          {(episodeError || episodeStatus === 'failed') && (
            <button type="button" className="drama-outline-chip-btn" onClick={() => void handleRegenerateEpisodes()}>
              重跑全部分集
            </button>
          )}
        </div>
      </div>

      <Modal
        open={metaModal === 'source'}
        onClose={closeMetaModal}
        title="整剧创意"
        size="lg"
        className="drama-outline-meta-modal"
        footer={
          sourceEditing ? (
            <>
              <button type="button" className="drama-btn-ghost" onClick={() => setSourceEditing(false)}>
                取消编辑
              </button>
              <button
                type="button"
                className="drama-btn-primary"
                disabled={sourceSaving}
                onClick={() => void saveSourceEdit()}
              >
                {sourceSaving ? '保存中…' : '保存'}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="drama-btn-ghost"
              onClick={() => {
                setSourceDraft(script?.source || '')
                setSourceEditing(true)
              }}
            >
              编辑
            </button>
          )
        }
      >
        <div className="drama-outline-meta-modal-body">
          {sourceEditing ? (
            <textarea
              className="drama-ep-section-textarea"
              rows={16}
              value={sourceDraft}
              onChange={(e) => setSourceDraft(e.target.value)}
            />
          ) : (
            <p className="drama-pre">{script?.source?.trim() || '暂无整剧创意'}</p>
          )}
        </div>
      </Modal>

      <Modal
        open={metaModal === 'summary'}
        onClose={closeMetaModal}
        title="全局设定"
        size="lg"
        className="drama-outline-meta-modal"
        footer={
          summaryEditing ? (
            <>
              <button type="button" className="drama-btn-ghost" onClick={() => setSummaryEditing(false)}>
                取消编辑
              </button>
              <button
                type="button"
                className="drama-btn-primary"
                disabled={summarySaving}
                onClick={() => void saveSummaryEdit()}
              >
                {summarySaving ? '保存中…' : '保存'}
              </button>
            </>
          ) : summary && summaryStatus === 'completed' ? (
            <button type="button" className="drama-btn-ghost" onClick={() => startSummaryEdit()}>
              编辑
            </button>
          ) : summaryError || summaryStatus === 'failed' ? (
            <button type="button" className="drama-btn-primary" onClick={() => void runSummary()}>
              重新生成
            </button>
          ) : null
        }
      >
        <div className="drama-outline-meta-modal-body">
          {summaryGenerating || summaryStatus === 'generating' ? (
            <p className="drama-loader">全剧摘要生成中…</p>
          ) : null}
          {summaryError || summaryStatus === 'failed' ? (
            <p className="drama-error">{summaryError || '摘要生成失败'}</p>
          ) : null}
          {summaryEditing && summaryDraft ? (
            <div className="drama-outline-edit">
              <EditableSummaryField
                label="剧名"
                value={String(summaryDraft.seriesTitle || '')}
                onChange={(v) =>
                  setSummaryDraft((prev) => (prev ? { ...prev, seriesTitle: v } : prev))
                }
              />
              <EditableSummaryField
                label="自定义集数"
                value={String(summaryDraft.episodeCount ?? '')}
                onChange={(v) =>
                  setSummaryDraft((prev) =>
                    prev ? { ...prev, episodeCount: v ? Number(v) || v : '' } : prev,
                  )
                }
              />
              <EditableSummaryField
                label="故事类型"
                value={String(summaryDraft.storyType || '')}
                onChange={(v) => setSummaryDraft((prev) => (prev ? { ...prev, storyType: v } : prev))}
              />
              <EditableSummaryField
                label="一句话故事"
                value={String(summaryDraft.oneLineStory || '')}
                onChange={(v) =>
                  setSummaryDraft((prev) => (prev ? { ...prev, oneLineStory: v } : prev))
                }
                multiline
              />
              <EditableSummaryField
                label="故事梗概"
                value={String(summaryDraft.synopsis || '')}
                onChange={(v) => setSummaryDraft((prev) => (prev ? { ...prev, synopsis: v } : prev))}
                multiline
              />
            </div>
          ) : null}
          {!summaryEditing && summary && summaryStatus === 'completed' ? (
            <div className="drama-summary-structured">
              <SummaryField label="剧名" value={String(summary.seriesTitle || '')} />
              <SummaryField label="故事类型" value={String(summary.storyType || '')} />
              <SummaryField label="一句话故事" value={String(summary.oneLineStory || '')} />
              <SummaryField label="故事梗概" value={String(summary.synopsis || '')} />
              {characters.length > 0 ? (
                <section>
                  <h4>人物</h4>
                  <p className="drama-muted">
                    {characters.map((ch) => String(ch.name || '')).filter(Boolean).join('、')}
                  </p>
                </section>
              ) : null}
            </div>
          ) : null}
          {!summaryEditing && !summary && summaryStatus !== 'generating' && !summaryError ? (
            <p className="drama-muted">暂无全局设定，等待摘要生成或点击重新生成。</p>
          ) : null}
        </div>
      </Modal>

      <DramaProjectSettingsModal
        open={metaModal === 'project'}
        projectId={projectId}
        project={project}
        script={script}
        onClose={closeMetaModal}
        onProjectChange={onProjectChange}
        onScriptChange={setScript}
        onError={onError}
      />

      <OutlineEpisodePanel
        projectId={projectId}
        script={script}
        episodeCount={episodeCount}
        summaryReady={summaryStatus === 'completed' || Boolean(summary)}
        episodeGenerating={episodeGenerating || episodeStatus === 'generating'}
        imageStyleLabel={getImageStyleLabel(imageStyleId) || undefined}
        storyType={String(summary?.storyType || '') || undefined}
        onScriptChange={setScript}
        onProjectChange={onProjectChange}
        onError={onError}
        onOpenEpisodes={() => undefined}
      />
    </div>
  )
}

function SummaryField({ label, value }: { label: string; value: string }) {
  if (!value) return null
  return (
    <section className="drama-summary-field">
      <h4>{label}</h4>
      <p className="drama-pre">{value}</p>
    </section>
  )
}

function EditableSummaryField({
  label,
  value,
  onChange,
  multiline = false,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  multiline?: boolean
}) {
  return (
    <label className="drama-outline-edit-field">
      <span>{label}</span>
      {multiline ? (
        <textarea rows={3} value={value} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input type="text" value={value} onChange={(e) => onChange(e.target.value)} />
      )}
    </label>
  )
}
