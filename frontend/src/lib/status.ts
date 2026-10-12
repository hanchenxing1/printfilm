import { getActiveLocale } from '../i18n/detect'
import { messages } from '../i18n/messages'

export const RUNNING = new Set([
  'SCRIPTING',
  'IMAGING',
  'VIDEOING',
  'AUDIOING',
  'COMPOSING',
  'AUDITING',
  'PARALLEL_ASSETS',
])

// 按当前界面语言取状态文案（兼容旧的 STATUS_CN[code] 写法）
export const STATUS_CN: Record<string, string> = new Proxy(
  {},
  {
    get(_target, prop: string) {
      const map = messages[getActiveLocale()].status as Record<string, string>
      return map[prop] || prop
    },
  },
)

export function isRunning(status: string) {
  return RUNNING.has(status)
}

export function hasActiveTasks(project: {
  active_tasks?: Array<{ status: string; cancel_requested?: boolean | null }> | null
}) {
  const activeStatuses = ['pending', 'leased', 'running', 'awaiting_poll', 'awaiting_review']
  return Boolean(
    project.active_tasks?.some(
      (task) => !task.cancel_requested && activeStatuses.includes(task.status),
    ),
  )
}

/**
 * Prefer stage inferred from shot assets when status is still SCRIPTING
 * (e.g. continue-generate briefly labeled wrong, or worker lag).
 */
export function effectiveStatus(project: {
  status: string
  pipeline_mode?: string | null
  shots?: Array<{ image_url?: string | null; audio_url?: string | null; video_url?: string | null }>
}): string {
  const status = project.status
  const shots = project.shots || []
  if (status !== 'SCRIPTING' || shots.length === 0) return status

  const full = project.pipeline_mode !== 'image_text'
  const imgs = shots.filter((s) => s.image_url).length
  const auds = shots.filter((s) => s.audio_url).length
  const vids = shots.filter((s) => s.video_url).length
  const n = shots.length
  // full 管线配音由视频模型完成，不要求 TTS audio_url
  const assetsOk = full ? imgs === n : imgs === n && auds === n

  if (assetsOk) {
    if (full && vids < n) return 'VIDEOING'
    if (full && vids === n) return 'COMPOSING'
    if (!full) return 'COMPOSING'
  }
  if (imgs > 0 || auds > 0) return 'IMAGING'
  return status
}

export function statusLabel(projectOrStatus: string | Parameters<typeof effectiveStatus>[0]) {
  const status = typeof projectOrStatus === 'string' ? projectOrStatus : effectiveStatus(projectOrStatus)
  return STATUS_CN[status] || status
}

export function statusTone(status: string): 'ok' | 'bad' | 'run' | 'idle' {
  if (status === 'DONE') return 'ok'
  if (status === 'FAILED' || status === 'REJECTED' || status === 'CANCELLED') return 'bad'
  if (isRunning(status)) return 'run'
  return 'idle'
}

/** Per-shot statuses from pipeline */
export const SHOT_STATUS_CN: Record<string, string> = new Proxy(
  {},
  {
    get(_target, prop: string) {
      const map = messages[getActiveLocale()].shotStatus as Record<string, string>
      return map[prop] || STATUS_CN[prop] || prop
    },
  },
)

// 兼容旧调用：直接翻译 shot.status
export function shotStatusLabel(status: string) {
  return SHOT_STATUS_CN[status] || STATUS_CN[status] || status
}

// 旧「镜头终态」判断；分镜表请用 shotDisplayDone
export function shotIsDone(status: string) {
  return ['AUDIO_READY', 'VIDEO_READY', 'DONE', 'IMAGE_READY'].includes(status)
}

/** 分镜表按素材完备度展示，不盲信 shot.status（AUDIO_READY 只代表配音） */
export type ShotDisplayKind =
  | 'failed'
  | 'generating'
  | 'wait_image'
  | 'wait_video'
  | 'image_ready'
  | 'video_ready'

export type ShotAssetLike = {
  status?: string | null
  image_url?: string | null
  video_url?: string | null
}

/*
 * SHOT_TASK_ACTIVE 任务中心进行中状态
 * PROJECT_WIDE_TASKS 整片占用，单镜生成需避开
 */
const SHOT_TASK_ACTIVE = [
  'pending',
  'leased',
  'running',
  'awaiting_poll',
  'awaiting_review',
  'cancel_requested',
]
const PROJECT_WIDE_TASKS = new Set([
  'project_pipeline',
  'project_compose_only',
  'project_regen_audio',
  'shot_regen_audio',
])

/** 按图/视频是否齐推断单镜展示态 */
export function shotDisplayKind(
  shot: ShotAssetLike,
  opts?: { pipelineMode?: string | null; generating?: boolean },
): ShotDisplayKind {
  if (opts?.generating) return 'generating'
  if (shot.status === 'FAILED') return 'failed'
  if (!shot.image_url) return 'wait_image'
  const full = opts?.pipelineMode !== 'image_text'
  if (full && !shot.video_url) return 'wait_video'
  if (full) return 'video_ready'
  return 'image_ready'
}

/** 该镜素材是否已齐（静图看图，全流程看视频） */
export function shotDisplayDone(kind: ShotDisplayKind) {
  return kind === 'image_ready' || kind === 'video_ready'
}

/** 分镜表 / CSV 用的素材态文案 */
export function shotDisplayLabel(kind: ShotDisplayKind) {
  const key = {
    failed: 'FAILED',
    generating: 'GENERATING',
    wait_image: 'WAIT_IMAGE',
    wait_video: 'WAIT_VIDEO',
    image_ready: 'IMAGE_READY',
    video_ready: 'VIDEO_READY',
  }[kind]
  return SHOT_STATUS_CN[key] || key
}

type TaskLike = {
  status: string
  task_type?: string | null
  shot_id?: number | null
  cancel_requested?: boolean | null
}

/** 整片流水线 / 合成 / 整片配音进行中 */
export function isProjectWideBusy(project: {
  status?: string
  active_tasks?: TaskLike[] | null
}) {
  const tasks = project.active_tasks
  if (Array.isArray(tasks)) {
    return tasks.some(
      (task) =>
        SHOT_TASK_ACTIVE.includes(task.status) && PROJECT_WIDE_TASKS.has(task.task_type || ''),
    )
  }
  return isRunning(project.status || '')
}

/** 该镜是否有进行中的单镜任务 */
export function isShotGenerating(
  project: { active_tasks?: TaskLike[] | null } | null | undefined,
  shotId: number,
) {
  return Boolean(
    project?.active_tasks?.some(
      (task) => task.shot_id === shotId && SHOT_TASK_ACTIVE.includes(task.status),
    ),
  )
}

export function formatMmSs(seconds: number) {
  const s = Math.max(0, Math.round(seconds || 0))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
}

/** 科普全链路步骤：建项 / 风格 / 分镜台共用 */
export const KEPU_STEPS = [
  { key: 'topic', label: '选题' },
  { key: 'style', label: '风格' },
  { key: 'confirm', label: '确认分镜' },
  { key: 'assets', label: '画面与配音' },
  { key: 'videos', label: '镜头视频' },
  { key: 'compose', label: '合成预览' },
]

export const CREATE_STEPS = KEPU_STEPS
export const BOARD_STEPS = KEPU_STEPS

/** 静图成片跳过「镜头视频」步 */
export function kepuSteps(pipelineMode?: string | null) {
  if (pipelineMode === 'image_text') {
    return KEPU_STEPS.filter((s) => s.key !== 'videos')
  }
  return KEPU_STEPS
}

export type KepuWizardPage = 'create' | 'style' | 'board'

export type KepuBillingPhase = 'script' | 'assets' | 'videos' | 'compose'

/** 与后端 resolve_kepu_billing_phase 对齐（前端不做近静音文件检测）。 */
export function kepuBillingPhase(project: {
  pipeline_mode?: string | null
  shots?: Array<{ image_url?: string | null; audio_url?: string | null; video_url?: string | null }>
}): KepuBillingPhase {
  const shots = project.shots || []
  if (!shots.length) return 'script'
  const full = project.pipeline_mode !== 'image_text'
  const needImages = shots.some((s) => !s.image_url)
  const needAudio = !full && shots.some((s) => !s.audio_url)
  if (needImages || needAudio) return 'assets'
  if (full && shots.some((s) => !s.video_url)) return 'videos'
  return 'compose'
}

export function shotsByNo<T extends { shot_no: number }>(shots: T[] | null | undefined): T[] {
  return [...(shots || [])].sort((a, b) => a.shot_no - b.shot_no)
}

/**
 * 当前步骤下标；分镜台跟 script / assets / videos / compose 对齐。
 */
export function kepuStepIndex(
  page: KepuWizardPage,
  project?: {
    status: string
    pipeline_mode?: string | null
    final_video_url?: string | null
    shots?: Array<{ image_url?: string | null; audio_url?: string | null; video_url?: string | null }>
  } | null,
): number {
  const steps = kepuSteps(project?.pipeline_mode)
  const idx = (key: string) => {
    const n = steps.findIndex((s) => s.key === key)
    return n >= 0 ? n : 0
  }
  if (page === 'create') return idx('topic')
  if (page === 'style') return idx('style')
  if (!project) return idx('confirm')
  const status = effectiveStatus(project)
  const shots = project.shots || []
  if (isRunning(status)) {
    if (status === 'VIDEOING') return idx('videos')
    if (['IMAGING', 'AUDIOING', 'PARALLEL_ASSETS'].includes(status)) return idx('assets')
    if (['COMPOSING', 'AUDITING'].includes(status)) return idx('compose')
  }
  if (project.final_video_url && status === 'DONE') return idx('compose')
  const phase = kepuBillingPhase(project)
  if (phase === 'compose') return idx('compose')
  if (phase === 'videos') return idx('videos')
  if (phase === 'assets') return idx('assets')
  if (status === 'DRAFT' && shots.length === 0) return idx('style')
  return idx('confirm')
}

/** 分镜台主按钮旁：本步做什么、是否预扣 */
export function kepuPhaseHint(project: {
  status: string
  pipeline_mode?: string | null
  shots?: Array<{ image_url?: string | null; audio_url?: string | null; video_url?: string | null }>
}): string {
  if (isRunning(effectiveStatus(project))) {
    return '生成进行中，可在右侧查看各阶段进度。'
  }
  const phase = kepuBillingPhase(project)
  if (phase === 'script') return '先在风格页点「生成故事板」，本步只拆分镜脚本（预扣文字模型）。'
  if (phase === 'assets') return '确认旁白与画面后开始生成：按镜头依次出图（后镜参考上一镜）+ 整片配音。'
  if (phase === 'videos') return '画面与配音已齐。下一步按镜头依次出视频，后镜参考上一镜尾帧。'
  return '素材已齐。拼接成片走后期合成（叠旁白字幕与配乐，扣费很少）。'
}
