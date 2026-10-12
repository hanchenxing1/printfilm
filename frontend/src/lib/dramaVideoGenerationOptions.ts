/** 漫剧画布 / 分集：视频生成选项（模型列表来自后台 TokenFree 目录） */
import type { MediaModelOption, MediaModelsCatalog } from '../api'

export type VideoGenerationModelId = string

export type VideoAspectRatio = '9:16' | '16:9' | '1:1'
export type VideoResolution = '480p' | '720p' | '1080p'

export type VideoGenerationOptions = {
  image_style_id?: string
  model_id: VideoGenerationModelId
  aspect_ratio: VideoAspectRatio
  resolution: VideoResolution
  duration_sec: number
}

export const VIDEO_ASPECT_RATIO_OPTIONS: VideoAspectRatio[] = ['9:16', '16:9', '1:1']
export const VIDEO_RESOLUTION_OPTIONS: VideoResolution[] = ['480p', '720p', '1080p']
/** 目录未到 / 未知模型时的保守档（与后端 SAFE 一致） */
export const SAFE_VIDEO_RESOLUTION_OPTIONS: VideoResolution[] = ['480p', '720p']
export const VIDEO_DURATION_PRESETS = [5, 8, 10, 15] as const
export const VIDEO_DURATION_MIN = 4
export const VIDEO_DURATION_MAX = 30

export const DEFAULT_VIDEO_GENERATION_OPTIONS: VideoGenerationOptions = {
  model_id: '',
  aspect_ratio: '9:16',
  resolution: '720p',
  duration_sec: 8,
}

function findVideoModelRow(
  modelId: string | undefined | null,
  catalog: MediaModelsCatalog | null | undefined,
  videoModels?: MediaModelOption[],
): MediaModelOption | undefined {
  const id = (modelId || '').trim()
  const models = videoModels ?? catalog?.video_models ?? []
  return id ? models.find((m) => m.id === id) : undefined
}

/** 当前模型时长上下限 */
export function durationBoundsForModel(
  modelId: string | undefined | null,
  catalog?: MediaModelsCatalog | null,
  videoModels?: MediaModelOption[],
): { min: number; max: number } {
  const row = findVideoModelRow(modelId, catalog, videoModels)
  const min = Math.max(1, Number(row?.duration_min) || VIDEO_DURATION_MIN)
  const max = Math.max(min, Number(row?.duration_max) || VIDEO_DURATION_MAX)
  return { min, max }
}

/** 夹紧时长到模型允许区间 */
export function clampVideoDuration(
  sec: number,
  modelId?: string | null,
  catalog?: MediaModelsCatalog | null,
  videoModels?: MediaModelOption[],
) {
  const { min, max } = durationBoundsForModel(modelId, catalog, videoModels)
  const n = Math.round(Number(sec) || DEFAULT_VIDEO_GENERATION_OPTIONS.duration_sec)
  return Math.min(max, Math.max(min, n))
}

/** 当前模型允许的比例 */
export function aspectRatiosForVideoModel(
  modelId: string | undefined | null,
  catalog?: MediaModelsCatalog | null,
  videoModels?: MediaModelOption[],
): VideoAspectRatio[] {
  const row = findVideoModelRow(modelId, catalog, videoModels)
  const raw = row?.allowed_aspect_ratios
  if (Array.isArray(raw) && raw.length > 0) {
    const filtered = raw.filter((r): r is VideoAspectRatio =>
      VIDEO_ASPECT_RATIO_OPTIONS.includes(r as VideoAspectRatio),
    )
    if (filtered.length) return filtered
  }
  return [...VIDEO_ASPECT_RATIO_OPTIONS]
}

/** 将比例钳到模型允许列表 */
export function clampVideoAspectRatioForModel(
  modelId: string | undefined | null,
  aspectRatio: string | undefined | null,
  catalog?: MediaModelsCatalog | null,
  videoModels?: MediaModelOption[],
): VideoAspectRatio {
  const allowed = aspectRatiosForVideoModel(modelId, catalog, videoModels)
  const raw = String(aspectRatio || '').trim() as VideoAspectRatio
  if (allowed.includes(raw)) return raw
  return allowed[0] || '9:16'
}

/** 格式化比例 · 清晰度 */
export function formatVideoOutputLabel(
  aspectRatio: VideoAspectRatio,
  resolution: VideoResolution,
) {
  return `${aspectRatio} · ${resolution}`
}

/** 解析模型展示名（无目录时回退 id） */
export function getVideoModelLabel(modelId: string | undefined | null) {
  const id = (modelId || '').trim()
  return id || '视频模型'
}

/** 任意非空字符串均可作为视频模型 id（后台 TokenFree 目录） */
export function isVideoGenerationModelId(id: string): id is VideoGenerationModelId {
  return Boolean((id || '').trim())
}

/** 当前模型允许的清晰度列表（目录行优先；未知时保守两档，仅展示勿静默落库） */
export function resolutionsForModel(
  modelId: string | undefined | null,
  catalog: MediaModelsCatalog | null | undefined,
  videoModels?: MediaModelOption[],
): VideoResolution[] {
  const row = findVideoModelRow(modelId, catalog, videoModels)
  const raw = row?.allowed_resolutions
  if (Array.isArray(raw) && raw.length > 0) {
    const filtered = raw.filter((r): r is VideoResolution =>
      VIDEO_RESOLUTION_OPTIONS.includes(r as VideoResolution),
    )
    if (filtered.length) return filtered
  }
  return [...SAFE_VIDEO_RESOLUTION_OPTIONS]
}

/** 目录已加载且能匹配到带清晰度白名单的视频模型行 */
export function hasKnownVideoModelResolutions(
  modelId: string | undefined | null,
  catalog: MediaModelsCatalog | null | undefined,
  videoModels?: MediaModelOption[],
): boolean {
  if (!catalog) return false
  const row = findVideoModelRow(modelId, catalog, videoModels)
  const raw = row?.allowed_resolutions
  return Array.isArray(raw) && raw.length > 0
}

/** 将清晰度钳到模型允许列表；非法取列表最高档 */
export function clampVideoResolutionForModel(
  modelId: string | undefined | null,
  resolution: string | undefined | null,
  catalog?: MediaModelsCatalog | null,
  videoModels?: MediaModelOption[],
): VideoResolution {
  const allowed = resolutionsForModel(modelId, catalog, videoModels)
  const raw = String(resolution || '').trim() as VideoResolution
  if (allowed.includes(raw)) return raw
  return allowed[allowed.length - 1] || '720p'
}

/** 从节点 data 恢复视频选项 */
export function readVideoGenerationOptions(raw: unknown): VideoGenerationOptions {
  const row = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {}
  const modelId = String(row.model_id || '').trim()
  const aspect = String(row.aspect_ratio || '')
  const resolution = String(row.resolution || '')
  return {
    image_style_id: typeof row.image_style_id === 'string' ? row.image_style_id : undefined,
    model_id: modelId || DEFAULT_VIDEO_GENERATION_OPTIONS.model_id,
    aspect_ratio: VIDEO_ASPECT_RATIO_OPTIONS.includes(aspect as VideoAspectRatio)
      ? (aspect as VideoAspectRatio)
      : DEFAULT_VIDEO_GENERATION_OPTIONS.aspect_ratio,
    resolution: VIDEO_RESOLUTION_OPTIONS.includes(resolution as VideoResolution)
      ? (resolution as VideoResolution)
      : DEFAULT_VIDEO_GENERATION_OPTIONS.resolution,
    duration_sec: clampVideoDuration(Number(row.duration_sec), modelId),
  }
}
