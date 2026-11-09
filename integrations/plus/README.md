# img2threejs plus: tools for photo-matched realism

Optional tools for reconstructions that must line up with the reference photo, not just resemble
it. They live outside `forge/`, so the core stays stdlib-only; nothing in the pipeline calls them
unless you do.

| Command | What it does | Output |
|---|---|---|
| `camera` | Solves the photo's camera from measured image points (PnP + grid search over focal length and unknown box dimensions) | `camera.json` |
| `lift` | Pixel → world point on a plane (`y=0` for the ground, `z=D/2` for a front face) | JSON |
| `project` | World points → pixels, to check a placement against the photo | JSON |
| `render` | Headless renders of a generated factory from the solved camera and orbit views (Chromium + SwiftShader, no GPU) | PNG per view |
| `compare` | Side-by-side, 50 % overlay, silhouette XOR map, silhouette IoU | PNGs + JSON |
| `crops` | Per-part sheet: the same pixel boxes cut from the photo and the reference-view render | PNG |
| `tone measure` / `tone apply` | Colour calibration: photo ÷ render ratio per region in linear light, accumulated across rounds, written back into material base colours | `compensation.json`, edited spec |

## Agent skill

`skill/img2threejs-plus/` is a companion skill that tells the agent when and how to use these
tools inside the base pipeline. Link it next to the base skill:

```bash
ln -sfn "$PWD/integrations/plus/skill/img2threejs-plus" ~/.claude/skills/img2threejs-plus
ln -sfn "$PWD/integrations/plus/skill/img2threejs-plus" ~/.codex/skills/img2threejs-plus
```

## Install

Python 3.10+ with numpy, opencv, pillow, playwright; Node 18+ for the viewer bundle
(`render` runs `npm install` in `viewer/` on first use).

```bash
pip install -r integrations/plus/requirements.txt
python3 -m playwright install chromium     # skip if a Playwright Chromium is already installed
```

## Workflow

**1. Camera.** Mark corners of the subject's main box in the photo and write a points file. Give
known dimensions as numbers and unknown ones as ranges; the solver searches them. Corner names are
three letters: `F`/`B` front or back, `T`/`B` top or bottom, `L`/`R` left or right.

```json
{"image": [1373, 1145],
 "focal": {"min": 1500, "max": 14000, "steps": 51},
 "box": {"W": {"min": 0.7, "max": 0.9, "steps": 21}, "H": 1.15, "D": {"min": 0.1, "max": 0.4, "steps": 31}},
 "corners": {"FTL": [565, 253], "FTR": [1074, 277], "FBL": [565, 1001], "FBR": [1072, 1079],
             "BTL": [603, 222], "BTR": [1121, 262], "BBR": [1127, 1049]},
 "points": [{"name": "foot", "world": [0, 0, 0.09], "px": [820, 1060]}]}
```

```bash
python3 integrations/plus/plus.py camera points.json --out camera.json
```

Aim for an RMS under ~10 px; `residualsPx` shows which point is off. Seven corners on two faces
are usually enough. Fewer than four points are refused.

**2. Place parts from the photo.** A part that rests on the ground or sits on a known face can be
placed by lifting its pixel onto that plane:

```bash
python3 integrations/plus/plus.py lift --px 302 782 --plane y=0.24
python3 integrations/plus/plus.py project --world 0.1 0 0.05  -0.4 1.15 0.09
```

**3. Render and compare.** `render` bundles `viewer/main.ts` against the factory and the camera.
Put texture maps in a folder and pass it as `--assets`; it is served next to the page.

```bash
python3 integrations/plus/plus.py render --factory src/createObjectModel.ts --camera camera.json \
  --assets public --out renders/pass1 ref="view=ref" stripped="view=ref&strip=1" right="az=90&el=4"
python3 integrations/plus/plus.py compare --reference reference.png --render renders/pass1/ref.png --out renders/pass1/cmp
```

The factory needs a `create…Model` export; `configure…Renderer`, `create…Environment` and
`create…LookDevLights` are used when present (the generator emits all four).

**4. Colour.** The renderer's tone mapping shifts every albedo. Pick a flat, evenly lit patch per
colour in the photo, then measure and apply; repeat render → measure → apply two or three times.

```bash
echo '{"red": [600, 560, 650, 640], "silver": [960, 880, 1020, 940]}' > regions.json
echo '{"red": "red", "red-rib": "red", "silver": "silver"}' > tone-map.json
python3 integrations/plus/plus.py tone measure --reference reference.png --render renders/pass1/ref.png --regions regions.json
python3 integrations/plus/plus.py tone apply --spec object-sculpt-spec.json --map tone-map.json
```

`apply` records the original colour in `toneMappingCompensation.referenceAlbedo` and always starts
from it, so running it twice does not compound.

## Limits

- One pinhole camera with a centred principal point and no lens distortion. Strong wide-angle
  distortion will show up as residuals.
- Generated reference images often have inconsistent perspective between parts. If one part fits
  and another does not, solve the main body and place the rest with `lift`; do not chase the RMS.
- `compare` finds the silhouette by difference from the border colour: it needs a plain backdrop.
- Colour ratios hold for the light rig they were measured under. Change the rig, measure again.

## Tests

```bash
python3 -m unittest discover -s integrations/plus/tests
```
