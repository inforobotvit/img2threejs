"""A tube / curve-sweep that carries its own authored path keeps that geometry.

`tube` and `curve-sweep` are in ATTACHMENT_PRIMITIVES, so strict validation requires a complete
attachment block (localStart/localEnd) on them. The generator treated any attachment on those
primitives as an instruction to build a straight endpoint cylinder, so a cable authored as a
measured `tubePath` -- valid and strict-clean -- shipped as a straight rod. A sweep that carries its
own path now keeps it; the attachment stays a contract for the anchor gate.

Run: python3 -m unittest forge.tests.test_authored_sweep_path
"""
import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "_shared"))
sys.path.insert(0, str(HERE.parent / "stage2_spec"))
sys.path.insert(0, str(HERE.parent / "stage3_build"))

import generate_threejs_factory  # noqa: E402

FIXTURE = HERE / "fixtures" / "reference_target_conformance_spec.json"


def spec_with(component: dict) -> dict:
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    root = spec["componentTree"][0]
    part = copy.deepcopy(root)
    part.update(component)
    part["parent"] = root["id"]
    part["level"] = root.get("level", "macro")
    spec["componentTree"].append(part)
    return spec


def first_pass(spec: dict) -> str:
    passes = spec.get("buildPasses") or []
    return passes[0]["id"] if passes and isinstance(passes[0], dict) and passes[0].get("id") else "blockout"


ATTACH = {"parentSocket": "root", "contactType": "embed", "embedDepth": 0.002, "gapTolerance": 0.003,
          "localStart": [0, 0, 0], "localEnd": [0, 1, 0], "baseRadius": 0.01, "endRadius": 0.01}


class AuthoredSweepsKeepTheirPath(unittest.TestCase):
    def source_for(self, primitive: str, descriptor_key: str | None, descriptor: dict | None) -> str:
        geometry = {"topologyIntent": "cable"}
        if descriptor_key:
            geometry[descriptor_key] = descriptor
        spec = spec_with({"id": "cable", "name": "Cable", "primitive": primitive,
                          "geometryDescriptor": geometry, "attachment": dict(ATTACH),
                          "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0], "scale": [1, 1, 1]}})
        return generate_threejs_factory.generate(spec, first_pass(spec))

    def cable_block(self, source: str) -> str:
        start = source.index('"Cable__pivot"')
        end = source.find("__pivot", start + len('"Cable__pivot"'))
        return source[start:end if end > 0 else len(source)]

    def test_tube_with_authored_path_is_built_from_the_path(self):
        path = {"points": [[0, 0, 0], [0.2, 0.3, 0], [0.5, 0.1, 0.2]], "radius": 0.01}
        source = self.source_for("tube", "tubePath", path)
        self.assertIn("buildTubeGeometry(", self.cable_block(source))
        self.assertRegex(source, r"const endpoint_cable_\d+ = makeAttachmentEndpoint\(null\)")

    def test_curve_sweep_with_authored_spine_is_built_from_the_spine(self):
        sweep = {"spine": [[0, 0, 0], [0.3, 0.4, 0], [0.6, 0, 0]],
                 "crossSection": {"points": [[-0.002, -0.01], [0.002, -0.01], [0.002, 0.01], [-0.002, 0.01]]}}
        source = self.source_for("curve-sweep", "curveSweep", sweep)
        self.assertIn("buildCurveSweepGeometry(", self.cable_block(source))
        self.assertRegex(source, r"const endpoint_cable_\d+ = makeAttachmentEndpoint\(null\)")

    def test_cylinder_still_derives_its_geometry_from_the_endpoints(self):
        """Negative control: endpoint-derived limbs are unchanged."""
        source = self.source_for("cylinder", None, None)
        self.assertNotRegex(source, r"const endpoint_cable_\d+ = makeAttachmentEndpoint\(null\)")

if __name__ == "__main__":
    unittest.main()
