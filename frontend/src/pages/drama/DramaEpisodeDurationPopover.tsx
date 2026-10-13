/** 每集时长选择弹层：1 / 2 / 5 / 10 分钟四档（value 以秒计） */
import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'

/** 预设时长档（秒）：1 / 2 / 5 / 10 分钟 */
export const EPISODE_DURATION_PRESETS: readonly number[] = [60, 120, 300, 600]

type Props = {
  /** 每集目标时长（秒） */
  value: number
  onChange: (seconds: number) => void
  disabled?: boolean
}

// 秒 → 展示文案
function durationLabel(sec: number) {
  return `${Math.round(sec / 60)} 分钟`
}

// 渲染每集时长选择弹层；点击预设即选中并关闭
export function DramaEpisodeDurationPopover({ value, onChange, disabled = false }: Props) {
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    function onDoc(e: MouseEvent) {
      const t = e.target as Node | null
      if (rootRef.current && t && !rootRef.current.contains(t)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  function toggle() {
    if (disabled) return
    setOpen((cur) => !cur)
  }

  function select(sec: number) {
    onChange(sec)
    setOpen(false)
  }

  return (
    <div ref={rootRef} className="drama-duration-popover">
      <button
        type="button"
        className={`drama-agent-opt-trigger${open ? ' is-active' : ''}`}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={toggle}
      >
        <span>每集 {durationLabel(value)}</span>
        <ChevronDown size={13} strokeWidth={2} className={open ? 'is-open' : ''} />
      </button>

      {open ? (
        <div className="drama-ep-count-panel" role="dialog" aria-label="每集时长">
          <p className="drama-ep-count-title">每集时长（驱动正文长度与分镜数量）</p>
          <div className="drama-ep-count-presets">
            {EPISODE_DURATION_PRESETS.map((sec) => (
              <button
                key={sec}
                type="button"
                className={value === sec ? 'is-active' : ''}
                onClick={() => select(sec)}
              >
                {durationLabel(sec)}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
