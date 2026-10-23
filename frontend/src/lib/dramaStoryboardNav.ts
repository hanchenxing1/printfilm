/** 分镜入口：跳过中间分集页，直达首集编辑 */
import { dramaApi, type DramaEpisode } from '../api/drama'

/**
 * 进入分镜时统一走 seed 接口（force=false）：
 * - 分镜已正常切分 → 原样返回，开销极小
 * - 存量「每集一条空分镜 + 剧本正文已就绪」→ 后端自动重切成多镜
 */
export async function loadDramaEpisodes(
  projectId: number,
  force = false,
): Promise<DramaEpisode[]> {
  return dramaApi.seedEpisodes(projectId, force)
}

/** 确保已切分并返回首集（或指定集）编辑路径；无分集则回大纲 */
export async function resolveStoryboardPath(
  projectId: number,
  preferredEpisodeId?: number | null,
): Promise<string> {
  const rows = await loadDramaEpisodes(projectId, false)
  if (preferredEpisodeId && rows.some((r) => r.id === preferredEpisodeId)) {
    return `/drama/projects/${projectId}/episodes/${preferredEpisodeId}`
  }
  const first = rows[0]
  if (first?.id) return `/drama/projects/${projectId}/episodes/${first.id}`
  return `/drama/projects/${projectId}`
}
