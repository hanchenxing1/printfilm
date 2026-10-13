# -*- coding: utf-8 -*-
"""准备 electron/ 开发态资源布局（dev 运行 electron . 时用）。

打包时 extraResources 会带 backend/python/ffmpeg；开发态直接在
electron/ 下做符号链接或复制，使 resourceRoot/.. 指向 standalone 根。

布局（electron/ 为 resourceRoot，parent = standalone 根）：
  standalone/
    electron/            <- resourceRoot（开发态）
      src/main.js
      src/preload.js
      assets/icon.png
      package.json
    backend/             <- ../backend
    python/              <- ../python（内嵌解释器目录，待装）
    ffmpeg/              <- ../ffmpeg
"""
from pathlib import Path
import shutil

root = Path(r"D:\短剧项目\printfilm-standalone")
electron = root / "electron"
backend = root / "backend"
ffmpeg_dir = root / "ffmpeg"
python_dir = root / "python"
python_dir.mkdir(parents=True, exist_ok=True)

# ffmpeg：从系统复制
ffmpeg_src = Path(r"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\ffmpeg.exe")
ffmpeg_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(ffmpeg_src, ffmpeg_dir / "ffmpeg.exe")
print("ffmpeg copied:", (ffmpeg_dir / "ffmpeg.exe").stat().st_size, "bytes")

# 说明 python 目录待构建（用 uv venv 装依赖 + 打包 python.exe）
(python_dir / "README.txt").write_text(
    "此目录在构建时由 scripts/pack_python.py 生成：\n"
    "- python.exe / python3.dll / libcrypto / libssl（嵌入式 CPython）\n"
    "- Lib/site-packages（uv 按 requirements.txt 装齐）\n",
    encoding="utf-8",
)
print("python/ placeholder ready")

print("dev layout done under electron/ (../backend ../ffmpeg exist)")
