"""Headless review renders of a generated factory.

Bundles integrations/plus/viewer/main.ts against the factory and camera.json with esbuild, serves
the bundle over local HTTP (WebGL refuses textures from file://) and captures each view with
Playwright Chromium on SwiftShader, so it runs on machines without a GPU.

Views are name=query pairs:
  view=ref            the solved reference camera, viewport = photo size
  view=ref&strip=1    same, every material replaced by flat grey (map-stripped render)
  az=90&el=4          orbit view; optional fov, dist, tx/ty/tz (orbit target)
  mode=neutral        look-dev light rig passed to the factory (default: reference)
  ground=0.08         ground shadow opacity (default 0 for view=ref, 0.08 for orbit views)
"""
from __future__ import annotations

import base64
import os
import functools
import http.server
import pathlib
import shutil
import socketserver
import subprocess
import tempfile
import threading

VIEWER = pathlib.Path(__file__).resolve().parent.parent / "viewer"


def ensure_viewer_deps() -> None:
    if not (VIEWER / "node_modules" / "three").exists() or not (VIEWER / "node_modules" / "esbuild").exists():
        subprocess.run(["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"], cwd=VIEWER, check=True)


def bundle(factory: str, camera: str, out_dir: pathlib.Path) -> None:
    ensure_viewer_deps()
    esbuild = VIEWER / "node_modules" / ".bin" / "esbuild"
    subprocess.run([
        str(esbuild), str(VIEWER / "main.ts"), "--bundle", "--format=iife", "--log-level=error",
        f"--outfile={out_dir / 'bundle.js'}", "--loader:.json=json",
        f"--alias:@img2plus/factory={pathlib.Path(factory).resolve()}",
        f"--alias:@img2plus/camera={pathlib.Path(camera).resolve()}",
    ], check=True, cwd=VIEWER, env={**os.environ, "NODE_PATH": str(VIEWER / "node_modules")})
    shutil.copy(VIEWER / "index.html", out_dir / "index.html")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def capture(factory: str, camera: str, out: str, views: dict, assets: str | None = None,
            orbit_size=(1200, 900), timeout_ms: int = 180000) -> dict:
    import json
    from playwright.sync_api import sync_playwright

    cam = json.loads(pathlib.Path(camera).read_text())
    out_dir = pathlib.Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    logs: list[str] = []
    saved = {}
    with tempfile.TemporaryDirectory() as tmp:
        site = pathlib.Path(tmp)
        if assets:
            shutil.copytree(assets, site, dirs_exist_ok=True)
        bundle(factory, camera, site)
        srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(site)))
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
                for name, query in views.items():
                    size = cam["image"] if "view=ref" in query else orbit_size
                    page = browser.new_page(viewport={"width": int(size[0]), "height": int(size[1])})
                    page.on("pageerror", lambda e: logs.append(f"error: {e}"))
                    page.on("console", lambda m: logs.append(m.text) if m.type in ("error", "warning") else None)
                    page.goto(f"http://127.0.0.1:{port}/index.html?{query}")
                    page.wait_for_function("window.__READY__ === true", timeout=timeout_ms)
                    data = page.evaluate("document.querySelector('canvas').toDataURL('image/png')")
                    path = out_dir / f"{name}.png"
                    path.write_bytes(base64.b64decode(data.split(",", 1)[1]))
                    saved[name] = str(path)
                    page.close()
                browser.close()
        finally:
            srv.shutdown()
    return {"saved": saved, "console": logs[:20]}
