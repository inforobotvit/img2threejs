#!/usr/bin/env python3
"""Spec-level override of the silhouette IoU gate.

A reference whose parts do not share one perspective (common for generated images) cannot reach
IoU 0.85 with any model. The spec may lower the bar with a stated reason, never below the floor,
and the diagnosis reports which threshold it applied.

Run: python3 forge/tests/test_review_threshold_override.py
"""
import json
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stage4_review"))

from diagnose_render import (  # noqa: E402
    SILHOUETTE_IOU_FLOOR,
    SILHOUETTE_IOU_THRESHOLD,
    run_tier1,
    silhouette_iou_threshold,
)

SIZE = 128
REASON = "generated reference: headphones and body are drawn in different perspectives"


def write_png(path: Path, inside) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = bytearray()
    for y in range(SIZE):
        raw.append(0)
        for x in range(SIZE):
            raw += bytes((200, 30, 40) if inside(x, y) else (245, 245, 245))
    ihdr = struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b""))


def minimal_spec(**extra) -> dict:
    return {"componentTree": [], "materials": [], **extra}


class ThresholdResolution(unittest.TestCase):
    def test_default_without_override(self):
        value, info = silhouette_iou_threshold(minimal_spec())
        self.assertEqual(value, SILHOUETTE_IOU_THRESHOLD)
        self.assertEqual(info["source"], "default")
        self.assertEqual(silhouette_iou_threshold(None)[0], SILHOUETTE_IOU_THRESHOLD)

    def test_override_with_reason(self):
        value, info = silhouette_iou_threshold(minimal_spec(reviewThresholds={"silhouetteIoU": {"min": 0.72, "reason": REASON}}))
        self.assertEqual(value, 0.72)
        self.assertEqual(info["source"], "spec.reviewThresholds")
        self.assertEqual(info["reason"], REASON)

    def test_override_cannot_switch_the_gate_off(self):
        for bad in ({"min": SILHOUETTE_IOU_FLOOR - 0.01, "reason": REASON},
                    {"min": 0.0, "reason": REASON},
                    {"min": 0.72},
                    {"min": 0.72, "reason": "because"},
                    {"min": "0.7", "reason": REASON},
                    0.7):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                silhouette_iou_threshold(minimal_spec(reviewThresholds={"silhouetteIoU": bad}))


class Tier1UsesTheThreshold(unittest.TestCase):
    def run_pair(self, spec: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp)
            # same size, offset by 1/5 of the side: IoU 0.667, same aspect and scale
            write_png(t / "ref.png", lambda x, y: 24 <= x < 84 and 34 <= y < 94)
            write_png(t / "ren.png", lambda x, y: 36 <= x < 96 and 34 <= y < 94)
            (t / "spec.json").write_text(json.dumps(spec))
            return run_tier1(t / "ref.png", t / "ren.png", spec_path=t / "spec.json", pass_id="blockout-pass")

    def iou_failures(self, result: dict) -> list:
        return [f for f in result["failures"] if "silhouette IoU" in f]

    def test_default_threshold_rejects(self):
        result = self.run_pair(minimal_spec())
        self.assertLess(result["checks"]["silhouetteIoU"], SILHOUETTE_IOU_THRESHOLD)
        self.assertTrue(self.iou_failures(result))
        self.assertEqual(result["checks"]["silhouetteIoUThreshold"]["source"], "default")

    def test_lowered_threshold_accepts_and_is_reported(self):
        result = self.run_pair(minimal_spec(reviewThresholds={"silhouetteIoU": {"min": 0.62, "reason": REASON}}))
        self.assertFalse(self.iou_failures(result))
        self.assertEqual(result["checks"]["silhouetteIoUThreshold"]["value"], 0.62)

    def test_lowered_threshold_still_rejects_below_it(self):
        result = self.run_pair(minimal_spec(reviewThresholds={"silhouetteIoU": {"min": 0.8, "reason": REASON}}))
        self.assertTrue(any("lowered by spec.reviewThresholds" in f for f in self.iou_failures(result)))


if __name__ == "__main__":
    unittest.main()
