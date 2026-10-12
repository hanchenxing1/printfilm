/** 旧分集中间页：自动跳到首集分镜编辑 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import AppShell from '../../components/layout/AppShell'
import { isCanvasWorkflow } from '../../lib/dramaWorkflow'
import { resolveStoryboardPath } from '../../lib/dramaStoryboardNav'
import { dramaApi } from '../../api/drama'
import RequireAuth from './RequireAuth'
import './drama.css'

export default function EpisodesPage() {
  return (
    <RequireAuth>
      <EpisodesRedirect />
    </RequireAuth>
  )
}

// 加载后跳转首集编辑，不再展示中间页
function EpisodesRedirect() {
  const { projectId } = useParams()
  const pid = Number(projectId)
  const navigate = useNavigate()
  const [error, setError] = useState('')

  useEffect(() => {
    if (!Number.isFinite(pid) || pid <= 0) return
    let cancelled = false
    ;(async () => {
      try {
        const p = await dramaApi.getProject(pid)
        if (cancelled) return
        if (isCanvasWorkflow(p)) {
          navigate(`/drama/projects/${pid}/canvas`, { replace: true })
          return
        }
        const path = await resolveStoryboardPath(pid)
        if (!cancelled) navigate(path, { replace: true })
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : '无法进入分镜')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [pid, navigate])

  return (
    <AppShell active="drama" flush>
      <div className="drama-workspace-status">
        {error || '正在进入分镜…'}
      </div>
    </AppShell>
  )
}
