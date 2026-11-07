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
