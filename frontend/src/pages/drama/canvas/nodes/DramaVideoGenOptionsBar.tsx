/** 画布视频节点：风格 / Seedance 模型 / 时长 / 比例清晰度 */
import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { BarChart3, ChevronDown, RectangleVertical, Smile, Timer } from 'lucide-react'
import {
  getImageStyleLabel,
  IMAGE_STYLE_OPTIONS,
} from '../../../../lib/dramaImageStyles'
import { DramaImageStylePreviewImg } from '../../../../components/drama/DramaImageStylePreviewImg'
import { DramaMediaModelPicker } from '../../../../components/drama/DramaMediaModelPicker'
import {
  aspectRatiosForVideoModel,
  clampVideoAspectRatioForModel,
  clampVideoDuration,
  clampVideoResolutionForModel,
  durationBoundsForModel,
  formatVideoOutputLabel,
  hasKnownVideoModelResolutions,
  resolutionsForModel,
  VIDEO_DURATION_PRESETS,
  type VideoAspectRatio,
  type VideoGenerationOptions,
  type VideoResolution,
} from '../../../../lib/dramaVideoGenerationOptions'
import {
  catalogModelLabel,
  catalogVideoModels,
  useMediaModelsCatalog,
} from '../../../../hooks/useMediaModelsCatalog'
import './dramaImageGenOptions.css'

type DramaVideoGenOptionsBarProps = {
  value: VideoGenerationOptions
  onChange: (next: VideoGenerationOptions) => void
  disabled?: boolean
}

type OpenPanel = 'style' | 'model' | 'duration' | 'output' | null

/** 渲染视频生成选项条 */
export function DramaVideoGenOptionsBar({
  value,
  onChange,
  disabled = false,
}: DramaVideoGenOptionsBarProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState<OpenPanel>(null)
  const catalog = useMediaModelsCatalog()
  const videoModels = catalogVideoModels(catalog)

  useEffect(() => {
    // 目录到达后，把旧 Kie/方舟 id 换成后台默认视频模型
    if (!catalog || disabled) return
    const ids = videoModels.map((m) => m.id)
    if (!ids.length) return
    if (value.model_id && ids.includes(value.model_id)) return
    const next = catalog.defaults.video_model || ids[0]
    if (next && next !== value.model_id) {
      onChange({
        ...value,
        model_id: next,
        resolution: clampVideoResolutionForModel(next, value.resolution, catalog, videoModels),
        aspect_ratio: clampVideoAspectRatioForModel(next, value.aspect_ratio, catalog, videoModels),
        duration_sec: clampVideoDuration(value.duration_sec, next, catalog, videoModels),
      })
    }
  }, [catalog, disabled])

  useEffect(() => {
    // 换模型后：清晰度 / 比例 / 时长钳到允许范围（须已知目录行，避免 SAFE 误写）
    if (disabled) return
    if (!hasKnownVideoModelResolutions(value.model_id, catalog, videoModels)) return
    const nextRes = clampVideoResolutionForModel(
      value.model_id,
      value.resolution,
      catalog,
      videoModels,
    )
    const nextAspect = clampVideoAspectRatioForModel(
      value.model_id,
      value.aspect_ratio,
      catalog,
      videoModels,
    )
    const nextDur = clampVideoDuration(value.duration_sec, value.model_id, catalog, videoModels)
    if (
      nextRes !== value.resolution ||
      nextAspect !== value.aspect_ratio ||
      nextDur !== value.duration_sec
    ) {
      onChange({
        ...value,
        resolution: nextRes,
        aspect_ratio: nextAspect,
        duration_sec: nextDur,
      })
    }
  }, [value.model_id, catalog, disabled])

  const resolutionOptions = resolutionsForModel(value.model_id, catalog, videoModels)
  const aspectOptions = aspectRatiosForVideoModel(value.model_id, catalog, videoModels)
  const durationBounds = durationBoundsForModel(value.model_id, catalog, videoModels)
  const durationPresets = VIDEO_DURATION_PRESETS.filter(
    (sec) => sec >= durationBounds.min && sec <= durationBounds.max,
  )

  useEffect(() => {
    if (!open) return
    function onDoc(e: Event) {
      const target = e.target as Node | null
      if (rootRef.current && target && !rootRef.current.contains(target)) {
        setOpen(null)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  const stop = (e: MouseEvent) => {
    e.stopPropagation()
  }

  const styleLabel = getImageStyleLabel(value.image_style_id) || '风格'
  const modelLabel = catalogModelLabel(value.model_id, videoModels, '视频模型')
  const outputLabel = formatVideoOutputLabel(value.aspect_ratio, value.resolution)

  return (
    <div ref={rootRef} className="fc-gen-opts" onMouseDown={stop} onPointerDown={stop}>
      <div className="fc-gen-opts-triggers">
        <button
          type="button"
          className={`fc-gen-opt-btn${open === 'style' || value.image_style_id ? ' active' : ''}`}
          disabled={disabled}
          onClick={() => setOpen((c) => (c === 'style' ? null : 'style'))}
        >
          <Smile size={14} strokeWidth={1.8} />
          <span className="fc-gen-opt-label">{styleLabel}</span>
          <ChevronDown size={12} />
        </button>
        <button
          type="button"
          className={`fc-gen-opt-btn${open === 'model' ? ' active' : ''}`}
          disabled={disabled}
          onClick={() => setOpen((c) => (c === 'model' ? null : 'model'))}
        >
          <BarChart3 size={14} strokeWidth={1.8} />
          <span className="fc-gen-opt-label">{modelLabel}</span>
          <ChevronDown size={12} />
        </button>
        <button
          type="button"
          className={`fc-gen-opt-btn${open === 'duration' ? ' active' : ''}`}
          disabled={disabled}
          onClick={() => setOpen((c) => (c === 'duration' ? null : 'duration'))}
        >
          <Timer size={14} strokeWidth={1.8} />
          <span className="fc-gen-opt-label">{value.duration_sec}s</span>
          <ChevronDown size={12} />
        </button>
        <button
          type="button"
          className={`fc-gen-opt-btn${open === 'output' ? ' active' : ''}`}
          disabled={disabled}
          onClick={() => setOpen((c) => (c === 'output' ? null : 'output'))}
        >
          <RectangleVertical size={14} strokeWidth={1.8} />
          <span className="fc-gen-opt-label">{outputLabel}</span>
          <ChevronDown size={12} />
        </button>
      </div>

      {open === 'style' ? (
        <div className="fc-gen-opt-panel fc-gen-style-panel" role="dialog" aria-label="视频风格">
          <div className="fc-gen-opt-panel-title">视频风格</div>
          <div className="fc-gen-style-grid">
            {IMAGE_STYLE_OPTIONS.map((opt) => {
              const selected = value.image_style_id === opt.id
              return (
                <button
                  key={opt.id}
                  type="button"
                  className={`fc-gen-style-card${selected ? ' selected' : ''}`}
                  onClick={() => {
                    onChange({ ...value, image_style_id: opt.id })
                    setOpen(null)
                  }}
                >
                  <DramaImageStylePreviewImg styleId={opt.id} alt={opt.label} loading="lazy" />
                  <span>{opt.label}</span>
                </button>
              )
            })}
          </div>
        </div>
      ) : null}

      {open === 'model' ? (
        <div className="fc-gen-opt-panel" role="dialog" aria-label="视频模型">
          <div className="fc-gen-opt-panel-title">模型</div>
          <DramaMediaModelPicker
            models={videoModels}
            selectedId={value.model_id}
            onSelect={(m) => {
              const nextRes = clampVideoResolutionForModel(
                m.id,
                value.resolution,
                catalog,
                videoModels,
              )
              const nextAspect = clampVideoAspectRatioForModel(
                m.id,
                value.aspect_ratio,
                catalog,
                videoModels,
              )
              const nextDur = clampVideoDuration(value.duration_sec, m.id, catalog, videoModels)
              onChange({
                ...value,
                model_id: m.id,
                resolution: nextRes,
                aspect_ratio: nextAspect,
                duration_sec: nextDur,
              })
              setOpen(null)
            }}
          />
        </div>
      ) : null}

      {open === 'duration' ? (
        <div className="fc-gen-opt-panel" role="dialog" aria-label="视频时长">
          <div className="fc-gen-opt-panel-title">时长</div>
          <div className="fc-gen-chip-row">
            {durationPresets.map((sec) => (
              <button
                key={sec}
                type="button"
                className={`fc-gen-chip${value.duration_sec === sec ? ' selected' : ''}`}
                onClick={() => {
                  onChange({
                    ...value,
                    duration_sec: clampVideoDuration(sec, value.model_id, catalog, videoModels),
                  })
                  setOpen(null)
                }}
              >
                {sec}s
              </button>
            ))}
          </div>
          <label className="fc-gen-duration-custom">
            自定义（{durationBounds.min}–{durationBounds.max}s）
            <input
              type="number"
              min={durationBounds.min}
              max={durationBounds.max}
              value={value.duration_sec}
              disabled={disabled}
              onChange={(e) =>
                onChange({
                  ...value,
                  duration_sec: clampVideoDuration(
                    Number(e.target.value),
                    value.model_id,
                    catalog,
                    videoModels,
                  ),
                })
              }
            />
          </label>
        </div>
      ) : null}

      {open === 'output' ? (
        <div className="fc-gen-opt-panel" role="dialog" aria-label="画幅与清晰度">
          <div className="fc-gen-opt-panel-title">比例</div>
          <div className="fc-gen-chip-row">
            {aspectOptions.map((ratio) => (
              <button
                key={ratio}
                type="button"
                className={`fc-gen-chip${value.aspect_ratio === ratio ? ' selected' : ''}`}
                onClick={() => onChange({ ...value, aspect_ratio: ratio as VideoAspectRatio })}
              >
                {ratio}
              </button>
            ))}
          </div>
          <div className="fc-gen-opt-panel-title" style={{ marginTop: 10 }}>
            清晰度
          </div>
          <div className="fc-gen-chip-row">
            {resolutionOptions.map((res) => (
              <button
                key={res}
                type="button"
                className={`fc-gen-chip${value.resolution === res ? ' selected' : ''}`}
                onClick={() => {
                  onChange({ ...value, resolution: res as VideoResolution })
                  setOpen(null)
                }}
              >
                {res}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
