"""Synthetic checks for integrations/plus. Run: python3 -m unittest discover -s integrations/plus/tests"""
import json
import pathlib
import sys
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from img2plus import camera, compare, tone  # noqa: E402


def synthetic_view(f=2400.0, W=0.8, H=1.1, D=0.25, image=(1400, 1100)):
    rvec = np.array([0.32, -0.55, 0.05])
    tvec = np.array([-0.05, -0.4, 4.2])
    K = np.array([[f, 0, image[0] / 2], [0, f, image[1] / 2], [0, 0, 1]])
    names = ["FTL", "FTR", "FBL", "FBR", "BTL", "BTR", "BBR"]
    obj = np.array([camera.corner_world(n, W, H, D) for n in names])
    px, _ = cv2.projectPoints(obj, rvec, tvec, K, None)
    return dict(zip(names, px.reshape(-1, 2).tolist())), rvec, tvec


class CameraSolve(unittest.TestCase):
    def test_recovers_focal_and_box(self):
        corners, _, _ = synthetic_view()
        cfg = {"image": [1400, 1100], "focal": {"min": 1500, "max": 3500, "steps": 41},
               "box": {"W": {"min": 0.7, "max": 0.9, "steps": 21}, "H": 1.1, "D": {"min": 0.15, "max": 0.35, "steps": 21}},
               "corners": corners}
        sol = camera.solve(cfg)
        self.assertLess(sol.rms, 0.5)
        self.assertAlmostEqual(sol.focal, 2400, delta=60)
        self.assertAlmostEqual(sol.dims["W"], 0.8, delta=0.011)
        self.assertAlmostEqual(sol.dims["D"], 0.25, delta=0.011)

    def test_lift_and_project_round_trip(self):
        corners, rvec, tvec = synthetic_view()
        cfg = {"image": [1400, 1100], "focal": 2400, "box": {"W": 0.8, "H": 1.1, "D": 0.25}, "corners": corners}
        cam = camera.Camera(camera.camera_json(camera.solve(cfg), cfg["image"]))
        world = np.array([0.1, 0.0, 0.05])
        px = cam.project(world)[0]
        back = cam.lift(px, "y", 0.0)
        self.assertLess(np.abs(back - world).max(), 1e-3)
        np.testing.assert_allclose(cam.project(camera.corner_world("FTL", 0.8, 1.1, 0.25))[0], corners["FTL"], atol=0.5)

    def test_rejects_bad_names_and_too_few_points(self):
        with self.assertRaises(ValueError):
            camera.corner_world("XYZ", 1, 1, 1)
        with self.assertRaises(ValueError):
            camera.solve({"image": [100, 100], "box": {"W": 1, "H": 1, "D": 1}, "corners": {"FTL": [1, 1]}})


class Tone(unittest.TestCase):
    def test_measure_then_apply_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            ref = pathlib.Path(d, "ref.png"); ren = pathlib.Path(d, "ren.png")
            Image.new("RGB", (40, 40), (200, 30, 40)).save(ref)
            Image.new("RGB", (40, 40), (150, 40, 40)).save(ren)
            state, rows = tone.measure(str(ref), str(ren), {"red": [5, 5, 30, 30]})
            self.assertGreater(state["red"][0], 1.0)
            self.assertLess(state["red"][1], 1.0)
            spec = {"materials": [{"id": "body", "baseColor": "#c81e28", "color": "#c81e28"}]}
            tone.apply(spec, state, {"body": "red"})
            first = spec["materials"][0]["baseColor"]
            tone.apply(spec, state, {"body": "red"})
            self.assertEqual(spec["materials"][0]["baseColor"], first)
            self.assertEqual(spec["materials"][0]["toneMappingCompensation"]["referenceAlbedo"], "#c81e28")

    def test_srgb_round_trip(self):
        c = np.array([0, 13, 128, 255], float)
        np.testing.assert_allclose(tone.to_srgb(tone.to_linear(c)), c, atol=1e-6)


class Compare(unittest.TestCase):
    def test_iou_of_offset_squares(self):
        with tempfile.TemporaryDirectory() as d:
            a = np.full((100, 100, 3), 245, np.uint8); a[20:60, 20:60] = (200, 30, 40)
            b = np.full((100, 100, 3), 245, np.uint8); b[20:60, 30:70] = (200, 30, 40)
            Image.fromarray(a).save(pathlib.Path(d, "a.png")); Image.fromarray(b).save(pathlib.Path(d, "b.png"))
            r = compare.compare(str(pathlib.Path(d, "a.png")), str(pathlib.Path(d, "b.png")), d)
            self.assertAlmostEqual(r["silhouetteIoU"], 1200 / 2000, places=3)
            self.assertTrue(pathlib.Path(r["files"]["xor"]).exists())


class Cli(unittest.TestCase):
    def test_camera_command_writes_json(self):
        import subprocess
        corners, _, _ = synthetic_view()
        with tempfile.TemporaryDirectory() as d:
            pts = pathlib.Path(d, "points.json")
            pts.write_text(json.dumps({"image": [1400, 1100], "focal": 2400, "box": {"W": 0.8, "H": 1.1, "D": 0.25}, "corners": corners}))
            out = pathlib.Path(d, "camera.json")
            plus = pathlib.Path(__file__).resolve().parents[1] / "plus.py"
            subprocess.run([sys.executable, str(plus), "camera", str(pts), "--out", str(out)], check=True, capture_output=True)
            cam = json.loads(out.read_text())
            self.assertLess(cam["rmsPx"], 0.5)
            self.assertEqual(set(cam["box"]), {"W", "H", "D"})


if __name__ == "__main__":
    unittest.main()
