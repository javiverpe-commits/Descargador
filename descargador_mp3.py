#!/usr/bin/env python3
"""
Descargador de audio a MP3 (uso personal).

Pega un enlace (YouTube u otra web compatible con yt-dlp), elige la calidad
y el audio se descarga y se convierte a MP3.

En la versión empaquetada (.exe / .app) ffmpeg y deno van incluidos: no hay
que instalar nada. Desde el código fuente:  python3 descargador_mp3.py
"""
import hashlib
import io
import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import threading
import tkinter as tk
import urllib.request
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import yt_dlp

FROZEN = getattr(sys, "frozen", False)
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
CONFIG = Path.home() / ".descargador_mp3.json"
LIBS_DIR = Path(os.environ.get("MP3_LIBS_DIR", Path.home() / ".descargador_mp3_libs"))
PACKAGES = {"yt-dlp": "yt_dlp", "yt-dlp-ejs": "yt_dlp_ejs"}  # nombre en PyPI -> módulo
ANSI = re.compile(r"\x1b\[[0-9;]*m")
QUALITIES = [("320 kbps (máxima)", "320"), ("256 kbps", "256"),
             ("192 kbps (recomendada)", "192"), ("128 kbps (ligera)", "128")]


# ---------------------------------------------------------------- herramientas incluidas
def find_ffmpeg():
    try:
        import imageio_ffmpeg  # incluye un ffmpeg estático para cada sistema
        exe = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if exe.exists():
            if os.name != "nt":
                exe.chmod(exe.stat().st_mode | 0o111)
            return str(exe)
    except Exception:  # noqa: BLE001
        pass
    return shutil.which("ffmpeg")


def find_deno():
    name = "deno.exe" if os.name == "nt" else "deno"
    bundled = BASE / "bin" / name
    if bundled.exists():
        if os.name != "nt":
            bundled.chmod(bundled.stat().st_mode | 0o111)
        return str(bundled)
    return shutil.which("deno")


FFMPEG = find_ffmpeg()
DENO = find_deno()


# ---------------------------------------------------------------- actualización de yt-dlp
def vtuple(version):
    return tuple(int(x) for x in re.findall(r"\d+", version))


def use_updated_libs():
    """Si hay una versión de yt-dlp descargada más nueva que la incluida, usa esa."""
    global yt_dlp
    try:
        text = (LIBS_DIR / "yt_dlp" / "version.py").read_text(encoding="utf-8")
        found = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", text)
        if not found or vtuple(found.group(1)) <= vtuple(yt_dlp.version.__version__):
            return
        for name in [n for n in sys.modules if n.split(".")[0] in PACKAGES.values()]:
            del sys.modules[name]
        sys.path.insert(0, str(LIBS_DIR))
        import yt_dlp as newer  # noqa: F811
        yt_dlp = newer
    except Exception:  # noqa: BLE001
        pass  # ante cualquier problema, nos quedamos con la versión incluida


use_updated_libs()


def _download(url):
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "DescargadorMP3"})
    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
        return r.read()


def update_libs():
    """Busca en PyPI una versión más nueva de yt-dlp y la guarda en LIBS_DIR.
    Devuelve (versión, True) si se ha actualizado o (versión_actual, False) si ya era la última."""
    current = yt_dlp.version.__version__
    metas = {pkg: json.loads(_download(f"https://pypi.org/pypi/{pkg}/json")) for pkg in PACKAGES}
    latest = metas["yt-dlp"]["info"]["version"]
    if vtuple(latest) <= vtuple(current):
        return current, False
    staging = LIBS_DIR.with_name(LIBS_DIR.name + "_nuevo")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        for pkg, module in PACKAGES.items():
            wheel = next((u for u in metas[pkg]["urls"]
                          if u["packagetype"] == "bdist_wheel" and u["filename"].endswith("none-any.whl")), None)
            if not wheel:
                raise RuntimeError(f"No se encontró el paquete de {pkg}.")
            data = _download(wheel["url"])
            if hashlib.sha256(data).hexdigest() != wheel["digests"]["sha256"]:
                raise RuntimeError("La descarga está dañada. Inténtalo de nuevo.")
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for name in z.namelist():
                    if name.split("/")[0] != module:
                        continue
                    target = (staging / name).resolve()
                    if staging.resolve() not in target.parents:
                        raise RuntimeError("Archivo no válido en la actualización.")
                    z.extract(name, staging)
        shutil.rmtree(LIBS_DIR, ignore_errors=True)
        staging.rename(LIBS_DIR)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return latest, True


# ---------------------------------------------------------------- carpeta de destino
def load_out_dir():
    if os.environ.get("MP3_DIR"):
        return Path(os.environ["MP3_DIR"])
    try:
        saved = json.loads(CONFIG.read_text(encoding="utf-8")).get("out_dir")
        if saved:
            return Path(saved)
    except Exception:  # noqa: BLE001
        pass
    return Path.home() / "Downloads" / "MP3"


def check_writable(path):
    """Devuelve None si se puede guardar en la carpeta, o el mensaje de error."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        test = path / ".escritura_prueba"
        test.write_text("ok")
        test.unlink()
    except Exception as e:  # noqa: BLE001
        return str(e)
    return None


class Quiet:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


# ---------------------------------------------------------------- descarga (hilo aparte)
def run_job(job, url, quality, playlist, out_dir):
    if not FFMPEG:
        job.update(state="error", message="No se encuentra ffmpeg, necesario para crear el MP3.")
        return

    def hook(d):
        info = d.get("info_dict") or {}
        idx, total_items = info.get("playlist_index"), info.get("n_entries")
        prefix = f"({idx}/{total_items}) " if playlist and idx and total_items else ""
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                job["percent"] = round(d["downloaded_bytes"] * 100 / total, 1)
            job["message"] = prefix + "Descargando audio…"
        elif d["status"] == "finished":
            job["percent"] = 100
            job["message"] = prefix + "Convirtiendo a MP3…"

    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(title).150s.%(ext)s"),
        "noplaylist": not playlist,
        "ffmpeg_location": FFMPEG,
        **({"js_runtimes": {"deno": {"path": DENO}}} if DENO else {}),
        "quiet": True,
        "no_warnings": True,
        "logger": Quiet(),
        "progress_hooks": [hook],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": quality},
            {"key": "FFmpegMetadata", "add_metadata": True},
        ],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        if info and info.get("entries"):
            n = len([e for e in info["entries"] if e])
            job["title"] = f"{n} pistas de la lista «{info.get('title', '')}»"
        else:
            job["title"] = (info or {}).get("title", "")
        job.update(state="done", percent=100, message="¡Listo!")
    except Exception as e:  # noqa: BLE001
        job.update(state="error", message=ANSI.sub("", str(e)).strip()[:600] or "Error desconocido")


# ---------------------------------------------------------------- ventana
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("")  # sin texto en la barra de título: el nombre ya está en la ventana
        self.minsize(580, 400)
        try:  # icono propio en lugar de la pluma de Tk
            ico = BASE / "icono.ico"
            if os.name == "nt" and ico.exists():
                self.iconbitmap(default=str(ico))
            else:
                self._icon = tk.PhotoImage(file=str(BASE / "icono.png"))
                self.iconphoto(True, self._icon)
        except Exception:  # noqa: BLE001
            pass
        self.out_dir = load_out_dir()
        self.job = None
        self.upd_job = None

        pad = {"padx": 18}
        root = ttk.Frame(self, padding=(0, 16, 0, 12))
        root.pack(fill="both", expand=True)

        title_font = tkfont.nametofont("TkDefaultFont").copy()
        title_font.configure(size=title_font.cget("size") + 6, weight="bold")
        head = ttk.Frame(root)
        head.pack(fill="x", pady=(0, 12), **pad)
        try:  # el pollito, grande, junto al título
            self._logo = tk.PhotoImage(file=str(BASE / "icono_cabecera.png"))
            ttk.Label(head, image=self._logo).pack(side="left", padx=(0, 16))
        except Exception:  # noqa: BLE001
            pass
        heading = ttk.Frame(head)
        heading.pack(side="left")
        ttk.Label(heading, text="Descargador MP3", font=title_font).pack(anchor="w")
        ttk.Label(heading, text="Pega el enlace del vídeo y se guardará su audio como MP3.",
                  foreground="#666").pack(anchor="w")

        ttk.Label(root, text="Enlace").pack(anchor="w", **pad)
        row = ttk.Frame(root)
        row.pack(fill="x", pady=(2, 10), **pad)
        self.url = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.url)
        self.entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Pegar", command=self.paste).pack(side="left", padx=(8, 0))
        self.entry.bind("<Return>", lambda e: self.start())
        self.entry.focus_set()

        ttk.Label(root, text="Calidad del MP3").pack(anchor="w", **pad)
        self.quality = ttk.Combobox(root, state="readonly", values=[q[0] for q in QUALITIES], width=26)
        self.quality.current(2)
        self.quality.pack(anchor="w", pady=(2, 8), **pad)

        self.playlist = tk.BooleanVar(value=False)
        ttk.Checkbutton(root, text="Si el enlace es de una lista de reproducción, descargar toda la lista",
                        variable=self.playlist).pack(anchor="w", pady=(0, 10), **pad)

        ttk.Label(root, text="Guardar en").pack(anchor="w", **pad)
        row = ttk.Frame(root)
        row.pack(fill="x", pady=(2, 12), **pad)
        self.dir_label = ttk.Label(row, text=str(self.out_dir), wraplength=330, justify="left")
        self.dir_label.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Abrir", command=self.open_folder).pack(side="right")
        ttk.Button(row, text="Cambiar carpeta…", command=self.change_folder).pack(side="right", padx=(0, 6))

        self.go = ttk.Button(root, text="Descargar MP3", command=self.start)
        self.go.pack(anchor="w", pady=(0, 10), **pad)
        self.bar = ttk.Progressbar(root, mode="determinate", maximum=100)
        self.bar.pack(fill="x", **pad)
        self.msg = ttk.Label(root, text="", wraplength=520, justify="left")
        self.msg.pack(anchor="w", pady=(8, 0), **pad)

        foot = ttk.Frame(root)
        foot.pack(side="bottom", fill="x", **pad)
        ttk.Label(foot, foreground="#888", wraplength=380, justify="left",
                  text="Úsalo solo con contenido que tengas derecho a descargar (tuyo, con licencia "
                       "libre o con permiso).").pack(side="left", fill="x", expand=True)
        self.upd = ttk.Button(foot, text=f"Actualizar yt-dlp ({yt_dlp.version.__version__})",
                              command=self.update_ytdlp)
        self.upd.pack(side="right", padx=(10, 0))

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(300, self._hide_titlebar_icon)
        self.bind("<Configure>", self._rewrap)

        if os.environ.get("MP3_SELFTEST_URL"):  # solo para pruebas automáticas
            self.after(500, self._selftest)

    def _hide_titlebar_icon(self):
        """Windows: deja en blanco el iconito de la barra de título.
        El icono grande (barra de tareas y Alt+Tab) se mantiene con el pollito."""
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.GetParent.argtypes = [wintypes.HWND]
            user32.GetParent.restype = wintypes.HWND
            user32.CreateIcon.argtypes = [wintypes.HINSTANCE, ctypes.c_int, ctypes.c_int, ctypes.c_ubyte,
                                          ctypes.c_ubyte, ctypes.c_void_p, ctypes.c_void_p]
            user32.CreateIcon.restype = wintypes.HICON
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = wintypes.LPARAM
            hwnd = user32.GetParent(self.winfo_id()) or self.winfo_id()
            # icono de 16x16 totalmente transparente (máscara AND a 1, imagen XOR a 0)
            and_bits = (ctypes.c_ubyte * 32)(*([0xFF] * 32))
            xor_bits = (ctypes.c_ubyte * 32)(*([0x00] * 32))
            blank = user32.CreateIcon(None, 16, 16, 1, 1, and_bits, xor_bits)
            if blank:
                self._blank_icon = blank
                WM_SETICON, ICON_SMALL = 0x0080, 0
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, blank)
        except Exception:  # noqa: BLE001
            pass  # si algo falla, la ventana queda como estaba

    # --- utilidades de interfaz
    def _rewrap(self, event):
        if event.widget is self:
            self.msg.configure(wraplength=max(300, event.width - 40))

    def show(self, text, color=""):
        self.msg.configure(text=text, foreground=color)

    def paste(self):
        try:
            self.url.set(self.clipboard_get().strip())
        except tk.TclError:
            pass

    def open_folder(self):
        if check_writable(self.out_dir):
            return self.show("No se puede abrir la carpeta de destino.", "#c53030")
        system = platform.system()
        if system == "Windows":
            os.startfile(self.out_dir)  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.Popen(["open", str(self.out_dir)])
        else:
            subprocess.Popen(["xdg-open", str(self.out_dir)])

    def change_folder(self):
        start = self.out_dir if self.out_dir.exists() else Path.home()
        chosen = filedialog.askdirectory(parent=self, initialdir=str(start),
                                         title="Elige la carpeta donde guardar los MP3")
        if chosen:
            self.set_folder(Path(chosen))

    def set_folder(self, path):
        err = check_writable(path)
        if err:
            return self.show(f"No se puede guardar en esa carpeta: {err}", "#c53030")
        self.out_dir = path
        self.dir_label.configure(text=str(path))
        try:
            CONFIG.write_text(json.dumps({"out_dir": str(path)}), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        self.show("✓ Carpeta cambiada", "#2f855a")

    # --- descarga
    def start(self, quality=None):
        if self.job and self.job["state"] == "running":
            return
        url = self.url.get().strip()
        if not re.match(r"^https?://", url, re.I):
            return self.show("Pega un enlace que empiece por http:// o https://", "#c53030")
        err = check_writable(self.out_dir)
        if err:
            return self.show(f"No se puede guardar en la carpeta de destino: {err}", "#c53030")
        if quality is None:
            quality = QUALITIES[self.quality.current()][1]
        self.job = {"state": "running", "percent": 0, "message": "Preparando…", "title": ""}
        self.go.state(["disabled"])
        self.bar.configure(value=2)
        self.show("Preparando…")
        threading.Thread(target=run_job, daemon=True,
                         args=(self.job, url, quality, self.playlist.get(), self.out_dir)).start()
        self.after(200, self.poll)

    def poll(self):
        job = self.job
        self.bar.configure(value=job["percent"] or 2)
        if job["state"] == "running":
            self.show(job["message"])
            return self.after(200, self.poll)
        self.go.state(["!disabled"])
        if job["state"] == "done":
            self.bar.configure(value=100)
            self.show(f"✓ {job['title'] or 'Listo'} — guardado en la carpeta de destino", "#2f855a")
            self.url.set("")
        else:
            self.bar.configure(value=0)
            self.show(job["message"], "#c53030")

    def update_ytdlp(self):
        if self.job and self.job["state"] == "running":
            return self.show("Espera a que termine la descarga para actualizar.", "#c53030")
        self.upd.state(["disabled"])
        self.show("Buscando actualización de yt-dlp…")
        self.upd_job = {"state": "running"}

        def work():
            try:
                self.upd_job["version"], self.upd_job["changed"] = update_libs()
                self.upd_job["state"] = "done"
            except Exception as e:  # noqa: BLE001
                self.upd_job.update(state="error", message=str(e)[:300])
        threading.Thread(target=work, daemon=True).start()
        self.after(300, self.poll_update)

    def poll_update(self):
        j = self.upd_job
        if j["state"] == "running":
            return self.after(300, self.poll_update)
        self.upd.state(["!disabled"])
        if j["state"] == "error":
            return self.show("No se pudo actualizar: " + j["message"], "#c53030")
        if not j["changed"]:
            return self.show(f"✓ Ya tienes la última versión de yt-dlp ({j['version']}).", "#2f855a")
        messagebox.showinfo("Actualizado", f"yt-dlp se ha actualizado a la versión {j['version']}.\n"
                            "El programa se reiniciará ahora. Si no vuelve a abrirse, ábrelo de nuevo.")
        self.restart()

    def restart(self):
        cmd = [sys.executable] if FROZEN else [sys.executable, str(Path(__file__).resolve())]
        try:
            subprocess.Popen(cmd, close_fds=True, env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
        except Exception:  # noqa: BLE001
            return self.show("Actualizado. Cierra el programa y ábrelo de nuevo.", "#2f855a")
        self.destroy()

    def on_close(self):
        if self.job and self.job["state"] == "running":
            if not messagebox.askyesno("Descarga en curso", "Hay una descarga en curso. ¿Salir de todas formas?"):
                return
        self.destroy()

    # --- prueba automática (variables de entorno; no se usa en el día a día)
    def _selftest(self):
        self.url.set(os.environ["MP3_SELFTEST_URL"])
        self.start()
        self._selftest_wait()

    def _selftest_wait(self):
        if self.job["state"] == "running":
            return self.after(300, self._selftest_wait)
        out = os.environ.get("MP3_SELFTEST_OUT")
        if out:
            Path(out).write_text(json.dumps({**self.job, "ytdlp": yt_dlp.version.__version__},
                                            ensure_ascii=False), encoding="utf-8")
        self.after(200, self.destroy)


def main():
    if platform.system() == "Windows":
        try:  # ventana nítida en pantallas de alta resolución
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    App().mainloop()


if __name__ == "__main__":
    main()
