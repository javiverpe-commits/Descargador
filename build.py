#!/usr/bin/env python3
"""
Compila la app en un programa independiente (no hace falta Python para usarlo).

  python build.py

Descarga deno (necesario para YouTube), empaqueta junto con yt-dlp y ffmpeg
y deja un .zip listo para repartir en  dist/
"""
import io
import os
import platform
import shutil
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

try:
    import tkinter  # noqa: F401  (la ventana de la app lo necesita)
except ImportError:
    sys.exit("Este Python no incluye tkinter; la app no tendría ventana.")
import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent
NAME = "DescargadorMP3"

system = platform.system()
machine = platform.machine().lower()
if system == "Windows":
    triple, tag = "x86_64-pc-windows-msvc", "windows"
elif system == "Darwin":
    arm = machine in ("arm64", "aarch64")
    triple = "aarch64-apple-darwin" if arm else "x86_64-apple-darwin"
    tag = "mac-apple-silicon" if arm else "mac-intel"
else:
    triple, tag = "x86_64-unknown-linux-gnu", "linux"

# 1) deno
deno_name = "deno.exe" if system == "Windows" else "deno"
deno_dir = ROOT / "build_tools"
deno_dir.mkdir(exist_ok=True)
deno_path = deno_dir / deno_name
if not deno_path.exists():
    url = f"https://github.com/denoland/deno/releases/latest/download/deno-{triple}.zip"
    print("Descargando deno:", url)
    with urllib.request.urlopen(url, timeout=300) as r:
        data = r.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extract(deno_name, deno_dir)
    deno_path.chmod(deno_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

# 2) PyInstaller
args = [
    str(ROOT / "descargador_mp3.py"),
    "--name", NAME,
    "--noconfirm", "--clean",
    "--distpath", str(ROOT / "dist"),
    "--workpath", str(ROOT / "build"),
    "--specpath", str(ROOT / "build"),
    "--collect-all", "yt_dlp",
    "--collect-all", "yt_dlp_ejs",
    "--collect-all", "imageio_ffmpeg",
    "--collect-all", "certifi",
    "--add-data", f"{deno_path}{os.pathsep}bin",
    "--add-data", f"{ROOT / 'icono.png'}{os.pathsep}.",
]
if system == "Windows":
    args += ["--icon", str(ROOT / "icono.ico")]
elif system == "Darwin":
    args += ["--icon", str(ROOT / "icono.icns")]
if system in ("Windows", "Darwin"):
    args.append("--windowed")  # sin ventana de consola
PyInstaller.__main__.run(args)

# 3) zip para repartir
dist = ROOT / "dist"
out = dist / f"{NAME}-{tag}.zip"
out.unlink(missing_ok=True)
if system == "Darwin":
    app = dist / f"{NAME}.app"
    os.system(f'ditto -c -k --sequesterRsrc --keepParent "{app}" "{out}"')  # conserva permisos y enlaces
elif system == "Windows":
    shutil.make_archive(str(out.with_suffix("")), "zip", dist, NAME)
else:
    shutil.make_archive(str(out.with_suffix("")), "zip", dist, NAME)
print("Listo:", out, f"({out.stat().st_size/1e6:.0f} MB)")
