"""Colour calibration between the reference photo and a render from the solved reference camera.

The renderer's tone mapping (ACES by default in the generated factories) and the look-dev lights
shift every albedo. Because the render uses the photo's camera, the same pixel box samples the same
part in both images, so each material's base colour can be corrected by the ratio photo / render
in linear light. Ratios accumulate across iterations in a state file; two or three rounds usually
converge to within a few sRGB levels.

`apply` is idempotent: it always starts from the albedo recorded the first time
(`toneMappingCompensation.referenceAlbedo`), never from an already corrected colour.
"""
from __future__ import annotations

import json

import numpy as np
from PIL import Image


def to_linear(c):
    c = np.asarray(c, float) / 255
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_srgb(v):
    v = np.clip(np.asarray(v, float), 0, None)
    return np.clip(np.where(v <= 0.0031308, v * 12.92, 1.055 * v ** (1 / 2.4) - 0.055), 0, 1) * 255


def _median(img: np.ndarray, box) -> np.ndarray:
    x0, y0, x1, y1 = (int(v) for v in box)
    patch = img[y0:y1, x0:x1].reshape(-1, 3)
    if patch.size == 0:
        raise ValueError(f"empty region {box}")
    return np.median(patch, axis=0)


def measure(reference: str, render: str, regions: dict, state: dict | None = None,
            clip=(0.05, 6.0)) -> tuple[dict, list]:
    """regions: {key: [x0, y0, x1, y1]} in reference pixels. Returns (new state, report rows)."""
    ref = np.asarray(Image.open(reference).convert("RGB")).astype(float)
    ren = Image.open(render).convert("RGB")
    if ren.size != (ref.shape[1], ref.shape[0]):
        ren = ren.resize((ref.shape[1], ref.shape[0]))
    ren = np.asarray(ren).astype(float)
    state = dict(state or {})
    rows = []
    for key, box in regions.items():
        r, f = _median(ren, box), _median(ref, box)
        step = (to_linear(f) / np.maximum(to_linear(r), 1e-4)).clip(*clip)
        total = np.array(state.get(key, [1, 1, 1]), float) * step
        state[key] = total.round(4).tolist()
        rows.append({"region": key, "render": r.round().tolist(), "reference": f.round().tolist(),
                     "step": step.round(3).tolist(), "total": state[key],
                     "maxDeltaLevels": float(np.abs(r - f).max())})
    return state, rows


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(round(v)) for v in c)


def apply(spec: dict, state: dict, mapping: dict) -> list:
    """mapping: {materialId: regionKey}. Edits spec in place; returns the changed material ids."""
    changed = []
    for m in spec.get("materials", []):
        key = mapping.get(m.get("id"))
        if not key or key not in state:
            continue
        comp = m.get("toneMappingCompensation") or {}
        base = comp.get("referenceAlbedo") or m.get("baseColor") or m.get("color")
        h = base.lstrip("#")
        rgb = np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)
        new = _hex(to_srgb(to_linear(rgb) * np.array(state[key], float)))
        m["toneMappingCompensation"] = {"referenceAlbedo": base, "linearScale": state[key], "ratioSource": key}
        m["baseColor"] = new
        if "color" in m:
            m["color"] = new
        changed.append(m["id"])
    return changed


def load_json(path: str, default=None):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
