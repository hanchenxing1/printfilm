/** 漫剧资产生图：提交后立刻轮询，成功后用新 URL 实时回显（不排队提交） */
import { dramaApi, type DramaAsset } from '../api/drama'
import type { ImageGenerationOptions } from './dramaGenerationOptions'
import { syncImageJobToUnified } from './dramaGenQueue'

export type DramaImageGenStatus = 'queued' | 'running' | 'done' | 'failed'

export type DramaImageGenJob = {
  id: string
  projectId: number
  assetId: number
  assetName: string
  assetType: string
  prompt: string
  options: Partial<ImageGenerationOptions>
  status: DramaImageGenStatus
  error?: string
  createdAt: number
  finishedAt?: number
}

type EnqueueInput = {
  projectId: number
  assetId: number
  assetName?: string
  assetType?: string
  prompt: string
  options?: Partial<ImageGenerationOptions>
  /** 仅恢复轮询（后端已在 generating，不再重复 POST） */
  resumeOnly?: boolean
  /** 入队/状态变化时回写资产（用于 UI 即时显示 generating / 新图） */
  onAssetUpdate?: (asset: DramaAsset) => void
}

type InternalJob = DramaImageGenJob & {
  resumeOnly: boolean
  taskId?: number
  baselineUrl: string
  onAssetUpdate?: (asset: DramaAsset) => void
  resolve: (asset: DramaAsset) => void
  reject: (err: Error) => void
}

/* 轮询可多路并行；提交不再限流排队，点了就 POST */
const MAX_POLL_CONCURRENT = 12
const DONE_RETENTION_MS = 45_000
const POLL_INTERVAL_MS = 1500
const POLL_TIMEOUT_MS = 10 * 60 * 1000

/** 对外暴露（文案用） */
export const DRAMA_IMAGE_GEN_MAX_CONCURRENT = MAX_POLL_CONCURRENT

/*
 * jobs 本地队列（UI + 轮询）
 * cachedSnapshot useSyncExternalStore 快照
 * listeners 订阅
 * pollingCount 正在 waitForAssetImage 的数量
 * pumping 是否已调度 poll pump
 */
let jobs: InternalJob[] = []
const EMPTY_SNAPSHOT: DramaImageGenJob[] = []
let cachedSnapshot: DramaImageGenJob[] = EMPTY_SNAPSHOT
const listeners = new Set<() => void>()
let pollingCount = 0
let pumping = false

// 将内部 job 转为对外结构
function toPublicJob(job: InternalJob): DramaImageGenJob {
  return {
    id: job.id,
    projectId: job.projectId,
    assetId: job.assetId,
    assetName: job.assetName,
    assetType: job.assetType,
    prompt: job.prompt,
    options: job.options,
    status: job.status,
    error: job.error,
    createdAt: job.createdAt,
    finishedAt: job.finishedAt,
  }
}

// 两个快照内容是否一致
function snapshotsEqual(a: DramaImageGenJob[], b: DramaImageGenJob[]): boolean {
  if (a === b) return true
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i += 1) {
    const left = a[i]
    const right = b[i]
    if (
      left.id !== right.id ||
      left.status !== right.status ||
      left.error !== right.error ||
      left.finishedAt !== right.finishedAt
    ) {
      return false
    }
  }
  return true
}

// 清理过期完成项
function pruneFinished() {
  const now = Date.now()
  jobs = jobs.filter((job) => {
    if (job.status === 'queued' || job.status === 'running') return true
    if (!job.finishedAt) return true
    return now - job.finishedAt < DONE_RETENTION_MS
  })
}

// 重建并缓存对外快照
function refreshSnapshot() {
  pruneFinished()
  const next = jobs.length === 0 ? EMPTY_SNAPSHOT : jobs.map((job) => toPublicJob(job))
  if (!snapshotsEqual(cachedSnapshot, next)) {
    cachedSnapshot = next
  }
}

// 通知订阅者，并同步到统一生成队列
function emit() {
  refreshSnapshot()
  listeners.forEach((listener) => listener())
  for (const job of jobs) {
    if (job.status === 'queued' || job.status === 'running' || job.finishedAt) {
      syncImageJobToUnified({
        assetId: job.assetId,
        projectId: job.projectId,
        assetName: job.assetName,
        assetType: job.assetType,
        status: job.status,
        taskId: job.taskId,
        error: job.error,
      })
    }
  }
}

// 读取队列快照
export function getDramaImageGenQueue(): DramaImageGenJob[] {
  refreshSnapshot()
  return cachedSnapshot
}

// 某资产是否忙
export function isDramaAssetImageBusy(assetId: number): boolean {
  return jobs.some(
    (job) =>
      job.assetId === assetId && (job.status === 'queued' || job.status === 'running'),
  )
}

// 当前排队 + 进行中数量
export function getDramaImageGenActiveCount(): number {
  return jobs.filter((job) => job.status === 'queued' || job.status === 'running').length
}

// 订阅队列变化
export function subscribeDramaImageGenQueue(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

// 生成本地任务 id
function makeJobId() {
  return `img-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

// 读取资产 generation 状态
function readGenerationStatus(asset: DramaAsset): string {
  const gen = (asset.params || {}).generation as { status?: string } | undefined
  return String(gen?.status || '')
}

// 资产当前预览 URL
function assetMediaUrl(asset: DramaAsset): string {
  return String(asset.url || asset.cover || '').trim()
}

/**
 * 轮询直到本次生图真正结束。
 * 有旧图时必须见到 queued/generating，或 URL 相对基线变化，避免秒回旧图当成功。
 * 必须先判 failed/cancelled：重试失败时旧 url/cover 仍在，不能当成功。
 */
async function waitForAssetImage(
  projectId: number,
  assetId: number,
  baselineUrl: string,
  onRemoteStatus?: (status: string) => void,
  onAssetUpdate?: (asset: DramaAsset) => void,
): Promise<DramaAsset> {
  const started = Date.now()
  let sawInFlight = false
  let lastNotifiedUrl = baselineUrl

  while (Date.now() - started < POLL_TIMEOUT_MS) {
    const list = await dramaApi.listAssets(projectId)
    const latest = list.find((a) => a.id === assetId)
    if (!latest) throw new Error('资产不存在')

    const status = readGenerationStatus(latest)
    const currentUrl = assetMediaUrl(latest)
    onRemoteStatus?.(status)

    if (status === 'queued' || status === 'generating') {
      sawInFlight = true
      if (currentUrl !== lastNotifiedUrl) {
        lastNotifiedUrl = currentUrl
        onAssetUpdate?.(latest)
      }
      await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
      continue
    }

    if (status === 'failed' || status === 'cancelled') {
      const gen = (latest.params || {}).generation as { error?: string } | undefined
      const raw = String(gen?.error || '').trim()
      throw new Error(raw || (status === 'cancelled' ? '生图已取消' : '生图失败'))
    }

    const urlChanged = Boolean(currentUrl) && currentUrl !== baselineUrl
    const finishedFresh =
      status === 'done' &&
      Boolean(currentUrl) &&
      (sawInFlight || urlChanged || !baselineUrl)

    if (finishedFresh) {
      onAssetUpdate?.(latest)
      return latest
    }

    // 仍是旧图且未进入过 in-flight：继续等（POST 后状态可能尚未可见）
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS))
  }
  throw new Error('生图超时，请刷新后重试')
}

const waitingPoll: InternalJob[] = []

// 有限并发轮询后端结果
async function pollJob(job: InternalJob) {
  pollingCount += 1
  try {
    const asset = await waitForAssetImage(
      job.projectId,
      job.assetId,
      job.baselineUrl,
      (remoteStatus) => {
        if (remoteStatus === 'generating' && job.status !== 'running') {
          job.status = 'running'
          emit()
        }
        if (remoteStatus === 'queued' && job.status === 'running') {
          job.status = 'queued'
          emit()
        }
      },
      job.onAssetUpdate,
    )
    job.status = 'done'
    job.finishedAt = Date.now()
    emit()
    job.resolve(asset)
  } catch (err) {
    const message = err instanceof Error ? err.message : '生图失败'
    job.status = 'failed'
    job.error = message
    job.finishedAt = Date.now()
    emit()
    job.reject(err instanceof Error ? err : new Error(message))
  } finally {
    pollingCount -= 1
    pumpPoll()
    emit()
  }
}

// 调度轮询槽位
function pumpPoll() {
  if (pumping) return
  pumping = true
  queueMicrotask(() => {
    pumping = false
    while (pollingCount < MAX_POLL_CONCURRENT && waitingPoll.length > 0) {
      const next = waitingPoll.shift()
      if (!next) break
      if (next.status === 'failed' || next.status === 'done') continue
      void pollJob(next)
    }
    emit()
  })
}

// 立即 POST 入队（不限流），再进入轮询
async function submitJob(job: InternalJob) {
  try {
    if (!job.resumeOnly) {
      const resp = await dramaApi.generateImage({
        project_id: job.projectId,
        asset_id: job.assetId,
        prompt: job.prompt,
        name: job.assetName || undefined,
        asset_type_kind: job.assetType,
        image_style_id: job.options.image_style_id,
        model_id: job.options.model_id,
        aspect_ratio: job.options.aspect_ratio,
        resolution: job.options.resolution,
      })
      job.taskId = resp.task_id != null ? Number(resp.task_id) : undefined
      const queuedAsset = (resp as { asset?: DramaAsset }).asset
      if (queuedAsset) {
        job.onAssetUpdate?.(queuedAsset)
      }
    }
    if (job.status === 'queued') {
      job.status = 'running'
    }
    waitingPoll.push(job)
    pumpPoll()
  } catch (err) {
    const message = err instanceof Error ? err.message : '生图失败'
    job.status = 'failed'
    job.error = message
    job.finishedAt = Date.now()
    emit()
    job.reject(err instanceof Error ? err : new Error(message))
  } finally {
    emit()
  }
}

/**
 * 将资产生图加入队列：立刻 POST 到后端，再本地轮询结果。
 * 同资产已在排队/生成中时复用同一 Promise（避免重复打上游）。
 */
export function enqueueDramaImageGen(input: EnqueueInput): Promise<DramaAsset> {
  const existing = jobs.find(
    (job) =>
      job.assetId === input.assetId &&
      (job.status === 'queued' || job.status === 'running'),
  )
  if (existing) {
    if (input.onAssetUpdate) {
      const prev = existing.onAssetUpdate
      existing.onAssetUpdate = (asset) => {
        prev?.(asset)
        input.onAssetUpdate?.(asset)
      }
    }
    return new Promise((resolve, reject) => {
      const prevResolve = existing.resolve
      const prevReject = existing.reject
      existing.resolve = (asset) => {
        prevResolve(asset)
        resolve(asset)
      }
      existing.reject = (err) => {
        prevReject(err)
        reject(err)
      }
    })
  }

  return new Promise<DramaAsset>((resolve, reject) => {
    const job: InternalJob = {
      id: makeJobId(),
      projectId: input.projectId,
      assetId: input.assetId,
      assetName: (input.assetName || '').trim() || `资产 ${input.assetId}`,
      assetType: input.assetType || 'character',
      prompt: input.prompt,
      options: input.options || {},
      status: 'queued',
      createdAt: Date.now(),
      resumeOnly: Boolean(input.resumeOnly),
      baselineUrl: '',
      onAssetUpdate: input.onAssetUpdate,
      resolve,
      reject,
    }
    jobs = [...jobs, job]
    emit()
    // 先拉一次当前图作基线，再提交/轮询，避免旧图被当成成功
    void (async () => {
      try {
        const list = await dramaApi.listAssets(input.projectId)
        const current = list.find((a) => a.id === input.assetId)
        job.baselineUrl = current ? assetMediaUrl(current) : ''
      } catch {
        job.baselineUrl = ''
      }
      if (job.resumeOnly) {
        waitingPoll.push(job)
        pumpPoll()
        return
      }
      void submitJob(job)
    })()
  })
}

/**
 * 从资产列表恢复「后端仍在 generating」的任务（刷新页面后调用）。
 * 不再重复 POST，只接上轮询与队列 UI。
 */
export function resumeDramaImageGensFromAssets(
  projectId: number,
  assets: DramaAsset[],
  onAssetUpdate?: (asset: DramaAsset) => void,
): void {
  for (const asset of assets) {
    if (asset.project_id !== projectId) continue
    /* 视频资产走 Seedance 队列，避免刷新后误 POST 生图 */
    if ((asset.type || '').toLowerCase() === 'video') continue
    const status = readGenerationStatus(asset)
    if (status !== 'generating' && status !== 'queued') continue
    if (isDramaAssetImageBusy(asset.id)) continue
    void enqueueDramaImageGen({
      projectId,
      assetId: asset.id,
      assetName: asset.name || undefined,
      assetType: asset.type,
      prompt: '',
      resumeOnly: true,
      onAssetUpdate,
    }).catch(() => {
      /* 面板会显示失败；页面层可再 toast */
    })
  }
}

// 清空已结束项
export function clearFinishedDramaImageGenJobs() {
  jobs = jobs.filter((job) => job.status === 'queued' || job.status === 'running')
  emit()
}
