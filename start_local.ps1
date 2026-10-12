# PRINTFILM 单机一键部署（Windows PowerShell）
# 用法：在仓库根目录双击 start_local.bat，或 PowerShell 运行 .\start_local.ps1
# 前置：Docker Desktop、Python 3.12+、Node.js 18+、FFmpeg

$ErrorActionPreference = "Stop"
$Root   = $PSScriptRoot
$LogDir = Join-Path $Root ".local-run"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Force -Path $LogDir | Out-Null }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  PRINTFILM 单机部署" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---------- 0. 自动准备 backend/.env（首次） ----------
$backendDir = Join-Path $Root "backend"
$envFile    = Join-Path $backendDir ".env"
$envExample = Join-Path $backendDir ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Host "  已从 .env.example 生成 backend/.env（三条能力默认走 Agnes 官方 API）" -ForegroundColor DarkGray
    } else {
        Write-Host "  警告：找不到 backend/.env 和 .env.example" -ForegroundColor Red
    }
}

# ---------- 1. 前置依赖检测 ----------
$missing = @()

# Docker（常见安装路径加入 PATH）
foreach ($p in @(
    "C:\Program Files\Docker\Docker\resources\bin",
    "C:\Program Files\Docker\cmd"
)) {
    if (Test-Path $p) { $env:Path = "$p;$env:Path" }
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    $missing += "Docker Desktop（安装: https://www.docker.com/products/docker-desktop/）"
} else {
    Write-Host "[OK] Docker" -ForegroundColor Green
}

# Python 3.12+（动态找 PATH 里的 python）
$py = $null
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    $ver = & python --version 2>&1
    if ($ver -match "3\.(1[2-9]|[2-9]\d)\.") {
        $py = $pythonCmd.Source
    }
}
# 也试 python3 / py
if (-not $py) {
    foreach ($cmd in @("python3", "py")) {
        $c = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($c) {
            $ver = & $c.Source --version 2>&1
            if ($ver -match "3\.(1[2-9]|[2-9]\d)\.") { $py = $c.Source; break }
        }
    }
}
if (-not $py) {
    $missing += "Python 3.12+（安装: https://www.python.org/downloads/）"
} else {
    Write-Host ("[OK] Python: " + $py) -ForegroundColor Green
}

# Node.js / npm（动态找）
$npmCmd = $null
foreach ($cmd in @("npm", "npm.cmd")) {
    $c = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($c) { $npmCmd = $c.Source; break }
}
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd -or -not $npmCmd) {
    $missing += "Node.js 18+（安装: https://nodejs.org/，勾选 Add to PATH）"
} else {
    $nodeVer = & $nodeCmd --version 2>&1
    Write-Host ("[OK] Node.js " + $nodeVer + " / npm") -ForegroundColor Green
}

# FFmpeg
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    $missing += "FFmpeg（安装: https://ffmpeg.org/download.html 并加入 PATH）"
} else {
    Write-Host "[OK] FFmpeg" -ForegroundColor Green
}

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "缺少以下依赖，请先安装后重试：" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host ("  - " + $_) -ForegroundColor Red }
    exit 1
}
Write-Host ""

# ---------- 2. Docker 中间件（Postgres + Redis） ----------
Write-Host "[1/5] 启动 Docker 中间件（Postgres + Redis）..." -ForegroundColor Yellow

$dockerOk = $false
for ($i = 0; $i -lt 30; $i++) {
    $ver = docker info --format '{{.ServerVersion}}' 2>$null
    if ($LASTEXITCODE -eq 0 -and $ver) { $dockerOk = $true; break }
    if ($i -eq 0) {
        Write-Host "  等待 Docker 引擎..." -ForegroundColor DarkGray
        foreach ($desk in @(
            "C:\Program Files\Docker\Docker\Docker Desktop.exe",
            "C:\Program Files (x86)\Docker\Docker\Docker Desktop.exe"
        )) {
            if (Test-Path $desk) { Start-Process $desk -WindowStyle Minimized; break }
        }
    }
    Start-Sleep -Seconds 5
}
if (-not $dockerOk) {
    Write-Host "  Docker 引擎未就绪，请手动启动 Docker Desktop 后重试。" -ForegroundColor Red
    exit 1
}
Write-Host ("  Docker 引擎: " + $ver) -ForegroundColor Green

# 创建 deploy/.env.prod（如果不存在）
$envProd = Join-Path $Root "deploy\.env.prod"
if (-not (Test-Path $envProd)) {
    $envProdExample = Join-Path $Root "deploy\.env.prod.example"
    if (Test-Path $envProdExample) {
        Copy-Item $envProdExample $envProd
        Write-Host "  已创建 deploy/.env.prod" -ForegroundColor DarkGray
    }
}

# 启动 PG + Redis
Push-Location $Root
docker compose -f deploy\docker-compose.yml --env-file deploy\.env.prod up -d 2>&1 | Out-Null
Pop-Location

$pgReady = $false
for ($i = 0; $i -lt 36; $i++) {
    $status = docker inspect -f '{{.State.Status}}' ai-movie-pg 2>$null
    if ($status -eq "running") { $pgReady = $true; break }
    Start-Sleep -Seconds 5
}
if (-not $pgReady) {
    Write-Host "  Postgres 未就绪，请检查 Docker Desktop 日志。" -ForegroundColor Red
    exit 1
}
Write-Host "  Postgres:15432 + Redis:16379 已就绪" -ForegroundColor Green

# ---------- 3. 后端 Python 环境 ----------
Write-Host "[2/5] 准备后端 Python 环境..." -ForegroundColor Yellow

$venvDir = Join-Path $backendDir ".venv"
$venvPy  = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "  创建 venv（首次）..." -ForegroundColor DarkGray
    & $py -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  venv 创建失败" -ForegroundColor Red
        exit 1
    }
}
& $venvPy -m pip install --quiet --upgrade pip
& $venvPy -c "import fastapi" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  安装 Python 依赖（首次可能耗时 2-5 分钟）..." -ForegroundColor DarkGray
    Push-Location $backendDir
    & $venvPy -m pip install --quiet -r requirements.txt
    Pop-Location
} else {
    Write-Host "  Python 依赖已就绪" -ForegroundColor DarkGray
}
Write-Host "  后端环境就绪" -ForegroundColor Green

# ---------- 4. 前端 Node 依赖 ----------
Write-Host "[3/5] 准备前端 Node 环境..." -ForegroundColor Yellow

foreach ($dir in @("frontend", "admin")) {
    $nm = Join-Path $Root "$dir\node_modules"
    if (-not (Test-Path $nm)) {
        Write-Host ("  npm install " + $dir + " ...") -ForegroundColor DarkGray
        Push-Location (Join-Path $Root $dir)
        & $npmCmd install --quiet 2>&1 | Out-Null
        Pop-Location
    }
}
Write-Host "  前端依赖就绪" -ForegroundColor Green

# ---------- 5. 修 static/generated（Windows 兼容） ----------
$genDir = Join-Path $backendDir "static\generated"
if (Test-Path $genDir) {
    $item = Get-Item $genDir -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        Write-Host "[4/5] 修复 static/generated 符号链接..." -ForegroundColor Yellow
        fsutil reparsepoint delete "$genDir" 2>$null | Out-Null
        Remove-Item $genDir -Force -ErrorAction SilentlyContinue
        New-Item -ItemType Directory -Force -Path $genDir | Out-Null
        Write-Host "  已重建为本地目录" -ForegroundColor DarkGray
    }
} else {
    Write-Host "[4/5] 创建 static/generated..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $genDir | Out-Null
}

# ---------- 6. 启动服务 ----------
Write-Host "[5/5] 启动服务..." -ForegroundColor Yellow

$uvBin = Join-Path $venvDir "Scripts\uvicorn.exe"

# 杀掉已有的 printfilm 相关 uvicorn（避免端口冲突）
Get-Process uvicorn, python -ErrorAction SilentlyContinue | ForEach-Object {
    $cmdline = try { (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine } catch { "" }
    if ($cmdline -like "*printfilm*" -or $cmdline -like "*app.main*") {
        Write-Host ("  清理旧进程 " + $_.ProcessName + " " + $_.Id) -ForegroundColor DarkGray
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep 2

$apiPid = Start-Process -FilePath $uvBin `
    -ArgumentList "app.main:app --host 127.0.0.1 --port 8000" `
    -WorkingDirectory $backendDir `
    -RedirectStandardOutput (Join-Path $LogDir "api.out.log") `
    -RedirectStandardError  (Join-Path $LogDir "api.err.log") `
    -WindowStyle Hidden -PassThru

$apiReady = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 3
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $apiReady = $true; break }
    } catch {}
}
if ($apiReady) {
    Write-Host "  API  http://127.0.0.1:8000  已就绪" -ForegroundColor Green
} else {
    Write-Host "  API 启动超时，请查看 $LogDir\api.err.log" -ForegroundColor Red
}

$fePid = Start-Process -FilePath $npmCmd `
    -ArgumentList "run dev" `
    -WorkingDirectory (Join-Path $Root "frontend") `
    -RedirectStandardOutput (Join-Path $LogDir "fe.out.log") `
    -RedirectStandardError  (Join-Path $LogDir "fe.err.log") `
    -WindowStyle Hidden -PassThru

Start-Sleep -Seconds 3

$admPid = Start-Process -FilePath $npmCmd `
    -ArgumentList "run dev" `
    -WorkingDirectory (Join-Path $Root "admin") `
    -RedirectStandardOutput (Join-Path $LogDir "admin.out.log") `
    -RedirectStandardError  (Join-Path $LogDir "admin.err.log") `
    -WindowStyle Hidden -PassThru

Start-Sleep -Seconds 8
# 确认前端起来
foreach ($port in @(5173, 5174)) {
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$port" -UseBasicParsing -TimeoutSec 5
        Write-Host ("  前端 :$port 已就绪") -ForegroundColor Green
    } catch {
        Write-Host ("  前端 :$port 未就绪，请查看日志（可能仍在编译）") -ForegroundColor DarkGray
    }
}

# ---------- 7. 完成 ----------
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  部署完成！" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  用户端:   http://localhost:5173" -ForegroundColor White
Write-Host "  管理端:   http://localhost:5174" -ForegroundColor White
Write-Host "  API:      http://127.0.0.1:8000" -ForegroundColor White
Write-Host ""
Write-Host "  下一步（只需填一把 Agnes Key）:" -ForegroundColor Yellow
Write-Host "  1. 浏览器打开 http://localhost:5173 注册账号"
Write-Host "  2. 个人中心 → API → 添加你的 Agnes API Key"
Write-Host "  3. 文本 / 图片 / 视频 三项功能即可使用"
Write-Host ""
Write-Host "  日志目录: $LogDir" -ForegroundColor DarkGray
Write-Host "  API PID: $($apiPid.Id) | FE PID: $($fePid.Id) | ADMIN PID: $($admPid.Id)" -ForegroundColor DarkGray
Write-Host ""

Start-Process "http://localhost:5173"
