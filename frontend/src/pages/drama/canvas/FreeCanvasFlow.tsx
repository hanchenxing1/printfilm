/** React Flow 无限画布核心 */
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import {
  Background,
  MiniMap,
  ReactFlow,
  useReactFlow,
  type Connection,
  type Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { CanvasAssetNode } from './CanvasAssetNode'
import { CanvasPaneAddMenu } from './CanvasPaneAddMenu'
import { useCanvasStore } from './CanvasStore'
import { CANVAS_NODE_SIZE, CANVAS_SNAP_GRID, type CanvasNodeKind } from './canvasTypes'

type FreeCanvasFlowProps = {
  projectId: number
}

type PaneAddMenuState = {
  screen: { x: number; y: number }
  flow: { x: number; y: number }
}

/** 渲染 React Flow 无限画布 */
export function FreeCanvasFlow({ projectId }: FreeCanvasFlowProps) {
  const nodeTypes = useMemo(() => ({ asset: CanvasAssetNode }), [])
  const {
    nodes,
    edges,
    snapToGrid,
    showMinimap,
    onNodesChange,
    onEdgesChange,
    onConnect,
    pushSnapshot,
    focusNodeId,
    clearFocusNode,
    addNodeOfKind,
  } = useCanvasStore()
  const { fitView, setCenter, getNode, screenToFlowPosition } = useReactFlow()
  const wrapperRef = useRef<HTMLDivElement>(null)
  const dragSnapshotPushed = useRef(false)
  // paneAddMenu 空白双击后的新建菜单
  const [paneAddMenu, setPaneAddMenu] = useState<PaneAddMenuState | null>(null)

  /* 聚焦文件夹选中的节点 */
  useEffect(() => {
    if (!focusNodeId) return
    const node = getNode(focusNodeId)
    if (!node) {
      clearFocusNode()
      return
    }
    const w = 200
    const h = 240
    void setCenter(node.position.x + w / 2, node.position.y + h / 2, {
      zoom: 1,
      duration: 280,
    })
    clearFocusNode()
  }, [focusNodeId, getNode, setCenter, clearFocusNode])

  const isValidConnection = useCallback((connection: Connection | Edge) => {
    return connection.source !== connection.target
  }, [])

  const handlePaneClick = useCallback(() => {
    wrapperRef.current?.focus()
    setPaneAddMenu(null)
  }, [])

  /** 空白处双击：在落点弹出新建节点菜单 */
  const handlePaneDoubleClick = useCallback(
    (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (!target) return
      if (
        target.closest(
          '.react-flow__node, .react-flow__edge, .react-flow__controls, .react-flow__minimap, .fc-pane-add-menu, .fc-generate-panel, button, input, textarea, [contenteditable="true"]',
        )
      ) {
        return
      }
      if (!target.closest('.react-flow__pane') && !target.closest('.react-flow__viewport')) {
        return
      }
      event.preventDefault()
      const flow = screenToFlowPosition({ x: event.clientX, y: event.clientY })
      setPaneAddMenu({
        screen: { x: event.clientX, y: event.clientY },
        flow,
      })
    },
    [screenToFlowPosition],
  )

  /** 从双击菜单创建节点，居中落在点击位置 */
  const handlePaneAddSelect = useCallback(
    (kind: CanvasNodeKind) => {
      if (!paneAddMenu) return
      const size = CANVAS_NODE_SIZE[kind]
      const position = {
        x: paneAddMenu.flow.x - size.width / 2,
        y: paneAddMenu.flow.y - size.height / 2,
      }
      setPaneAddMenu(null)
      void addNodeOfKind(kind, position)
    },
    [addNodeOfKind, paneAddMenu],
  )

  /* 拖拽开始时压入历史快照（同一拖拽只压一次） */
  const handleNodeDragStart = useCallback(() => {
    if (!dragSnapshotPushed.current) {
      pushSnapshot()
      dragSnapshotPushed.current = true
    }
  }, [pushSnapshot])

  const handleNodeDragStop = useCallback(() => {
    dragSnapshotPushed.current = false
  }, [])

  /* 保证容器可聚焦；加载后有节点时适应视图 */
  useEffect(() => {
    wrapperRef.current?.focus()
  }, [projectId])

  const fittedRef = useRef(false)
  useEffect(() => {
    fittedRef.current = false
  }, [projectId])

  useEffect(() => {
    if (fittedRef.current || nodes.length === 0) return
    fittedRef.current = true
    void fitView({ padding: 0.2 })
  }, [nodes.length, fitView])

  return (
    <div
      ref={wrapperRef}
      tabIndex={0}
      className="free-canvas-flow"
      style={{ width: '100%', height: '100%', outline: 'none' }}
      data-project-id={projectId}
      onDoubleClick={handlePaneDoubleClick}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeDragStart={handleNodeDragStart}
        onNodeDragStop={handleNodeDragStop}
        isValidConnection={isValidConnection}
        onPaneClick={handlePaneClick}
        deleteKeyCode={['Backspace', 'Delete']}
        snapToGrid={snapToGrid}
        snapGrid={CANVAS_SNAP_GRID}
        minZoom={0.2}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: 'default' }}
      >
        <Background gap={CANVAS_SNAP_GRID[0]} size={1.2} color="#cbd5e1" />
        {showMinimap ? (
          <MiniMap
            pannable
            zoomable
            style={{ bottom: 20, right: 20, borderRadius: 12, overflow: 'hidden' }}
          />
        ) : null}
      </ReactFlow>
      {paneAddMenu ? (
        <CanvasPaneAddMenu
          screen={paneAddMenu.screen}
          onSelect={handlePaneAddSelect}
          onClose={() => setPaneAddMenu(null)}
        />
      ) : null}
    </div>
  )
}
