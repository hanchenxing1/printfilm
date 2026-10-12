/** 漫剧模型选择：图标族与展示文案辅助 */
import type { MediaModelOption } from '../api'

export type MediaModelIconKind =
  | 'seedance25'
  | 'seedance'
  | 'seedanceMini'
  | 'minimax'
  | 'seedream'
  | 'gptImage'
  | 'generic'

/** 按模型 id 推断图标族 */
export function mediaModelIconKind(modelId: string | undefined | null): MediaModelIconKind {
  const id = (modelId || '').toLowerCase()
  if (!id) return 'generic'
  if (id.includes('minimax')) return 'minimax'
  if (id.includes('seedream')) return 'seedream'
  if (id.includes('gpt-image') || id.includes('sunburst')) return 'gptImage'
  if (id.includes('seedance') && (id.includes('mini') || id.includes('fast'))) return 'seedanceMini'
  if (id.includes('seedance') && (id.includes('2-5') || id.includes('2.5'))) return 'seedance25'
  if (id.includes('seedance')) return 'seedance'
  return 'generic'
}

/** 能力标签（列表角标） */
export function mediaModelCapabilityBadge(model: MediaModelOption): string {
  const id = (model.id || '').toLowerCase()
  if (id.includes('minimax')) return 'MiniMax'
  if (id.includes('seedance')) return 'Seedance'
  if (id.includes('seedream')) return 'Seedream'
  if (id.includes('gpt-image')) return 'GPT Image'
  return model.provider === 'tokenfree' ? 'TokenFree' : model.provider || '模型'
}

/** 悬停 / title 完整介绍 */
export function mediaModelHoverText(model: MediaModelOption): string {
  const clip =
    typeof model.duration_min === 'number' && typeof model.duration_max === 'number'
      ? `成片 ${model.duration_min}–${model.duration_max}s`
      : ''
  const parts = [
    model.label || model.id,
    model.description?.trim(),
    model.eta_hint?.trim() ? `耗时：${model.eta_hint.trim()}` : '',
    clip,
    model.pricing_hint?.trim() || '',
  ].filter(Boolean)
  return parts.join('\n')
}

/** 成片可选取时长文案 */
export function mediaModelClipDurationLabel(model: MediaModelOption): string {
  const lo = Number(model.duration_min)
  const hi = Number(model.duration_max)
  if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo <= 0 || hi <= 0) return ''
  if (lo === hi) return `成片 ${lo}s`
  return `成片 ${lo}–${hi}s`
}
