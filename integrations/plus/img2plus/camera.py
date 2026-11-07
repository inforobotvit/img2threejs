"""Reference-camera solve, image-point lifting and projection.

The reference photo is matched by a pinhole camera with a centred principal point. Its pose comes
from OpenCV PnP over measured image points; whatever is unknown (focal length, box dimensions) is
found by grid search on the reprojection error.

World frame (same as the generated factories): metres, +Y up, the subject's front faces +Z,
origin at the centre of the subject's footprint on the ground.

Box corners are named by three letters: F/B (front +Z / back -Z), T/B (top y=H / bottom y=0),
L/R (left -X / right +X). Example: "FTL" = front-top-left.
"""
from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass

import cv2
import numpy as np


def _range(spec, default=None):
    """A dimension is a number, or {"min", "max", "steps"}."""
    if spec is None:
        spec = default
    if isinstance(spec, (int, float)):
        return np.array([float(spec)])
    return np.linspace(float(spec["min"]), float(spec["max"]), int(spec.get("steps", 21)))


def corner_world(name: str, W: float, H: float, D: float) -> tuple[float, float, float]:
    name = name.upper()
    if len(name) != 3 or name[0] not in "FB" or name[1] not in "TB" or name[2] not in "LR":
        raise ValueError(f"corner name must look like FTL/BBR, got {name!r}")
    z = D / 2 if name[0] == "F" else -D / 2
    y = H if name[1] == "T" else 0.0
    x = -W / 2 if name[2] == "L" else W / 2
    return (x, y, z)


@dataclass
class Solution:
    rms: float
    focal: float
    dims: dict
    rvec: np.ndarray
    tvec: np.ndarray
    residuals: dict


def _intrinsics(f: float, w: int, h: int) -> np.ndarray:
    return np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]], dtype=np.float64)


def _pnp(obj: np.ndarray, img: np.ndarray, K: np.ndarray):
    flags = cv2.SOLVEPNP_ITERATIVE if len(obj) >= 6 else cv2.SOLVEPNP_SQPNP
    ok, rvec, tvec = cv2.solvePnP(obj, img, K, None, flags=flags)
    if not ok:
        return None
    rvec, tvec = cv2.solvePnPRefineLM(obj, img, K, None, rvec, tvec)
    proj, _ = cv2.projectPoints(obj, rvec, tvec, K, None)
    d = proj.reshape(-1, 2) - img
    if (cv2.Rodrigues(rvec)[0] @ obj.T + tvec).T[:, 2].min() <= 0:  # points behind the camera
        return None
    return float(np.sqrt(np.mean(np.sum(d ** 2, axis=1)))), rvec, tvec, np.linalg.norm(d, axis=1)


def solve(cfg: dict) -> Solution:
    """cfg: {"image": [w, h], "focal": num|range, "box": {"W","H","D": num|range},
    "corners": {"FTL": [px, py], ...}, "points": [{"name"?, "world": [x,y,z], "px": [x,y]}]}"""
    w, h = (int(v) for v in cfg["image"])
    corners = {k.upper(): v for k, v in (cfg.get("corners") or {}).items()}
    points = cfg.get("points") or []
    if len(corners) + len(points) < 4:
        raise ValueError("need at least 4 measured points (corners + points)")
    box = cfg.get("box") or {}
    if corners and not {"W", "H", "D"} <= set(box):
        raise ValueError("box corners need box.W, box.H and box.D (numbers or ranges)")
    focals = _range(cfg.get("focal"), {"min": 0.5 * max(w, h), "max": 12 * max(w, h), "steps": 60})
    Ws, Hs, Ds = (_range(box.get(k), 1.0) for k in "WHD")
    names = list(corners) + [p.get("name", f"p{i}") for i, p in enumerate(points)]
    img = np.array(list(corners.values()) + [p["px"] for p in points], dtype=np.float64)
    fixed = [p["world"] for p in points]

    best = None
    for W, H, D in itertools.product(Ws, Hs, Ds):
        obj = np.array([corner_world(n, W, H, D) for n in corners] + fixed, dtype=np.float64)
        for f in focals:
            r = _pnp(obj, img, _intrinsics(f, w, h))
            if r and (best is None or r[0] < best[0]):
                best = (r[0], f, W, H, D, r[1], r[2], r[3])
    if best is None:
        raise RuntimeError("PnP failed for every candidate; check point order and units")
    rms, f, W, H, D, rvec, tvec, res = best
    dims = {"W": float(W), "H": float(H), "D": float(D)} if corners else {}
    return Solution(rms, float(f), dims, rvec, tvec, dict(zip(names, (float(x) for x in res))))


def camera_json(sol: Solution, image: list) -> dict:
    w, h = image
    R, _ = cv2.Rodrigues(sol.rvec)
    pos = (-R.T @ sol.tvec).ravel()
    forward = R.T @ np.array([0, 0, 1.0])       # OpenCV camera looks down +Z
    up = -(R.T @ np.array([0, 1.0, 0]))           # OpenCV image y points down
    r = lambda v, n=4: [round(float(x), n) for x in v]
    out = {
        "rmsPx": round(sol.rms, 2),
        "focalPx": round(sol.focal, 1),
        "fovVerticalDeg": round(math.degrees(2 * math.atan(h / 2 / sol.focal)), 3),
        "position": r(pos),
        "target": r(pos + forward * np.linalg.norm(pos)),
        "up": r(up),
        "image": [int(w), int(h)],
        "rvec": r(sol.rvec.ravel(), 6),
        "tvec": r(sol.tvec.ravel(), 6),
        "residualsPx": {k: round(v, 1) for k, v in sol.residuals.items()},
    }
    if sol.dims:
        out["box"] = {k: round(v, 4) for k, v in sol.dims.items()}
    return out


class Camera:
    """A solved camera loaded from camera.json."""

    def __init__(self, cam: dict):
        self.w, self.h = cam["image"]
        self.f = cam["focalPx"]
        self.K = _intrinsics(self.f, self.w, self.h)
        self.R, _ = cv2.Rodrigues(np.array(cam["rvec"], float))
        self.t = np.array(cam["tvec"], float).reshape(3)
        self.centre = -self.R.T @ self.t

    @classmethod
    def load(cls, path: str) -> "Camera":
        with open(path) as fh:
            return cls(json.load(fh))

    def project(self, points) -> np.ndarray:
        P = np.asarray(points, float).reshape(-1, 3) @ self.R.T + self.t
        return np.stack([self.f * P[:, 0] / P[:, 2] + self.w / 2, self.f * P[:, 1] / P[:, 2] + self.h / 2], axis=1)

    def ray(self, px) -> np.ndarray:
        d = self.R.T @ (np.linalg.inv(self.K) @ np.array([px[0], px[1], 1.0]))
        return d / np.linalg.norm(d)

    def lift(self, px, axis: str, value: float) -> np.ndarray:
        """World point where the pixel's ray meets the plane axis=value (axis in x/y/z)."""
        i = "xyz".index(axis)
        d = self.ray(px)
        if abs(d[i]) < 1e-9:
            raise ValueError(f"ray is parallel to the plane {axis}={value}")
        s = (value - self.centre[i]) / d[i]
        if s <= 0:
            raise ValueError(f"plane {axis}={value} is behind the camera for pixel {px}")
        return self.centre + s * d
