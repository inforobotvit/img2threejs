#!/usr/bin/env python3
"""img2threejs plus: realism tools for photo-matched reconstructions.

  camera   solve the reference camera from measured points       -> camera.json
  lift     pixel -> world point on a plane (x|y|z = value)
  project  world point(s) -> pixels in the reference
  render   headless renders of a generated factory (ref camera, orbit views)
  compare  side-by-side, overlay, silhouette XOR + IoU vs the photo
  crops    per-part sheet: the same boxes cut from photo and render, side by side
  tone     measure | apply  colour calibration under the renderer's tone mapping

Every command prints JSON. See integrations/plus/README.md.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def _dump(obj) -> None:
    print(json.dumps(obj, indent=1, ensure_ascii=False))


def cmd_camera(a):
    from img2plus import camera
    cfg = json.loads(pathlib.Path(a.points).read_text())
    sol = camera.solve(cfg)
    out = camera.camera_json(sol, cfg["image"])
    pathlib.Path(a.out).write_text(json.dumps(out, indent=1))
    _dump(out)
    if out["rmsPx"] > a.warn_px:
        print(f"warning: rms {out['rmsPx']} px > {a.warn_px}; recheck the worst residuals", file=sys.stderr)


def cmd_lift(a):
    from img2plus.camera import Camera
    axis, value = a.plane.split("=")
    p = Camera.load(a.camera).lift((a.px[0], a.px[1]), axis.strip().lower(), float(value))
    _dump({"px": a.px, "plane": a.plane, "world": [round(float(v), 4) for v in p]})


def cmd_project(a):
    from img2plus.camera import Camera
    pts = [a.world[i:i + 3] for i in range(0, len(a.world), 3)]
    px = Camera.load(a.camera).project(pts)
    _dump([{"world": w, "px": [round(float(v), 1) for v in p]} for w, p in zip(pts, px)])


def cmd_render(a):
    from img2plus import render
    views = dict(v.split("=", 1) for v in a.views) or {"ref": "view=ref"}
    _dump(render.capture(a.factory, a.camera, a.out, views, assets=a.assets))


def cmd_compare(a):
    from img2plus import compare
    _dump(compare.compare(a.reference, a.render, a.out, a.threshold))


def cmd_crops(a):
    from img2plus import compare
    _dump(compare.crops(a.reference, a.render, json.loads(pathlib.Path(a.boxes).read_text()), a.out))


def cmd_tone(a):
    from img2plus import tone
    if a.action == "measure":
        regions = json.loads(pathlib.Path(a.regions).read_text())
        state, rows = tone.measure(a.reference, a.render, regions, tone.load_json(a.state, {}))
        pathlib.Path(a.state).write_text(json.dumps(state, indent=1))
        _dump(rows)
    else:
        spec = json.loads(pathlib.Path(a.spec).read_text())
        mapping = json.loads(pathlib.Path(a.map).read_text())
        changed = tone.apply(spec, tone.load_json(a.state, {}), mapping)
        pathlib.Path(a.spec).write_text(json.dumps(spec, indent=2, ensure_ascii=False))
        _dump({"changed": changed})


def main(argv=None):
    p = argparse.ArgumentParser(prog="plus.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("camera", help="solve the reference camera")
    s.add_argument("points", help="points JSON (see examples/camera-box.json)")
    s.add_argument("--out", default="camera.json")
    s.add_argument("--warn-px", type=float, default=10.0)
    s.set_defaults(fn=cmd_camera)

    s = sub.add_parser("lift", help="pixel to world point on a plane")
    s.add_argument("--camera", default="camera.json")
    s.add_argument("--px", type=float, nargs=2, required=True)
    s.add_argument("--plane", required=True, help="e.g. y=0 (ground) or z=0.12 (front face)")
    s.set_defaults(fn=cmd_lift)

    s = sub.add_parser("project", help="world points to reference pixels")
    s.add_argument("--camera", default="camera.json")
    s.add_argument("--world", type=float, nargs="+", required=True, help="x y z [x y z ...]")
    s.set_defaults(fn=cmd_project)

    s = sub.add_parser("render", help="headless renders of a factory")
    s.add_argument("--factory", required=True, help="generated createObjectModel.ts")
    s.add_argument("--camera", default="camera.json")
    s.add_argument("--out", required=True)
    s.add_argument("--assets", help="folder served next to the page (texture maps)")
    s.add_argument("views", nargs="*", help='name=query, e.g. ref="view=ref" right="az=90&el=4"')
    s.set_defaults(fn=cmd_render)

    s = sub.add_parser("compare", help="review images and silhouette IoU")
    s.add_argument("--reference", required=True)
    s.add_argument("--render", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--threshold", type=float, default=18.0)
    s.set_defaults(fn=cmd_compare)

    s = sub.add_parser("crops", help="per-part photo | render sheet")
    s.add_argument("--reference", required=True)
    s.add_argument("--render", required=True, help="render from the reference camera (view=ref)")
    s.add_argument("--boxes", required=True, help='{"claw-r": [x0, y0, x1, y1], ...} in reference pixels')
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_crops)

    s = sub.add_parser("tone", help="colour calibration")
    s.add_argument("action", choices=["measure", "apply"])
    s.add_argument("--state", default="compensation.json")
    s.add_argument("--reference")
    s.add_argument("--render")
    s.add_argument("--regions", help='measure: {"key": [x0, y0, x1, y1]}')
    s.add_argument("--spec", help="apply: object-sculpt-spec.json (edited in place)")
    s.add_argument("--map", help='apply: {"materialId": "regionKey"}')
    s.set_defaults(fn=cmd_tone)

    a = p.parse_args(argv)
    if a.cmd == "tone":
        need = ("reference", "render", "regions") if a.action == "measure" else ("spec", "map")
        missing = [f"--{n}" for n in need if not getattr(a, n)]
        if missing:
            p.error(f"tone {a.action} needs {' '.join(missing)}")
    a.fn(a)


if __name__ == "__main__":
    main()
