import {
  DoubleSide,
  ExtrudeGeometry,
  Group,
  Mesh,
  MeshBasicMaterial,
  NotEqualStencilFunc,
  PerspectiveCamera,
  ReplaceStencilOp,
  Scene,
  Shape,
  ShapeGeometry,
  WebGLRenderer,
} from "three";
import { Line2 } from "three/examples/jsm/lines/Line2.js";
import { LineGeometry } from "three/examples/jsm/lines/LineGeometry.js";
import { LineMaterial } from "three/examples/jsm/lines/LineMaterial.js";
import { easeInOut } from "../../lib/motion";
import { TEE_PATH } from "./tee";

type Loader = {
  canvas: HTMLCanvasElement;
  ctx: CanvasRenderingContext2D;
  size: number;
  onFail: () => void;
};

type Stage = ReturnType<typeof createStage>;

const LOOP_MS = 2800;
const FRAME_UNITS = 72;
const FOV = 30;
const STACK_DEPTH = 22;
const MAX_SLICES = 8;
const FRONT_WIDTH = 4;
const BACK_WIDTH = 2;
const NEAR_OPACITY = 0.65;
const FAR_OPACITY = 0.22;
const DISPOSE_DELAY_MS = 1000;
const DEG = Math.PI / 180;

const KEYS = [
  { at: 0, spread: 0, turnY: 0, turnX: 0 },
  { at: 0.12, spread: 0, turnY: 0, turnX: 0 },
  { at: 0.34, spread: 1, turnY: 0, turnX: 0 },
  { at: 0.6, spread: 1, turnY: -42, turnX: 14 },
  { at: 0.8, spread: 1, turnY: 32, turnX: 8 },
  { at: 1, spread: 0, turnY: 0, turnX: 0 },
];

const loaders = new Set<Loader>();
let stage: Stage | null = null;
let unavailable = false;
let raf = 0;
let epoch = 0;
let disposeTimer = 0;

const sliceCount = (size: number) => (size > 72 ? 8 : size > 40 ? 6 : size > 24 ? 4 : 3);

function teeShape() {
  const shape = new Shape();
  for (const [, command, args] of TEE_PATH.matchAll(/([MLCZ])([^MLCZ]*)/g)) {
    // viewBox to world units: centered, y up
    const p = (args.match(/-?[\d.]+/g) ?? []).map((n, i) => (i % 2 ? 32 - Number(n) : Number(n) - 32));
    if (command === "M") shape.moveTo(p[0], p[1]);
    else if (command === "L") shape.lineTo(p[0], p[1]);
    else if (command === "C") shape.bezierCurveTo(p[0], p[1], p[2], p[3], p[4], p[5]);
    else shape.closePath();
  }
  return shape;
}

function createStage() {
  const renderer = new WebGLRenderer({
    alpha: true,
    antialias: true,
    stencil: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(1);
  renderer.setClearColor(0x000000, 0);
  renderer.setScissorTest(true);
  renderer.domElement.addEventListener("webglcontextlost", onContextLost);

  const camera = new PerspectiveCamera(FOV, 1, 10, 400);
  camera.position.z = FRAME_UNITS / 2 / Math.tan((FOV / 2) * DEG);

  const shape = teeShape();
  const outline = new LineGeometry().setPositions(shape.getPoints().flatMap((p) => [p.x, p.y, 0]));
  const fill = new ShapeGeometry(shape);
  const prism = new ExtrudeGeometry(shape, { depth: 1, bevelEnabled: false });

  const surface = (opacity: number) =>
    new MeshBasicMaterial({
      transparent: true,
      opacity,
      side: DoubleSide,
      depthWrite: false,
      toneMapped: false,
    });
  // stencil keeps overlapping round caps from blending twice
  const stroke = (opacity: number, stencilRef: number) =>
    new LineMaterial({
      transparent: true,
      opacity,
      depthWrite: false,
      toneMapped: false,
      stencilWrite: true,
      stencilRef,
      stencilFunc: NotEqualStencilFunc,
      stencilZPass: ReplaceStencilOp,
    });

  const walls = new Mesh(prism, [new MeshBasicMaterial({ visible: false }), surface(0.06)]);
  const backFill = new Mesh(fill, surface(0.12));
  const backLines = Array.from(
    { length: MAX_SLICES - 1 },
    (_, i) => new Line2(outline, stroke(NEAR_OPACITY, i + 2)),
  );
  const frontFill = new Mesh(fill, surface(0.18));
  const frontLine = new Line2(outline, stroke(1, 1));

  const scene = new Scene();
  const pivot = new Group();
  const stack = new Group();
  pivot.add(stack);
  scene.add(pivot);
  [walls, backFill, ...backLines.toReversed(), frontFill, frontLine].forEach((object, order) => {
    object.renderOrder = order;
    stack.add(object);
  });

  let depth = 0;

  return {
    fit(px: number) {
      if (renderer.domElement.width !== px) renderer.setSize(px, px, false);
    },

    pose(t: number) {
      let i = 1;
      while (i < KEYS.length - 1 && KEYS[i].at < t) i++;
      const from = KEYS[i - 1];
      const to = KEYS[i];
      const e = easeInOut((t - from.at) / (to.at - from.at));
      const mix = (a: number, b: number) => a + (b - a) * e;
      depth = mix(from.spread, to.spread) * STACK_DEPTH;
      pivot.position.z = -depth / 2;
      stack.position.z = depth / 2;
      // css rotateY() rotateX(); css y points down
      pivot.rotation.set(-mix(from.turnX, to.turnX) * DEG, mix(from.turnY, to.turnY) * DEG, 0, "YXZ");
      walls.visible = depth > 0.01;
      walls.position.z = -depth;
      walls.scale.z = Math.max(depth, 0.01);
      backFill.visible = depth > 0.01;
      backFill.position.z = -depth;
    },

    draw({ canvas, ctx, size }: Loader) {
      const px = canvas.width;
      const slices = sliceCount(size);
      const unit = px / FRAME_UNITS;
      frontLine.material.linewidth = FRONT_WIDTH * unit;
      backLines.forEach((line, i) => {
        const k = i + 1;
        line.visible = k < slices;
        if (!line.visible) return;
        line.position.z = (-depth * k) / (slices - 1);
        line.material.opacity = NEAR_OPACITY + ((FAR_OPACITY - NEAR_OPACITY) * (k - 1)) / (slices - 2);
        line.material.linewidth = BACK_WIDTH * unit;
      });
      renderer.setViewport(0, 0, px, px);
      renderer.setScissor(0, 0, px, px);
      renderer.render(scene, camera);
      ctx.clearRect(0, 0, px, px);
      // gl viewport origin is bottom-left
      ctx.drawImage(renderer.domElement, 0, renderer.domElement.height - px, px, px, 0, 0, px, px);
    },

    dispose() {
      renderer.domElement.removeEventListener("webglcontextlost", onContextLost);
      [outline, fill, prism].forEach((geometry) => geometry.dispose());
      [
        ...walls.material,
        backFill.material,
        frontFill.material,
        frontLine.material,
        ...backLines.map((line) => line.material),
      ].forEach((material) => material.dispose());
      renderer.dispose();
      if (!renderer.getContext().isContextLost()) renderer.forceContextLoss();
    },
  };
}

function ensureStage() {
  if (!stage && !unavailable) {
    try {
      stage = createStage();
    } catch {
      unavailable = true;
    }
  }
  return stage;
}

function stop() {
  cancelAnimationFrame(raf);
  raf = 0;
}

function teardown() {
  window.clearTimeout(disposeTimer);
  stage?.dispose();
  stage = null;
}

function onContextLost() {
  const lost = [...loaders];
  loaders.clear();
  stop();
  teardown();
  lost.forEach((loader) => loader.onFail());
}

function tick() {
  raf = requestAnimationFrame(tick);
  if (!stage) return;
  const now = performance.now();
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let max = 1;
  for (const loader of loaders) {
    const px = Math.max(1, Math.round(loader.size * dpr));
    if (loader.canvas.width !== px) loader.canvas.width = loader.canvas.height = px;
    max = Math.max(max, px);
  }
  stage.fit(max);
  stage.pose(((now - epoch) % LOOP_MS) / LOOP_MS);
  for (const loader of loaders) stage.draw(loader);
}

export const webglUnavailable = () => unavailable;

export function attachLoader(canvas: HTMLCanvasElement, size: number, onFail: () => void) {
  const ctx = canvas.getContext("2d");
  if (!ctx || !ensureStage()) {
    onFail();
    return () => {};
  }
  const loader: Loader = { canvas, ctx, size, onFail };
  loaders.add(loader);
  window.clearTimeout(disposeTimer);
  if (!raf) {
    epoch = performance.now();
    raf = requestAnimationFrame(tick);
  }
  return () => {
    if (!loaders.delete(loader) || loaders.size > 0) return;
    stop();
    disposeTimer = window.setTimeout(teardown, DISPOSE_DELAY_MS);
  };
}
