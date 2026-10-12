/** Shared helpers for drama project workspace steps. */
import type { DramaEpisodeBody, DramaProject, DramaScript } from '../../api/drama'

/** 与后端 MIN_EPISODE_CONTENT_CHARS 对齐：过短正文视为未完成 */
export const MIN_EPISODE_BODY_CHARS = 500
export const MIN_EPISODE_CREATIVE_CHARS = 20

export type OutlineDirectoryEpisode = {
  episodeNumber: number
  title: string
  creative?: string
  summary?: string
  body?: string
  origin?: string
}

// 解析 episode_content 为分集数组
export function parseEpisodeBodies(script: DramaScript | null | undefined): DramaEpisodeBody[] {
  const raw = script?.episode_content
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (Array.isArray(raw.episodes)) return raw.episodes
  return []
}

// 去空白后的正文字数
export function episodeBodyCharLen(text: string | undefined): number {
  return (text || '').replace(/\s/g, '').length
}

// 手动加集（等待用户贴剧本）不会被自动流水线填满
export function isManualEpisode(ep: DramaEpisodeBody | undefined): boolean {
  return ep?.origin === 'manual'
}

// 正文是否达到可进入下一步的长度
export function isSubstantialEpisodeBody(body: string | undefined): boolean {
  return episodeBodyCharLen(body) >= MIN_EPISODE_BODY_CHARS
}

export function isSubstantialEpisodeCreative(creative: string | undefined): boolean {
  return episodeBodyCharLen(creative) >= MIN_EPISODE_CREATIVE_CHARS
}

// 是否已有至少一集可用正文
export function hasSubstantialEpisode(bodies: DramaEpisodeBody[]): boolean {
  return bodies.some((ep) => isSubstantialEpisodeBody(ep.body))
}

// 自动流水线仍缺的集数（跳过手动空集）
export function autoMissingEpisodeCount(bodies: DramaEpisodeBody[], target: number): number {
  const byNumber = new Map<number, DramaEpisodeBody>()
  for (const ep of bodies) {
    const num = ep.episodeNumber || 0
    if (num >= 1) byNumber.set(num, ep)
  }
  let missing = 0
  const total = Math.max(target, 0)
  for (let num = 1; num <= total; num += 1) {
    const ep = byNumber.get(num)
    if (!ep) {
      missing += 1
      continue
    }
    if (isSubstantialEpisodeBody(ep.body)) continue
    if (isManualEpisode(ep)) continue
    missing += 1
  }
  return missing
}

// 按目标集数铺满目录
export function buildOutlineDirectory(
  bodies: DramaEpisodeBody[],
  episodeCount: number,
): OutlineDirectoryEpisode[] {
  const byNumber = new Map(
    bodies.map((ep, i) => {
      const num = ep.episodeNumber || i + 1
      return [num, ep] as const
    }),
  )
  const total = Math.max(episodeCount, bodies.length, 0)
  if (total <= 0) return []
  return Array.from({ length: total }, (_, i) => {
    const episodeNumber = i + 1
    const ep = byNumber.get(episodeNumber)
    return {
      episodeNumber,
      title: ep?.title || `第 ${episodeNumber} 集`,
      creative: ep?.creative,
      summary: ep?.summary,
      body: ep?.body,
      origin: ep?.origin,
    }
  })
}

// 目录项与正文合并（保留 creative / summary）
export function mergeDirectoryEpisodeBodies(
  directory: OutlineDirectoryEpisode[],
  bodies: DramaEpisodeBody[],
): DramaEpisodeBody[] {
  const byNumber = new Map(bodies.map((ep, i) => [ep.episodeNumber || i + 1, ep] as const))
  return directory.map((item) => {
    const found = byNumber.get(item.episodeNumber)
    return {
      episodeNumber: item.episodeNumber,
      title: found?.title || item.title,
      creative: found?.creative || item.creative || '',
      summary: found?.summary || item.summary || '',
      body: found?.body || item.body || '',
      origin: found?.origin || (item.origin as 'auto' | 'manual' | undefined),
    }
  })
}

// 读取摘要状态
export function getSummaryStatus(script: DramaScript | null | undefined): string {
  return String((script?.params || {}).summary_status || (script?.summary ? 'completed' : 'pending'))
}

// 读取分集剧本状态
export function getEpisodeContentStatus(script: DramaScript | null | undefined): string {
  return String((script?.params || {}).episode_content_status || 'pending')
}

// 读取画面风格 ID
export function getImageStyleId(
  script: DramaScript | null | undefined,
  project: DramaProject | null,
): string {
  const fromScript = (script?.params || {}).image_style_id
  const fromProject = (project?.params || {}).image_style_id
  return String(fromScript || fromProject || '')
}

// 写回分集正文时保持与原结构一致（数组或 { episodes }）
export function buildEpisodeContentUpdate(
  script: DramaScript | null | undefined,
  bodies: DramaEpisodeBody[],
): DramaScript['episode_content'] {
  const raw = script?.episode_content
  if (Array.isArray(raw)) return bodies
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    return { ...(raw as Record<string, unknown>), episodes: bodies }
  }
  return { episodes: bodies }
}
