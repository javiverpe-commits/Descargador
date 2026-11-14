#!/usr/bin/env python3
"""
Descargador de audio a MP3 (uso personal).

Pega un enlace (YouTube u otra web compatible con yt-dlp), elige la calidad
y el audio se descarga y se convierte a MP3 en  ~/Downloads/MP3

En la versión empaquetada (.exe / .app) ffmpeg y deno van incluidos: no hay
que instalar nada. Desde el código fuente:  python3 descargador_mp3.py
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("MP3_PORT", "8765"))
OUT_DIR = Path(os.environ.get("MP3_DIR", Path.home() / "Downloads" / "MP3"))

import yt_dlp

FROZEN = getattr(sys, "frozen", False)
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def log(*args):
    """print() seguro: en la versión sin consola no hay stdout."""
    try:
        if sys.stdout:
            print(*args, flush=True)
    except Exception:  # noqa: BLE001
        pass


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
LAST_PING = time.time()
IDLE_LIMIT = 180  # segundos sin página abierta (y sin descargas) antes de cerrarse solo

JOBS = {}
LOCK = threading.Lock()
ANSI = re.compile(r"\x1b\[[0-9;]*m")
QUALITIES = {"128", "192", "256", "320"}


class Quiet:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def run_job(job_id, url, quality, playlist):
    job = JOBS[job_id]
    if not FFMPEG:
        job["state"], job["message"] = "error", "No se encuentra ffmpeg, necesario para crear el MP3."
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
        "outtmpl": str(OUT_DIR / "%(title).150s.%(ext)s"),
        "noplaylist": not playlist,
        **({"ffmpeg_location": FFMPEG} if FFMPEG else {}),
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
        job["state"], job["percent"], job["message"] = "done", 100, "¡Listo!"
    except Exception as e:  # noqa: BLE001
        job["state"] = "error"
        job["message"] = ANSI.sub("", str(e)).strip()[:600] or "Error desconocido"


def open_folder():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    system = platform.system()
    if system == "Windows":
        os.startfile(OUT_DIR)  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", str(OUT_DIR)])
    else:
        subprocess.Popen(["xdg-open", str(OUT_DIR)])


PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Descargador MP3</title>
<style>
  :root{color-scheme:light dark;--bg:#f6f5f2;--card:#fff;--fg:#1d1d1b;--mut:#6b6a66;--acc:#2b6cb0;--line:#dcdad4;--ok:#2f855a;--err:#c53030}
  @media(prefers-color-scheme:dark){:root{--bg:#161615;--card:#222221;--fg:#ecebe7;--mut:#9b9a95;--acc:#63a4e8;--line:#3a3a38;--ok:#68d391;--err:#fc8181}}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;display:grid;place-items:start center;min-height:100vh;padding:48px 16px}
  main{width:100%;max-width:620px;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:28px}
  h1{font-size:22px;margin:0 0 4px} p.sub{margin:0 0 22px;color:var(--mut);font-size:14px}
  label{display:block;font-size:13px;color:var(--mut);margin:14px 0 6px}
  input[type=text],select{width:100%;padding:11px 12px;font:inherit;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:8px}
  input[type=text]:focus,select:focus{outline:2px solid var(--acc);border-color:transparent}
  .row{display:flex;gap:12px;align-items:end;flex-wrap:wrap} .row>div{flex:1;min-width:160px}
  .chk{display:flex;gap:8px;align-items:center;font-size:14px;margin-top:14px;color:var(--fg)}
  button{font:inherit;border:0;border-radius:8px;padding:11px 18px;cursor:pointer;background:var(--acc);color:#fff;font-weight:600}
  button.sec{background:transparent;color:var(--acc);border:1px solid var(--line);font-weight:500}
  button:disabled{opacity:.5;cursor:default}
  .actions{display:flex;gap:10px;margin-top:20px}
  .bar{height:8px;background:var(--bg);border-radius:6px;overflow:hidden;margin-top:22px;display:none}
  .bar>div{height:100%;width:0;background:var(--acc);transition:width .3s}
  #msg{margin-top:10px;font-size:14px;min-height:22px;word-break:break-word}
  .ok{color:var(--ok)} .err{color:var(--err)}
  footer{margin-top:22px;font-size:12px;color:var(--mut)}
</style></head><body><main>
<h1>Descargador MP3</h1>
<p class="sub">Pega el enlace del vídeo y se guarda el audio en <b id="dir"></b></p>
<label for="url">Enlace</label>
<input id="url" type="text" placeholder="https://www.youtube.com/watch?v=…" autofocus>
<div class="row"><div>
  <label for="q">Calidad MP3</label>
  <select id="q">
    <option value="320">320 kbps (máxima)</option>
    <option value="256">256 kbps</option>
    <option value="192" selected>192 kbps (recomendada)</option>
    <option value="128">128 kbps (ligera)</option>
  </select></div></div>
<label class="chk"><input type="checkbox" id="pl"> Si el enlace es de una lista de reproducción, descargar toda la lista</label>
<div class="actions"><button id="go">Descargar MP3</button><button class="sec" id="open">Abrir carpeta</button><button class="sec" id="quit" style="margin-left:auto">Salir</button></div>
<div class="bar" id="bar"><div id="fill"></div></div>
<div id="msg"></div>
<footer>Úsalo solo con contenido que tengas derecho a descargar (tuyo, con licencia libre o con permiso).<br><span id="ver"></span></footer>
</main>
<script>
const $=id=>document.getElementById(id); let timer=null;
fetch('/info').then(r=>r.json()).then(j=>{$('dir').textContent=j.dir;$('ver').textContent='yt-dlp '+j.ytdlp});
setInterval(()=>fetch('/ping').catch(()=>{}),5000);
function show(t,c){$('msg').className=c||'';$('msg').textContent=t}
async function post(path,body){
  const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});
  return r.json();
}
$('go').onclick=async()=>{
  const url=$('url').value.trim();
  if(!/^https?:\\/\\//i.test(url)){show('Pega un enlace que empiece por http:// o https://','err');return}
  $('go').disabled=true; $('bar').style.display='block'; $('fill').style.width='2%'; show('Preparando…');
  const j=await post('/download',{url,quality:$('q').value,playlist:$('pl').checked});
  if(j.error){show(j.error,'err');$('go').disabled=false;return}
  timer=setInterval(async()=>{
    const s=await (await fetch('/status?id='+j.id)).json();
    $('fill').style.width=(s.percent||2)+'%';
    if(s.state==='running'){show(s.message)}
    else{clearInterval(timer);$('go').disabled=false;
      if(s.state==='done'){show('✓ '+(s.title||'Listo')+' — guardado en la carpeta MP3','ok');$('url').value=''}
      else{show(s.message,'err')}}
  },700);
};
$('url').addEventListener('keydown',e=>{if(e.key==='Enter')$('go').click()});
$('open').onclick=()=>post('/open');
$('quit').onclick=async()=>{await post('/quit');document.body.innerHTML='<p style="font:16px system-ui;padding:40px;text-align:center">Aplicación cerrada. Ya puedes cerrar esta pestaña.</p>'};
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        if not self._host_ok():
            return self._json(403, {"error": "Host no permitido"})
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if parsed.path == "/info":
            return self._json(200, {"dir": str(OUT_DIR), "ytdlp": yt_dlp.version.__version__})
        if parsed.path == "/ping":
            global LAST_PING
            LAST_PING = time.time()
            return self._json(200, {"app": "mp3dl"})
        if parsed.path == "/status":
            job = JOBS.get(parse_qs(parsed.query).get("id", [""])[0])
            if not job:
                return self._json(404, {"state": "error", "message": "Tarea no encontrada"})
            return self._json(200, job)
        self._json(404, {"error": "No encontrado"})

    def do_POST(self):
        # Exigir JSON + Host local: evita que otras webs lancen descargas en tu equipo.
        if not self._host_ok() or "application/json" not in self.headers.get("Content-Type", ""):
            return self._json(403, {"error": "Petición no permitida"})
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 10_000)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "Petición no válida"})

        path = urlparse(self.path).path
        if path == "/open":
            try:
                open_folder()
            except Exception as e:  # noqa: BLE001
                return self._json(500, {"error": str(e)})
            return self._json(200, {"ok": True})

        if path == "/quit":
            self._json(200, {"ok": True})
            threading.Timer(0.3, lambda: os._exit(0)).start()
            return

        if path == "/download":
            url = str(body.get("url", "")).strip()
            if not re.match(r"^https?://", url, re.I):
                return self._json(400, {"error": "El enlace debe empezar por http:// o https://"})
            quality = str(body.get("quality", "192"))
            if quality not in QUALITIES:
                quality = "192"
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            job_id = uuid.uuid4().hex[:10]
            with LOCK:
                JOBS[job_id] = {"id": job_id, "state": "running", "percent": 0,
                                "message": "Iniciando…", "title": ""}
            threading.Thread(target=run_job, args=(job_id, url, quality, bool(body.get("playlist"))),
                             daemon=True).start()
            return self._json(200, {"id": job_id})

        self._json(404, {"error": "No encontrado"})


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=2) as r:
            return json.load(r).get("app") == "mp3dl"
    except Exception:  # noqa: BLE001
        return False


def watchdog():
    """Se cierra solo cuando se cierra la pestaña (y no hay descargas en curso)."""
    while True:
        time.sleep(5)
        busy = any(j["state"] == "running" for j in JOBS.values())
        if not busy and time.time() - LAST_PING > IDLE_LIMIT:
            os._exit(0)


def main():
    global PORT
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        if already_running(PORT):  # ya hay una ventana abierta: la reutilizamos
            webbrowser.open(f"http://localhost:{PORT}")
            return
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        PORT = server.server_address[1]
    url = f"http://localhost:{PORT}"
    log(f"Descargador MP3 funcionando en {url}\nLos MP3 se guardan en: {OUT_DIR}\n"
        "Cierra esta ventana o pulsa Ctrl+C para salir.")
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("\nHasta pronto.")


if __name__ == "__main__":
    main()
