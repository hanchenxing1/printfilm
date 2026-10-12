/** 画布空白处双击：弹出新建节点类型菜单 */
import { useEffect, useRef } from 'react'
import { ADD_NODE_OPTIONS, type CanvasNodeKind } from './canvasTypes'

type CanvasPaneAddMenuProps = {
  /** 相对视口的屏幕坐标 */
  screen: { x: number; y: number }
  onSelect: (kind: CanvasNodeKind) => void
  onClose: () => void
}

/** 在双击位置附近展示节点类型列表 */
export function CanvasPaneAddMenu({ screen, onSelect, onClose }: CanvasPaneAddMenuProps) {
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const root = rootRef.current
      if (!root) return
      if (event.target instanceof Node && root.contains(event.target)) return
      onClose()
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('pointerdown', onPointerDown, true)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('pointerdown', onPointerDown, true)
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [onClose])

  const left = Math.min(Math.max(12, screen.x), window.innerWidth - 180)
  const top = Math.min(Math.max(12, screen.y), window.innerHeight - 280)

  return (
    <div
      ref={rootRef}
      className="fc-pane-add-menu"
      style={{ left, top }}
      role="menu"
      aria-label="双击新建节点"
    >
      {ADD_NODE_OPTIONS.map((option) => {
        const Icon = option.icon
        return (
          <button
            key={option.id}
            type="button"
            role="menuitem"
            className="nodrag nopan"
            onClick={(event) => {
              event.stopPropagation()
              onSelect(option.id)
            }}
          >
            <span className="fc-pane-add-menu-icon">
              <Icon size={14} strokeWidth={1.8} />
            </span>
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
