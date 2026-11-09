---
name: img2threejs-plus
description: Companion to img2threejs for photo-matched realism. Use when an img2threejs reconstruction must line up with the reference photo (solve the photo camera, place parts from pixels, calibrate colours under tone mapping, render and compare headlessly), or when the user says the model is "not like the photo", colours are off, or parts do not connect.
license: Apache-2.0
---

# img2threejs plus

The base `img2threejs` skill builds a procedural model that resembles the reference. This skill
adds what it takes to make the model *line up* with the photo: the photo's camera, measured
placement, calibrated colour, and a review pass for how parts connect. It does not replace any
base gate; run the base pipeline as usual and use these tools inside its passes.

## Find the tools

The tools live in the img2threejs checkout under `integrations/plus/`. Locate the checkout from the
installed base skill and check the tools are there:

```bash
ROOT="$(cd "$(readlink -f ~/.claude/skills/img2threejs 2>/dev/null || readlink -f ~/.codex/skills/img2threejs)" && pwd)"
PLUS="$ROOT/integrations/plus/plus.py"
test -f "$PLUS" || echo "plus tools missing: install the inforobotvit/img2threejs fork (branch forge-plus)"
python3 -c "import cv2, numpy, PIL, playwright" || pip install -r "$ROOT/integrations/plus/requirements.txt"
```

If the checkout is the upstream release without `integrations/plus/`, say so and stop; do not
recreate the tools by hand. Full command reference: `integrations/plus/README.md`.

## When to use which step

| Situation | Step |
|---|---|
| The model must match the photo's viewpoint, or blockout IoU is stuck below the bar | 1. Camera |
| A part rests on the ground or sits on a known face (feet, cups, knobs, a plug) | 2. Place from pixels |
| Any pass that needs a render to judge | 3. Render and compare |
| Material pass; colours on the render differ from the photo | 4. Colour |
| The model has hinges, limbs or anything that will animate | 5. Jointed parts |
| Two references (photo, side view, close-up) disagree about a part | 6. Conflicting references |
| Before showing the model to anyone | 7. Connection review |

## 1. Camera

1. Pick the subject's main box-like body. Mark 6–8 of its corners in the photo, on at least two
   faces, at the apex of rounded corners. Write them to `points.json` with names `FTL`, `BBR`, …
   (front/back, top/bottom, left/right). See `integrations/plus/examples/camera-box.json`.
2. Give the one dimension you trust as a number (often height) and the others as ranges. Leave
   focal length as a range unless the photo's EXIF gives it.
3. `python3 "$PLUS" camera points.json --out camera.json`
4. Accept under ~10 px RMS. Above that, read `residualsPx`: one large residual is a mismarked
   point; uniformly large ones mean the body is not a box or the image has no single perspective.
5. Use the solved box dimensions in the spec, and build the generic orbit/review camera from
   `camera.json` so every pass is judged from the photo's viewpoint.

## 2. Place parts from pixels

For parts whose position you can see but not measure, lift the pixel onto the plane the part
touches, then check by projecting the placed point back:

```bash
python3 "$PLUS" lift --px 302 782 --plane y=0.24      # cup centre, 0.24 m above the ground
python3 "$PLUS" project --world -0.41 0.24 0.35       # should land on the same pixel
```

A free-floating part (a headband, a cable in the air) has no plane: fit its pose by minimising
distances between projected model points and marked pixels (scipy `least_squares` against
`Camera.project` from `integrations/plus/img2plus/camera.py`), with priors that keep it physical
(resting on the ground, not intersecting the body).

## 3. Render and compare

```bash
python3 "$PLUS" render --factory src/createObjectModel.ts --camera camera.json --assets public \
  --out renders/<pass> ref="view=ref" stripped="view=ref&strip=1" front="az=0&el=4" right="az=90&el=4" hero="az=38&el=16"
python3 "$PLUS" compare --reference reference.png --render renders/<pass>/ref.png --out renders/<pass>/cmp
```

Look at `cmp/side.png` and `cmp/xor.png` yourself (red = only in the photo, blue = only in the
render). The whole-object IoU hides part-level mistakes (an elbow bent the wrong way barely moves
it), so also compare every major part on its own: put pixel boxes around the arms, hands, feet,
face and so on, and cut the same boxes from the photo and the reference-view render:

```bash
python3 "$PLUS" crops --reference reference.png --render renders/<pass>/ref.png --boxes part-boxes.json --out renders/<pass>/parts.png
```

Close-up orbit views need an explicit distance (`dist=0.7&tx=..&ty=..&tz=..&fov=22`); a narrow
`fov` alone only moves the camera further away. The reference view renders without a cast ground
shadow on purpose (a long shadow would count as silhouette); orbit views keep it. Feed `renders/<pass>/ref.png` and `stripped.png` to the base `diagnose_render.py` as usual;
these renders are evidence for the base gates, not a substitute for them.

If the reference is a generated image whose parts are drawn in different perspectives, IoU 0.85 may
be unreachable with any model. Only after the camera is solved and the XOR map shows the remaining
mismatch comes from the reference, set `reviewThresholds.silhouetteIoU` in the spec
(`{"min": <value ≥ 0.6>, "reason": "<what in the reference prevents 0.85>"}`) and tell the user.
Never lower it to pass a model that is still wrong.

## 4. Colour

The renderer's tone mapping and look-dev lights shift every albedo, so colours picked from the
photo come out wrong on the render. Calibrate against the render from the photo camera:

1. Pick one flat, evenly lit patch per colour family in the photo (no highlights, no shadow edges).
   `regions.json`: `{"red": [x0, y0, x1, y1], ...}`. `tone-map.json`: material id → region key.
2. `python3 "$PLUS" tone measure --reference reference.png --render renders/<pass>/ref.png --regions regions.json`
3. `python3 "$PLUS" tone apply --spec object-sculpt-spec.json --map tone-map.json`
4. Regenerate, render, measure again. Stop when `maxDeltaLevels` is within ~10 or after three rounds.

For textured materials (foam, fabric, brushed metal) take the albedo map from the photo's pixels,
de-light it to the region median, and keep only damped local contrast; then calibrate as above.

- A generated factory renders a textured material with `color` = white, so the calibrated colour
  must be baked into the albedo map itself; re-run the calibration whenever the map changes.
- Do not tile a mirrored photo crop for a worn finish: mirroring turns rivets and streaks into
  symmetric ovals that read as wood grain. Synthesise the wear instead (seamless noise for
  mottling, rust specks, bare-metal scratches, enamel chips) using colours and coverage measured
  on the photo, and keep it sparse; the extractor's automatic map can also drift in white balance.

## 5. Jointed parts

Offsets in a hand-authored spec are usually composed in world axes, and the generator nests each
component under its parent node. That breaks as soon as a parent is rotated only to orient its own
geometry (a side-extruded link, a lathe turned onto its side): a child hinge then inherits the
rotation, and a "bend forward" about X becomes a bend sideways. Rules that held up in practice:

- Give every hinge its own small joint node (a sphere at the pivot) and attach links, caps and the
  next hinge to joint nodes only. Make the spec builder fail if a component is attached to a parent
  rotated for its geometry.
- Author each chain in its rest pose (an arm hanging straight down) and put the bend on the joint
  node's rotation; the animation then adds to that rest rotation instead of overwriting it.
- A part at the end of a chain (claw, hand, foot) continues its link's axis unless the reference
  clearly shows a bend; a compensating rotation that makes it "upright" reads as broken.
- Hinges that only pitch in reality (elbows, knees of a toy) get one rotation axis; never let a
  limb splay sideways to match a perspective effect.
- Paired left/right parts must be exact mirrors: same node placement, extrusion growing outward on
  both sides. Name sides from the subject's point of view, not the screen's.
- A leg that swings needs room: run its top up into the body, put the hip pivot inside the body,
  and give the body a dark socket under it, so the lifted leg moves within the opening instead of
  folding into the shell.
- Check the walk or motion cycle in frames, not just the rest pose: render 3-4 moments and look at
  hips, shoulders and feet.

## 6. Conflicting references

Generated references often disagree between views (a side view showing a claw edge-on that the
front photo shows face-on, a torso deeper in one view than in the other). Do not pick silently and
do not flip between them on each round of feedback. Render the candidate orientations from every
view you have, put them on one sheet, ask the user which one wins, record the choice and the
reason in the spec assumptions, and say in the hand-off which view the model now disagrees with.

## 7. Connection review

Gates measure outlines and colours; they do not see whether parts are attached the way a real
object is. Before showing the model, render close-ups and check each joint yourself:

- every band, arm or strap enters its socket (a headband into the cups, a strap into its lugs);
- every plug sits in a jack, not on a button or a blank face; find the real jack in the photo;
- cables leave a device from the side the photo shows and never pass through another part;
- soft parts (pads, cushions) are not pierced by rigid ones;
- the part that animates is the one a user would press (play, not record);
- nothing floats above the ground or sinks into it;
- feet and other supports have a contact shadow: one directional light leaves the ground under a
  planted sole lit, so add a soft occlusion blob per support that fades as it lifts;
- anything that lifts off the ground has a believable underside (dark tin, not a bright chrome
  slab that reflects the environment as a white square);
- features the photo shows proud of a face (eyes, nose, mouth grille, caps) actually stand out by
  the measured depth, checked from the side.

List what you checked in the hand-off. The user's eye is still the final review; ask them to look
at the joints specifically.

## Honesty rules

- A model built outside a pass gate is labelled as such in the factory header and in the hand-off.
- Report the camera RMS, the IoU and the threshold applied, and any lowered threshold with its reason.
- Do not claim photo accuracy for parts the photo does not show (backs, undersides, tops seen at a
  grazing angle); say they were authored by hand.
