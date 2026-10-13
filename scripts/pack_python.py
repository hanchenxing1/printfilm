# -*- coding: utf-8 -*-
"""pack_python.py — 构建 printfilm-standalone 内嵌 Python 运行时。

布局（生成后，electron-builder 会把 python/ 作为 extraResource 打进安装包）：

  standalone/
    python/
      python.exe
      pythonw.exe
      python312.dll
      python3.dll
      vcruntime140.dll            (root)
      Lib/...                     (stdlib, uv CPython 完整)
      DLLs/...                    (C 扩展 + libcrypto/libssl)
      bin/...                     (Scripts 可执行)
      Lib/site-packages/...       (uv 按 backend/requirements.txt 装齐)

原理：
  1. 从 uv 已缓存的 cpython-3.12.14-windows-x86_64-none 基础拷贝
     (python.exe / python312.dll / Lib / DLLs)，得到免安装 CPython；
  2. 用 `uv pip install --target` 把 requirements.txt 装进 Lib/site-packages；
  3. 用 venv 的 bin/*.exe 复制为 bin/（去掉 activate* 与 celery）；
  4. 写一个 `python\\run_uvicorn.cmd` 方便手动验证。

用法：
  & "C:\\Users\\Administrator\\.local\\bin\\uv.exe" ... 不需要，本脚本直接用 python 跑：
  python D:\短剧项目\printfilm-standalone\scripts\pack_python.py
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON_OUT = ROOT / "python"
BACKEND = ROOT / "backend"
REQS = BACKEND / "requirements.txt"

# uv 缓存的 cpython-3.12.14 基础（与本 venv 同版本，保证 ABI 一致）
UV_PY_BASE = Path(
    r"C:\Users\Administrator\AppData\Roaming\uv\python\cpython-3.12.14-windows-x86_64-none"
)
VENV_SRC = Path(r"D:\短剧项目\aidj-open-source\printfilm\backend\.venv")

# 需要拷的根级 exe/dll（嵌入式最小集）
ROOT_FILES = [
    "python.exe",
    "pythonw.exe",
    "python312.dll",
    "python3.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
]


def run(cmd: list[str], cwd: str | Path | None = None) -> None:
    print("  $ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True, cwd=str(cwd))


def copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    print(f"  copied {src.name} -> {dst}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="覆盖已存在的 python/ 目录")
    args = ap.parse_args()

    if not UV_PY_BASE.is_dir():
        sys.exit(f"未找到 uv CPython 基础：{UV_PY_BASE}")
    if not REQS.is_file():
        sys.exit(f"未找到 {REQS}")
    if not VENV_SRC.is_dir():
        sys.exit(f"未找到 venv 源 {VENV_SRC}（需要它提供 bin/*.exe）")

    if PYTHON_OUT.exists():
        if not args.force:
            sys.exit(f"{PYTHON_OUT} 已存在，加 --force 覆盖")
        print(f"清空 {PYTHON_OUT} ...")
        shutil.rmtree(PYTHON_OUT)

    print(f"[1/4] 拷贝 CPython 基础 -> {PYTHON_OUT}")
    PYTHON_OUT.mkdir(parents=True)
    for name in ROOT_FILES:
        src = UV_PY_BASE / name
        if src.is_file():
            shutil.copy2(src, PYTHON_OUT / name)
            print(f"  {name}")
    for d in ("Lib", "DLLs"):
        copytree(UV_PY_BASE / d, PYTHON_OUT / d)

    # bin/：从 venv 的 Scripts 拷可执行文件（Windows .exe）
    print(f"[2/4] 拷贝 venv bin (Scripts) -> {PYTHON_OUT / 'bin'}")
    bin_dst = PYTHON_OUT / "bin"
    bin_dst.mkdir(parents=True, exist_ok=True)
    scripts_src = VENV_SRC / "Scripts"
    skipped = {"activate", "activate.bat", "Activate.ps1", "deactivate.bat", "celery.exe"}
    n = 0
    for f in scripts_src.iterdir():
        if f.is_file() and f.stem not in skipped and f.suffix in (".exe", ".cmd"):
            shutil.copy2(f, bin_dst / f.name)
            n += 1
    print(f"  {n} executable(s)")

    # [3/4] uv pip install --target 装依赖进 site-packages
    print(f"[3/4] uv pip install --target {PYTHON_OUT / 'Lib' / 'site-packages'}")
    site = PYTHON_OUT / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)

    uv = Path(r"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\Scripts\uv.exe")
    if not uv.is_file():
        uv = shutil.which("uv") or Path(sys.executable)

    run(
        [
            str(uv), "pip", "install",
            "--python", "3.12",
            "--target", str(site),
            "-r", str(REQS),
        ],
        cwd=ROOT,
    )

    # [4/4] 验证：用内嵌解释器 import 关键包
    print("[4/4] 验证内嵌解释器")
    py_exe = PYTHON_OUT / "python.exe"
    check = [
        "-c",
        "import sys, fastapi, sqlalchemy, aiosqlite, jose, httpx, uvicorn, sse_starlette, edge_tts;"
        "print('ok', sys.version.split()[0], fastapi.__version__, sqlalchemy.__version__)",
    ]
    run([str(py_exe)] + check, cwd=BACKEND)

    # 写一个方便验证的启动脚本
    (PYTHON_OUT / "run_uvicorn.cmd").write_text(
        f"@echo off\r\n"
        f"REM 验证内嵌后端：cd 到 backend 起 uvicorn\r\n"
        f"set PYTHONIOENCODING=utf-8\r\n"
        f"cd /d {BACKEND}\r\n"
        f"{py_exe} -m uvicorn app.main:app --host 127.0.0.1 --port 8000\r\n",
        encoding="utf-8",
    )
    print(f"\n完成。python/ 大小 {sum(f.stat().st_size for f in PYTHON_OUT.rglob('*') if f.is_file())//1024//1024} MB")
    print("验证：双击 python\\run_uvicorn.cmd 或")
    print(f"  cd {BACKEND} && {py_exe} -m uvicorn app.main:app --port 8000")


if __name__ == "__main__":
    main()
