import * as THREE from 'three';
// Both aliases are set by img2plus/render.py at bundle time.
import * as M from '@img2plus/factory';
import cam from '@img2plus/camera';

// Review harness for a generated factory.
//   ?view=ref            solved photo camera      &strip=1  flat grey materials
//   ?az=&el=[&fov&dist&tx&ty&tz]  orbit view     &mode=    look-dev light rig (default reference)
// Sets window.__READY__ once every texture has decoded and a few frames are drawn.
const q = new URLSearchParams(location.search);
const strip = q.get('strip') === '1';
const mode = q.get('mode') ?? 'reference';
const exports = Object.entries(M as Record<string, unknown>);
const find = <T,>(re: RegExp): T | undefined => exports.find(([k, v]) => re.test(k) && typeof v === 'function')?.[1] as T | undefined;

const createModel = find<(o?: object) => THREE.Group>(/^create\w+Model$/);
if (!createModel) throw new Error('factory exports no create...Model function');

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(window.innerWidth, window.innerHeight);
const configure = find<(r: THREE.WebGLRenderer) => void>(/^configure\w+Renderer$/);
if (configure) configure(renderer);
else { renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace; }
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf6f6f5);
const env = find<(r: THREE.WebGLRenderer) => THREE.Texture>(/^create\w+Environment$/);
if (env) scene.environment = env(renderer);
const rig = find<(m: string) => THREE.Group>(/^create\w+LookDevLights$/);
const lights = rig ? rig(mode) : (() => {
  const g = new THREE.Group();
  g.add(new THREE.HemisphereLight(0xffffff, 0xd8d8d8, 1.2));
  const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(3, 5, 4); g.add(key);
  return g;
})();
lights.traverse((o) => {
  const l = o as THREE.DirectionalLight;
  if (l.isDirectionalLight && l.intensity > 1) {
    l.castShadow = true; l.shadow.mapSize.set(2048, 2048); l.shadow.radius = 6; l.shadow.bias = -0.0004;
    const c = l.shadow.camera; c.left = -2.5; c.right = 2.5; c.top = 2.5; c.bottom = -2.5; c.near = 0.1; c.far = 30;
  }
});
scene.add(lights);

const model = createModel({ castShadow: true, receiveShadow: true });
scene.add(model);
if (strip) {
  const grey = new THREE.MeshStandardMaterial({ color: 0x9a9a9a, roughness: 0.8 });
  model.traverse((o) => { if ((o as THREE.Mesh).isMesh) (o as THREE.Mesh).material = grey; });
}
const ground = new THREE.Mesh(new THREE.PlaneGeometry(20, 20), new THREE.ShadowMaterial({ opacity: 0.08 }));
ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);

const aspect = window.innerWidth / window.innerHeight;
let camera: THREE.PerspectiveCamera;
if (q.get('view') === 'ref') {
  camera = new THREE.PerspectiveCamera(cam.fovVerticalDeg, aspect, 0.01, 200);
  camera.position.fromArray(cam.position); camera.up.fromArray(cam.up);
  camera.lookAt(new THREE.Vector3().fromArray(cam.target));
} else {
  camera = new THREE.PerspectiveCamera(Number(q.get('fov') ?? 22), aspect, 0.01, 200);
  const box = new THREE.Box3().setFromObject(model); const ctr = box.getCenter(new THREE.Vector3());
  if (q.get('tx')) ctr.set(Number(q.get('tx')), Number(q.get('ty')), Number(q.get('tz')));
  const r = box.getSize(new THREE.Vector3()).length() * 0.5;
  const az = THREE.MathUtils.degToRad(Number(q.get('az') ?? 30)), el = THREE.MathUtils.degToRad(Number(q.get('el') ?? 15));
  const dist = q.get('dist') ? Number(q.get('dist')) : (r / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2))) * 1.02;
  camera.position.set(ctr.x + dist * Math.sin(az) * Math.cos(el), ctr.y + dist * Math.sin(el), ctr.z + dist * Math.cos(az) * Math.cos(el));
  camera.lookAt(ctr);
}
camera.updateProjectionMatrix();

const textures: THREE.Texture[] = [];
model.traverse((o) => {
  const mats = ([] as THREE.Material[]).concat(((o as THREE.Mesh).material as THREE.Material | THREE.Material[] | undefined) ?? []);
  for (const m of mats) for (const k of ['map', 'roughnessMap', 'metalnessMap', 'normalMap', 'aoMap', 'bumpMap'] as const) {
    const t = (m as unknown as Record<string, THREE.Texture | null>)[k]; if (t) textures.push(t);
  }
});
let frames = 0;
const tick = () => {
  renderer.render(scene, camera);
  const ready = textures.every((t) => t.image && (t.image as HTMLImageElement).complete !== false);
  if (ready && ++frames > 3) { (window as unknown as Record<string, unknown>).__READY__ = true; return; }
  requestAnimationFrame(tick);
};
tick();
