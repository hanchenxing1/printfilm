/** 按项目批量入队角色/场景/道具参考图（只走已有生图接口，不注册外部账号） */
import { api, type BillingPreflight } from '../api'
import { dramaApi, type DramaAsset, type DramaProject } from '../api/drama'
import { handleBillingError, isBillingError } from './billingError'
import { dialog } from './dialog'
import { dramaAssetNeedsImageGeneration } from './dramaAssetImage'
import {
  defaultOptionsForAssetKind,
  type ImageGenerationOptions,
} from './dramaGenerationOptions'
import { enqueueDramaImageGen, isDramaAssetImageBusy } from './dramaImageGenQueue'
import { filterDramaLibraryAssets } from './dramaLibraryAssets'
import { readVisualPrompt } from './dramaVisualPrompt'

export type BatchAssetImageResult = {
  queued: number
  skipped: number
  cancelled: boolean
}

export type EnsureAssetImagesBeforeVideoResult = {
  proceeded: boolean
  queued: number
  cancelled: boolean
}

function imageStyleIdOf(project: DramaProject | null): string {
  const fromScript = (project?.script?.params || {}).image_style_id
  const fromProject = (project?.params || {}).image_style_id
  return String(fromScript || fromProject || '')
}

function isVisualLibraryAsset(asset: DramaAsset): boolean {
  const kind = (asset.type || '').toLowerCase()
  return kind === 'character' || kind === 'scene' || kind === 'prop'
}

async function ensureImageGenBalance(count: number): Promise<BillingPreflight | null> {
  try {
    return await api.billingPreflight({
      domain: 'drama',
      task_type: 'asset_image',
      count,
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err || '')
    if (isBillingError(message)) return null
    if (await handleBillingError(err)) return null
    throw err instanceof Error ? err : new Error(message || '余额校验失败')
  }
}

async function loadVisualAssets(projectId: number, project: DramaProject | null): Promise<DramaAsset[]> {
  let list = filterDramaLibraryAssets(
    await dramaApi.listAssets(projectId, { libraryOnly: true }),
  ).filter(isVisualLibraryAsset)
  if (list.length === 0 && project?.script?.summary) {
    const seeded = await dramaApi.seedAssets(projectId)
    list = filterDramaLibraryAssets(seeded?.assets || []).filter(isVisualLibraryAsset)
    if (list.length === 0) {
      list = filterDramaLibraryAssets(
        await dramaApi.listAssets(projectId, { libraryOnly: true }),
      ).filter(isVisualLibraryAsset)
    }
  }
  return list
}

export async function enqueueProjectAssetImages(opts: {
  projectId: number
  /** 已有图也重新生成 */
  forceRegen?: boolean
  /** 已齐全时直接返回，不弹「全部重新生成」 */
  skipIfComplete?: boolean
  /** 跳过费用确认框（调用方已确认） */
  skipConfirm?: boolean
  title: string
  confirmVerb: string
  onAssetUpdate?: (asset: DramaAsset) => void
}): Promise<BatchAssetImageResult> {
  const project = await dramaApi.getProject(opts.projectId)
  const assets = await loadVisualAssets(opts.projectId, project)
  const idle = assets.filter((asset) => !isDramaAssetImageBusy(asset.id))
  const missing = idle.filter((asset) => dramaAssetNeedsImageGeneration(asset))
  let targets = opts.forceRegen ? idle : missing

  if (!opts.forceRegen && missing.length === 0 && idle.length > 0) {
    if (opts.skipIfComplete) {
      return { queued: 0, skipped: assets.length, cancelled: false }
    }
    const regen = await dialog.confirm({
      title: opts.title,
      message: `「${project.title}」的 ${idle.length} 个视觉资产都已有参考图。是否全部重新生成？`,
      confirmText: '全部重新生成',
    })
    if (!regen) return { queued: 0, skipped: assets.length, cancelled: true }
    targets = idle
  }

  if (targets.length === 0) {
    throw new Error(assets.length === 0 ? '该项目还没有可生成的角色/场景/道具' : '没有可生成的资产（可能都在生成中）')
  }

  const pre = await ensureImageGenBalance(targets.length)
  if (!pre) return { queued: 0, skipped: assets.length, cancelled: true }

  if (!opts.skipConfirm) {
    const unitYuan = pre.unit_estimate_yuan ?? pre.unit_estimate_fen / 100
    const totalYuan = pre.requested_total_yuan ?? pre.requested_total_fen / 100
    const balanceYuan = pre.balance_yuan ?? pre.balance_fen / 100
    const ok = await dialog.confirm({
      title: opts.title,
      message:
        `将为「${project.title}」入队 ${targets.length} 个资产参考图（角色/场景/道具，并行提交）。\n\n` +
        `每张预扣约 ¥${unitYuan.toFixed(2)}，本次合计约 ¥${totalYuan.toFixed(2)}（当前余额 ¥${balanceYuan.toFixed(2)}；结束后按实际上游用量多退少补）。\n\n是否${opts.confirmVerb}？`,
      confirmText: opts.confirmVerb,
    })
    if (!ok) return { queued: 0, skipped: assets.length, cancelled: true }
  }

  const styleId = imageStyleIdOf(project)
  const tasks = targets.map((asset) =>
    enqueueDramaImageGen({
      projectId: opts.projectId,
      assetId: asset.id,
      assetName: asset.name || undefined,
      assetType: asset.type,
      prompt: readVisualPrompt(asset),
      options: {
        ...defaultOptionsForAssetKind(asset.type),
        image_style_id: styleId || undefined,
      } satisfies Partial<ImageGenerationOptions>,
      onAssetUpdate: opts.onAssetUpdate,
    }),
  )
  const results = await Promise.allSettled(tasks)
  const failed = results.find((row) => row.status === 'rejected')
  if (failed && failed.status === 'rejected') {
    throw failed.reason instanceof Error ? failed.reason : new Error(String(failed.reason || '入队失败'))
  }
  return { queued: targets.length, skipped: assets.length - targets.length, cancelled: false }
}

/** 一键生成视频前：资产库无图或不全则先生成全部参考图，完成后再放行 */
export async function ensureProjectAssetImagesBeforeVideo(opts: {
  projectId: number
  onAssetUpdate?: (asset: DramaAsset) => void
}): Promise<EnsureAssetImagesBeforeVideoResult> {
  const project = await dramaApi.getProject(opts.projectId)
  const assets = await loadVisualAssets(opts.projectId, project)
  if (assets.length === 0) {
    await dialog.alert({
      title: '请先完善资产库',
      message: '当前没有角色/场景/道具。请先在资产库添加或生成资产，再一键生成视频。',
    })
    return { proceeded: false, queued: 0, cancelled: true }
  }

  const missing = assets.filter((asset) => dramaAssetNeedsImageGeneration(asset))
  const busyMissing = missing.filter((asset) => isDramaAssetImageBusy(asset.id))
  const idleMissing = missing.filter((asset) => !isDramaAssetImageBusy(asset.id))
  if (missing.length === 0) {
    return { proceeded: true, queued: 0, cancelled: false }
  }
  if (idleMissing.length === 0 && busyMissing.length > 0) {
    await dialog.alert({
      title: '参考图生成中',
      message: `还有 ${busyMissing.length} 张参考图正在生成。请待完成后再次点击生成视频。`,
    })
    return { proceeded: false, queued: 0, cancelled: true }
  }

  const names = idleMissing.map((asset) => asset.name || `#${asset.id}`)
  const shown = names.slice(0, 8).join('、')
  const extra = names.length > 8 ? ` 等 ${names.length} 个` : ''
  const pre = await ensureImageGenBalance(idleMissing.length)
  if (!pre) return { proceeded: false, queued: 0, cancelled: true }
  const unitYuan = pre.unit_estimate_yuan ?? pre.unit_estimate_fen / 100
  const totalYuan = pre.requested_total_yuan ?? pre.requested_total_fen / 100
  const balanceYuan = pre.balance_yuan ?? pre.balance_fen / 100
  const ok = await dialog.confirm({
    title: '参考图不完整',
    message:
      `资产库共 ${assets.length} 个角色/场景/道具，其中 ${idleMissing.length} 个尚无参考图` +
      (shown ? `（${shown}${extra}）` : '') +
      `。将先生成这些参考图，完成后再生成分镜视频。\n\n` +
      `每张预扣约 ¥${unitYuan.toFixed(2)}，本次合计约 ¥${totalYuan.toFixed(2)}（当前余额 ¥${balanceYuan.toFixed(2)}）。`,
    confirmText: '先生成参考图',
  })
  if (!ok) return { proceeded: false, queued: 0, cancelled: true }

  // 直接入队缺图资产并等待完成；部分失败时仍放行进分镜视频，仅提示未成功的数量
  const styleId = imageStyleIdOf(project)
  const results = await Promise.allSettled(
    idleMissing.map((asset) =>
      enqueueDramaImageGen({
        projectId: opts.projectId,
        assetId: asset.id,
        assetName: asset.name || undefined,
        assetType: asset.type,
        prompt: readVisualPrompt(asset),
        options: {
          ...defaultOptionsForAssetKind(asset.type),
          image_style_id: styleId || undefined,
        } satisfies Partial<ImageGenerationOptions>,
        onAssetUpdate: opts.onAssetUpdate,
      }),
    ),
  )
  const succeeded = results.filter((r) => r.status === 'fulfilled').length
  const failedCount = idleMissing.length - succeeded
  const queued = idleMissing.length
  if (failedCount > 0) {
    await dialog.alert({
      title: '部分参考图生成失败',
      message: `${succeeded}/${idleMissing.length} 张参考图生成成功，${failedCount} 张失败。将带着现有参考图继续生成分镜视频；失败资产可在资产库重新生成。`,
    })
  }
  return { proceeded: true, queued, cancelled: false }
}
