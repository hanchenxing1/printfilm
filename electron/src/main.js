/**
 * PRINTFILM 单机开源版 — Electron 主进程
 *
 * 架构：
 *   - 启动时 spawn 内嵌 Python (uvicorn) 后端（同包目录下 backend/）
 *   - 数据目录 %APPDATA%/PRINTFILM-standalone/data
 *   - 打开 http://127.0.0.1:<port>/ 同源前端
 *   - 关闭时杀 Python 子进程
 *
 * 环境变量注入给 Python 子进程：
 *   - PRINFFILM_DATA_DIR -> 用户数据目录
 *   - FFMPEG_PATH        -> 包内 ffmpeg.exe 或系统 PATH
 *   - AGNES_API_KEY / AGNES_API_KEYS -> 用户保存的 key（可选）
 */
const { app, BrowserWindow, Menu, shell, dialog, session } = require('electron')
const path = require('path')
const fs = require('fs')
const { spawn, execSync } = require('child_process')

const BG = '#0D1218'
const PORT = 8377 // 避免与 8000/8001 冲突

// ---- 资源路径（开发态 vs 打包态） ----
// 开发态：__dirname = electron/src，backend 在 electron/../backend
// 打包态：extraResources backend 落在 resources/backend
const isPackaged = app.isPackaged
const backendDir = isPackaged
  ? path.join(process.resourcesPath, 'backend')
  : path.join(__dirname, '..', '..', 'backend')
const resourceRoot = isPackaged ? process.resourcesPath : path.join(__dirname, '..')
const parentRoot = isPackaged ? process.resourcesPath : path.join(__dirname, '..', '..')
const pythonExe =
  process.platform === 'win32'
    ? path.join(parentRoot, 'python', 'python.exe')
    : path.join(parentRoot, 'python', 'bin', 'python3')
const ffmpegExe =
  process.platform === 'win32'
    ? path.join(parentRoot, 'ffmpeg', 'ffmpeg.exe')
    : path.join(parentRoot, 'ffmpeg', 'ffmpeg')

let pyProc = null
let mainWindow = null

function log(msg) {
  console.log('[printfilm-standalone]', msg)
}

// ---- 启动内嵌 Python 后端 ----
async function waitPort(port, ms = 30000) {
  const deadline = Date.now() + ms
  while (Date.now() < deadline) {
    try {
      const http = require('http')
      const ok = await new Promise((resolve) => {
        const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
          res.resume()
          resolve(res.statusCode === 200)
        })
        req.on('error', () => resolve(false))
      })
      if (ok) return true
    } catch {}
    await new Promise((r) => setTimeout(r, 500))
  }
  return false
}

function startBackend() {
  const dataDir = path.join(app.getPath('userData'), 'data')
  fs.mkdirSync(dataDir, { recursive: true })

  const env = {
    ...process.env,
    PRINFFILM_DATA_DIR: dataDir,
    FFMPEG_PATH: fs.existsSync(ffmpegExe) ? ffmpegExe : process.env.FFMPEG_PATH || 'ffmpeg',
    PYTHONUNBUFFERED: '1',
    PYTHONPATH: [backendDir, process.env.PYTHONPATH || ''].filter(Boolean).join(
      process.platform === 'win32' ? ';' : ':'
    ),
  }

  // 找到 Python 可执行（开发态可用 PRINTFILM_PYTHON env 指向系统解释器）
  const pyPath =
    process.env.PRINTFILM_PYTHON && fs.existsSync(process.env.PRINTFILM_PYTHON)
      ? process.env.PRINTFILM_PYTHON
      : fs.existsSync(pythonExe)
        ? pythonExe
        : 'python'
  const args = ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(PORT)]
  log(`starting python: ${pyPath} (cwd=${backendDir}, pythonExe=${pythonExe})`)
  pyProc = spawn(pyPath, args, {
    cwd: backendDir,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  const pyLogPath = path.join(path.dirname(resourceRoot), 'backend_py.log')
  const pyLogStream = fs.createWriteStream(pyLogPath, { flags: 'a' })
  pyLogStream.write('\n===== spawn ' + new Date().toISOString() + ' py=' + pyPath + ' =====\n')
  pyProc.stdout.on('data', (d) => {
    const s = String(d).trim()
    if (s) {
      log('[py]', s)
      pyLogStream.write(s + '\n')
    }
  })
  pyProc.stderr.on('data', (d) => {
    const s = String(d).trim()
    if (s) {
      log('[py:err]', s)
      pyLogStream.write('[err] ' + s + '\n')
    }
  })
  pyProc.on('exit', (code) => log('python exited code=' + code))

  return waitPort(PORT).then((ok) => {
    if (!ok) throw new Error('Python 后端 30s 内未就绪，请查看日志')
  })
}

function stopBackend() {
  if (pyProc && pyProc.exitCode === null) {
    log('stopping python...')
    pyProc.kill('SIGTERM')
    // 给 3 秒优雅退出，然后强杀
    setTimeout(() => {
      if (pyProc && pyProc.exitCode === null) pyProc.kill('SIGKILL')
    }, 3000)
  }
}

function createWindow() {
  const icon = path.join(__dirname, '..', 'assets', 'icon.png')
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 720,
    backgroundColor: BG,
    autoHideMenuBar: true,
    icon,
    title: 'PRINTFILM 单机版',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      spellcheck: false,
    },
  })

  const url = `http://127.0.0.1:${PORT}/`
  mainWindow.webContents.setUserAgent(
    `${mainWindow.webContents.getUserAgent()} PRINTFILM-Standalone/${app.getVersion()}`
  )

  // 通知前端这是单机版（Agnes onboarding 组件据此启用）
  mainWindow.webContents.on('did-finish-load', () => {
    mainWindow.webContents
      .executeJavaScript('window.__PRINTFILM_STANDALONE__ = true')
      .catch(() => {})
  })

  // 外链走系统浏览器，站内留应用
  mainWindow.webContents.setWindowOpenHandler(({ url: target }) => {
    if (target.startsWith(`http://127.0.0.1:${PORT}`) || target.startsWith('file:')) {
      return { action: 'allow' }
    }
    shell.openExternal(target)
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, target) => {
    if (target.startsWith(`http://127.0.0.1:${PORT}`) || target.startsWith('file:')) return
    event.preventDefault()
    shell.openExternal(target)
  })

  // 下载
  session.defaultSession.on('will-download', (event, item) => {
    const dl = app.getPath('downloads')
    item.setSavePath(path.join(dl, item.getFilename() || 'download'))
    item.once('done', (_e, state) => {
      if (state === 'completed') shell.showItemInFolder(item.getSavePath())
    })
  })

  mainWindow.loadURL(url).catch(async (err) => {
    await dialog.showMessageBox(mainWindow, {
      type: 'error',
      title: 'PRINTFILM 单机版',
      message: '后端未就绪',
      detail: `无法连接 http://127.0.0.1:${PORT}\n${err.message}`,
    })
  })
}

function buildMenu() {
  const template = [
    {
      label: '文件',
      submenu: [
        { label: '刷新', accelerator: 'CmdOrCtrl+R', click: (_i, w) => w && w.webContents.reload() },
        { label: '强制刷新', accelerator: 'CmdOrCtrl+Shift+R', click: (_i, w) => w && w.webContents.reloadIgnoringCache() },
        { type: 'separator' },
        { label: '退出', role: 'quit' },
      ],
    },
    {
      label: '查看',
      submenu: [
        { label: '实际大小', role: 'resetZoom' },
        { label: '放大', role: 'zoomIn' },
        { label: '缩小', role: 'zoomOut' },
        { type: 'separator' },
        { label: '全屏', role: 'togglefullscreen' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '关于 PRINTFILM 单机版',
          click: () => {
            dialog.showMessageBox({
              type: 'info',
              title: '关于',
              message: 'PRINTFILM 单机开源版',
              detail: `版本 ${app.getVersion()}\n内嵌 Python 后端 + Agnes 引擎\n数据目录：${app.getPath('userData')}`,
            })
          },
        },
      ],
    },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

// ---- app 生命周期 ----
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const win = BrowserWindow.getAllWindows()[0]
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  app.whenReady().then(async () => {
    buildMenu()
    try {
      await startBackend()
      log('backend ready')
    } catch (err) {
      log('backend failed: ' + err.message)
      dialog.showErrorBox(
        'PRINTFILM 单机版',
        `后端启动失败：${err.message}\n请确认 Python 与依赖完整。`
      )
      app.quit()
      return
    }
    createWindow()
  })

  app.on('window-all-closed', () => {
    stopBackend()
    app.quit()
  })

  app.on('before-quit', () => {
    stopBackend()
  })
}
