/** 拉取并缓存前台 TokenFree 图/视频模型目录。 */
import { useEffect, useState } from 'react'
import { api, type MediaModelOption, type MediaModelsCatalog } from '../api'

let cached: MediaModelsCatalog | null = null
let inflight: Promise<MediaModelsCatalog> | null = null

function loadCatalog(): Promise<MediaModelsCatalog> {
  if (cached) return Promise.resolve(cached)
  if (!inflight) {
    inflight = api.mediaModels().then((cat) => {
      cached = cat
      return cat
    })
  }
  return inflight
}

export function useMediaModelsCatalog() {
  const [catalog, setCatalog] = useState<MediaModelsCatalog | null>(cached)

  useEffect(() => {
    let cancelled = false
    loadCatalog()
      .then((cat) => {
        if (!cancelled) setCatalog(cat)
      })
      .catch(() => {
        if (!cancelled) setCatalog(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return catalog
}

/** 当前目录下的视频模型；目录未到时为空。 */
export function catalogVideoModels(catalog: MediaModelsCatalog | null): MediaModelOption[] {
  return catalog?.video_models ?? []
}

/** 当前目录下的图片模型；目录未到时为空。 */
export function catalogImageModels(catalog: MediaModelsCatalog | null): MediaModelOption[] {
  return catalog?.image_models ?? []
}

/** 用目录 label 展示模型名，找不到则显示 id。 */
export function catalogModelLabel(
  modelId: string | undefined | null,
  models: Array<{ id: string; label: string }>,
  fallback = '模型',
): string {
  const id = (modelId || '').trim()
  if (!id) return fallback
  return models.find((m) => m.id === id)?.label || id
}
