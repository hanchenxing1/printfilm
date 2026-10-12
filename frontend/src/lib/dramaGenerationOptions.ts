/** 漫剧生图：模型 / 比例 / 清晰度选项（模型列表与参数来自后台 TokenFree 目录） */

import type { MediaModelOption, MediaModelsCatalog } from '../api'

export type ImageGenerationModelId = string

export type GenerationAspectRatioId =
  | 'auto'
  | '16:9'
  | '21:9'
  | '9:16'
  | '4:3'
  | '3:4'
  | '3:2'
  | '2:3'
  | '1:1'

export type GenerationResolution = '1K' | '2K' | '3K' | '4K'

export type ImageGenerationOptions = {
  image_style_id?: string
  model_id: ImageGenerationModelId
  aspect_ratio: GenerationAspectRatioId
  resolution: GenerationResolution
}

/** 全量清晰度（实际展示按模型 allowed_resolutions 过滤） */
export const GENERATION_RESOLUTION_OPTIONS: GenerationResolution[] = ['1K', '2K', '3K', '4K']
/** 目录未到时的保守档（与后端 Pro / gpt-image 一致） */
export const SAFE_IMAGE_RESOLUTION_OPTIONS: GenerationResolution[] = ['1K', '2K']

/** 比例列表 */
export const GENERATION_ASPECT_RATIO_OPTIONS: Array<{
  id: GenerationAspectRatioId
  label: string
}> = [
  { id: 'auto', label: '自动' },
  { id: '16:9', label: '16:9' },
  { id: '21:9', label: '21:9' },
  { id: '9:16', label: '9:16' },
  { id: '4:3', label: '4:3' },
  { id: '3:4', label: '3:4' },
  { id: '3:2', label: '3:2' },
  { id: '2:3', label: '2:3' },
  { id: '1:1', label: '1:1' },
]

/** 生图模型由 /api/media-models 提供；此处仅占位默认 id */
export const IMAGE_GENERATION_MODELS: Array<{
  id: ImageGenerationModelId
  label: string
  description: string
}> = []

/** 默认生图选项（角色偏竖构图；清晰度默认 2K，避免 Pro 静默降档） */
export const DEFAULT_IMAGE_GENERATION_OPTIONS: ImageGenerationOptions = {
  model_id: '',
  aspect_ratio: '3:4',
  resolution: '2K',
}

/** 场景默认横构图 */
export function defaultOptionsForAssetKind(kind: string | undefined | null): ImageGenerationOptions {
  const k = String(kind || '').toLowerCase()
  if (k === 'scene') {
    return { model_id: DEFAULT_IMAGE_GENERATION_OPTIONS.model_id, aspect_ratio: '16:9', resolution: '2K' }
  }
  return { ...DEFAULT_IMAGE_GENERATION_OPTIONS }
}

/** 格式化比例·清晰度触发文案 */
export function formatOutputSettingsLabel(
  aspectRatio: GenerationAspectRatioId,
  resolution: GenerationResolution,
): string {
  if (aspectRatio === 'auto') return `自动 · ${resolution}`
  return `${aspectRatio} · ${resolution}`
}

/** 解析模型展示名（无目录时回退 id） */
export function getImageModelLabel(modelId: string | undefined | null): string {
  const id = (modelId || '').trim()
  return id || '图片模型'
}

/** 任意非空字符串均可作为生图模型 id */
export function isImageGenerationModelId(id: string): id is ImageGenerationModelId {
  return Boolean((id || '').trim())
}

function findImageModelRow(
  modelId: string | undefined | null,
  catalog: MediaModelsCatalog | null | undefined,
  imageModels?: MediaModelOption[],
): MediaModelOption | undefined {
  const id = (modelId || '').trim()
  const models = imageModels ?? catalog?.image_models ?? []
  return id ? models.find((m) => m.id === id) : undefined
}

/** 当前模型允许的清晰度 */
export function resolutionsForImageModel(
  modelId: string | undefined | null,
  catalog?: MediaModelsCatalog | null,
  imageModels?: MediaModelOption[],
): GenerationResolution[] {
  const row = findImageModelRow(modelId, catalog, imageModels)
  const raw = row?.allowed_resolutions
  if (Array.isArray(raw) && raw.length > 0) {
    const filtered = raw.filter((r): r is GenerationResolution =>
      GENERATION_RESOLUTION_OPTIONS.includes(r as GenerationResolution),
    )
    if (filtered.length) return filtered
  }
  return [...SAFE_IMAGE_RESOLUTION_OPTIONS]
}

/** 当前模型允许的比例 */
export function aspectRatiosForImageModel(
  modelId: string | undefined | null,
  catalog?: MediaModelsCatalog | null,
  imageModels?: MediaModelOption[],
): GenerationAspectRatioId[] {
  const row = findImageModelRow(modelId, catalog, imageModels)
  const allIds = GENERATION_ASPECT_RATIO_OPTIONS.map((o) => o.id)
  const raw = row?.allowed_aspect_ratios
  if (Array.isArray(raw) && raw.length > 0) {
    const filtered = raw.filter((r): r is GenerationAspectRatioId =>
      allIds.includes(r as GenerationAspectRatioId),
    )
    if (filtered.length) return filtered
  }
  return [...allIds]
}

/** 将清晰度钳到模型允许列表 */
export function clampImageResolutionForModel(
  modelId: string | undefined | null,
  resolution: string | undefined | null,
  catalog?: MediaModelsCatalog | null,
  imageModels?: MediaModelOption[],
): GenerationResolution {
  const allowed = resolutionsForImageModel(modelId, catalog, imageModels)
  const raw = String(resolution || '').trim() as GenerationResolution
  if (allowed.includes(raw)) return raw
  return allowed[allowed.length - 1] || '2K'
}

/** 将比例钳到模型允许列表 */
export function clampImageAspectRatioForModel(
  modelId: string | undefined | null,
  aspectRatio: string | undefined | null,
  catalog?: MediaModelsCatalog | null,
  imageModels?: MediaModelOption[],
): GenerationAspectRatioId {
  const allowed = aspectRatiosForImageModel(modelId, catalog, imageModels)
  const raw = String(aspectRatio || '').trim() as GenerationAspectRatioId
  if (allowed.includes(raw)) return raw
  return allowed.includes('3:4') ? '3:4' : allowed[0] || '3:4'
}
