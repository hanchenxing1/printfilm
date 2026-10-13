/** 分集编辑：全集成片三合一操作（均为订阅功能，默认隐藏，仅订阅 active 用户可见）
 *  ① 全集预览（顺序播放全剧已生成镜头）② 打包全集分镜（ZIP）③ 全集合成成片（逐集服务端合成后拼接） */
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'

import { Loader2, Package, PlayCircle, Scissors, X } from 'lucide-react'

import { api } from '../../api'
import { dramaApi, resolveDramaMediaUrl, type DramaEpisode } from '../../api/drama'
import { fetchMediaBlob, triggerBlobDownload } from '../../lib/clientDownload'
import { listEpisodeComposeClips } from '../../lib/composeEpisodeVideoClient'
import { sanitizeMediaBasename } from '../../lib/canvasNodeMedia'

import JSZip from 'jszip'

type Props = {
  /** 项目全部分集（含 fragments，listEpisodes 返回） */
  episodes: DramaEpisode[]
  /** 页面级 busy（分镜生成中）时禁用 */
  disabled?: boolean
}

type PreviewClip = { epName: string; url: string }

function dayStamp() {
  return new Date().toISOString().slice(0, 10).replace(/-/g, '')
}

// 拷成独立 ArrayBuffer，避免 Uint8Array 视图在 TS 里不能当 BlobPart
function copyToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new ArrayBuffer(bytes.byteLength)
  new Uint8Array(copy).set(bytes)
  return copy
}

// 渲染全集成片三合一按钮组（顶栏右侧）：均订阅可见，非订阅/未登录一律隐藏
export function EpisodeFinalActions({ episodes, disabled = false }: Props) {
  /* 订阅状态：三个按钮默认隐藏，仅 api.subscriptionStatus() active 的用户可见（复用 OutlineEpisodePanel 模式） */
  const [subActive, setSubActive] = useState(false)
  useEffect(() => {
    let cancelled = false
    api
      .subscriptionStatus()
      .then((s) => {
        if (!cancelled) setSubActive(Boolean(s?.active))
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  /* 全集口径：按集顺序展平全部已生成分镜 */
  const allTargets = useMemo(
    () => episodes.filter((ep) => listEpisodeComposeClips(ep.fragments ?? []).length > 0),
    [episodes],
  )
  const previewList = useMemo<PreviewClip[]>(() => {
    const list: PreviewClip[] = []
    for (const ep of allTargets) {
      const epName = ep.name || `第${ep.id}集`
      for (const clip of listEpisodeComposeClips(ep.fragments ?? [])) {
        list.push({ epName, url: clip.url })
      }
    }
    return list
  }, [allTargets])
  const allClipsTotal = previewList.length
  const noAllClips = allTargets.length === 0

  /* 全集预览弹层（顺序播放，零下载成本） */
  const [previewOpen, setPreviewOpen] = useState(false)
  const [previewIndex, setPreviewIndex] = useState(0)
  const [previewNote, setPreviewNote] = useState('')

  /* zipBusy 打包全集分镜中；zipProgress 已拉取 x/y */
  const [zipBusy, setZipBusy] = useState(false)
  const [zipProgress, setZipProgress] = useState<{ done: number; total: number } | null>(null)
  const [zipError, setZipError] = useState('')

  /* composeAllBusy 全集合成中；composeAllProgress 已合成 x/y 集 */
  const [composeAllBusy, setComposeAllBusy] = useState(false)
  const [composeAllProgress, setComposeAllProgress] = useState<{
    done: number
    total: number
    phase: 'server' | 'concat'
  } | null>(null)
  const [composeAllError, setComposeAllError] = useState('')

  const anyBusy = zipBusy || composeAllBusy
  const locked = disabled || anyBusy

  // ① 全集预览：按集顺序播放全部已生成镜头（跳过未生成），不下载不占服务端
  function openPreview() {
    if (previewList.length === 0 || anyBusy) return
    setPreviewIndex(0)
    setPreviewNote('')
    setPreviewOpen(true)
  }

  // ② 打包下载全集分镜：遍历 listEpisodes 全部分集，逐镜拉取后压缩为 ZIP（订阅用户）
  async function handleDownloadAllClipsZip() {
    if (noAllClips || anyBusy) return
    setZipError('')
    setZipBusy(true)
    setZipProgress({ done: 0, total: allClipsTotal })
    try {
      const zip = new JSZip()
      const used = new Set<string>()
      let done = 0
      for (let e = 0; e < allTargets.length; e += 1) {
        const ep = allTargets[e]
        const clips = listEpisodeComposeClips(ep.fragments ?? [])
        const epBase = sanitizeMediaBasename(ep.name || `第${e + 1}集`)
        for (let ci = 0; ci < clips.length; ci += 1) {
          const clip = clips[ci]
          const blob = await fetchMediaBlob(clip.url)
          let name = `${epBase}_分镜${ci + 1}.mp4`
          if (used.has(name)) name = `${epBase}_分镜${ci + 1}_${done + 1}.mp4`
          used.add(name)
          zip.file(name, blob)
          done += 1
          setZipProgress({ done, total: allClipsTotal })
        }
      }
      const out = await zip.generateAsync({ type: 'blob', compression: 'STORE' })
      triggerBlobDownload(out, `全部分镜_${dayStamp()}.zip`)
    } catch (err) {
      setZipError(err instanceof Error ? err.message : '打包下载失败')
    } finally {
      setZipBusy(false)
      setZipProgress(null)
    }
  }

  // ③ 全集合成成片：逐集服务端统一重编码，再在浏览器里拼成整部成片并下载（订阅用户）
  async function handleComposeAll() {
    if (noAllClips || anyBusy) return
    setComposeAllError('')
    setComposeAllBusy(true)
    setComposeAllProgress({ done: 0, total: allTargets.length, phase: 'server' })
    try {
      const parts: Uint8Array[] = []
      const names: string[] = []
      for (let i = 0; i < allTargets.length; i += 1) {
        const ep = allTargets[i]
        const clips = listEpisodeComposeClips(ep.fragments ?? [])
        const result = await dramaApi.composeEpisode(ep.id, clips.map((c) => c.id))
        const url = resolveDramaMediaUrl(result.video_url)
        if (!url) throw new Error(`第 ${i + 1} 集合成未返回可下载地址`)
        const blob = await fetchMediaBlob(url)
        parts.push(new Uint8Array(await blob.arrayBuffer()))
        names.push(ep.name || `第${i + 1}集`)
        setComposeAllProgress({ done: i + 1, total: allTargets.length, phase: 'server' })
      }

      setComposeAllProgress({ done: allTargets.length, total: allTargets.length, phase: 'concat' })
      const { concatMp4, isMp4, mp4Compat } = await import('mp4cat')
      for (let i = 0; i < parts.length; i += 1) {
        if (!isMp4(parts[i])) {
          throw new Error(`${names[i]} 不是可拼接的 MP4`)
        }
      }
      if (parts.length === 1) {
        triggerBlobDownload(
          new Blob([copyToArrayBuffer(parts[0])], { type: 'video/mp4' }),
          `全剧成片_${dayStamp()}.mp4`,
        )
        return
      }
      const compat = mp4Compat(parts, { names })
      if (!compat.ok) {
        throw new Error(
          `各集合片规格不一致，无法拼接（${compat.reason || 'SPS/PPS 不同'}）。请统一全剧的画面风格、比例与清晰度后重试。`,
        )
      }
      const merged = concatMp4(parts)
      triggerBlobDownload(
        new Blob([copyToArrayBuffer(merged)], { type: 'video/mp4' }),
        `全剧成片_${dayStamp()}.mp4`,
      )
    } catch (err) {
      setComposeAllError(err instanceof Error ? err.message : '全集合成失败')
    } finally {
      setComposeAllBusy(false)
      setComposeAllProgress(null)
    }
  }

  const allHint = noAllClips ? '全剧还没有分镜视频' : `共 ${allTargets.length} 集 ${allClipsTotal} 个分镜`

  const activeError = zipError || composeAllError

  return (
    <>
      {subActive ? (
        <div className="drama-ep-final-actions">
          <button
            type="button"
            className="drama-ep-btn-ghost drama-ep-final-btn"
            disabled={locked || noAllClips}
            title={allHint || '按集顺序播放全剧已生成镜头（订阅功能）'}
            onClick={openPreview}
          >
            <PlayCircle size={14} strokeWidth={1.8} />
            全集预览
          </button>
          <button
            type="button"
            className="drama-ep-btn-ghost drama-ep-final-btn"
            disabled={locked || noAllClips}
            title={allHint || '把全剧所有分镜视频打包成一个 ZIP 下载'}
            onClick={() => void handleDownloadAllClipsZip()}
          >
            {zipBusy ? (
              <Loader2 size={14} className="drama-ep-compose-spin" />
            ) : (
              <Package size={14} strokeWidth={1.8} />
            )}
            {zipBusy && zipProgress ? `打包 ${zipProgress.done}/${zipProgress.total}` : '打包全集分镜'}
          </button>
          <button
            type="button"
            className="drama-ep-btn-dark drama-ep-final-btn"
            disabled={locked || noAllClips}
            title={allHint || '逐集服务端合成后拼成整部成片并下载'}
            onClick={() => void handleComposeAll()}
          >
            {composeAllBusy ? (
              <Loader2 size={14} className="drama-ep-compose-spin" />
            ) : (
              <Scissors size={14} strokeWidth={1.8} />
            )}
            {composeAllBusy && composeAllProgress
              ? composeAllProgress.phase === 'server'
                ? `合成 ${composeAllProgress.done}/${composeAllProgress.total} 集`
                : '拼接中…'
              : '全集合成成片'}
          </button>
        </div>
      ) : null}

      {activeError ? <p className="drama-ep-final-error">{activeError}</p> : null}

      {previewOpen && previewList[previewIndex] ? (
        createPortal(
          <div className="drama-ep-final-preview" role="dialog" aria-label="全集预览">
          <div className="drama-ep-final-preview-head">
            <span>
              全集预览 · {allTargets.length} 集 {allClipsTotal} 镜 · 正在播放第 {previewIndex + 1} / {allClipsTotal}（
              {previewList[previewIndex].epName}）
            </span>
            <button
              type="button"
              className="drama-ep-final-preview-close"
              aria-label="关闭预览"
              onClick={() => setPreviewOpen(false)}
            >
              <X size={16} strokeWidth={2} />
            </button>
          </div>
          <video
            key={previewIndex}
            src={previewList[previewIndex].url}
            controls
            autoPlay
            playsInline
            onEnded={() => {
              if (previewIndex < previewList.length - 1) {
                setPreviewIndex(previewIndex + 1)
              } else {
                setPreviewNote('全集播放完毕')
              }
            }}
          />
          <p className="drama-ep-final-preview-tip">
            {previewNote || `未生成的镜头自动跳过；留存文件请用「全集合成成片」（订阅功能）。`}
          </p>
          </div>,
          document.body,
        )
      ) : null}
    </>
  )
}
