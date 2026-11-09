"""Review images for a render taken from the solved reference camera.

Writes side-by-side, 50 % overlay and a silhouette XOR map (red = only in the photo,
blue = only in the render), and reports silhouette IoU. The background is estimated from the
image border, so this works for subjects photographed on a plain backdrop.
"""
from __future__ import annotations

import pathlib

import numpy as np
from PIL import Image


def silhouette(img: np.ndarray, threshold: float = 18.0) -> np.ndarray:
    border = np.concatenate([img[0], img[-1], img[:, 0], img[:, -1]])
    bg = np.median(border, axis=0)
    return np.abs(img - bg).max(axis=2) > threshold


def compare(reference: str, render: str, out_dir: str, threshold: float = 18.0) -> dict:
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    a = Image.open(reference).convert("RGB")
    b = Image.open(render).convert("RGB").resize(a.size)
    w, h = a.size
    side = Image.new("RGB", (w, h), (255, 255, 255))
    side.paste(a.resize((w // 2, h // 2)), (0, h // 4))
    side.paste(b.resize((w // 2, h // 2)), (w // 2, h // 4))
    side.save(out / "side.png")
    Image.blend(a, b, 0.5).save(out / "overlay.png")

    A, B = np.asarray(a).astype(float), np.asarray(b).astype(float)
    ma, mb = silhouette(A, threshold), silhouette(B, threshold)
    xor = np.full(A.shape, 255, np.uint8)
    xor[ma & mb] = (205, 205, 205)
    xor[ma & ~mb] = (214, 40, 40)
    xor[~ma & mb] = (40, 90, 214)
    Image.fromarray(xor).save(out / "xor.png")
    union = int((ma | mb).sum())
    iou = float((ma & mb).sum() / union) if union else 1.0
    return {"silhouetteIoU": round(iou, 4),
            "onlyReferencePx": int((ma & ~mb).sum()), "onlyRenderPx": int((~ma & mb).sum()),
            "files": {k: str(out / f"{k}.png") for k in ("side", "overlay", "xor")}}


def crops(reference: str, render: str, boxes: dict, out: str, height: int = 360) -> dict:
    """Per-part review: the same pixel box cut from the photo and from the reference-camera render,
    placed side by side (photo | render) for every named box, one row per box."""
    a = Image.open(reference).convert("RGB")
    b = Image.open(render).convert("RGB").resize(a.size)
    rows = []
    for name, box in boxes.items():
        pair = [im.crop(tuple(int(v) for v in box)) for im in (a, b)]
        pair = [p.resize((max(1, int(p.width * height / p.height)), height)) for p in pair]
        row = Image.new("RGB", (pair[0].width + pair[1].width + 12, height), (255, 255, 255))
        row.paste(pair[0], (0, 0)); row.paste(pair[1], (pair[0].width + 12, 0))
        rows.append(row)
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height for r in rows) + 12 * (len(rows) - 1)), (255, 255, 255))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y)); y += r.height + 12
    pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return {"sheet": out, "parts": list(boxes)}
