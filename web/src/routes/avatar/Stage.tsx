import { Environment, Html, Lightformer } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { Suspense, useDeferredValue, useEffect, useRef } from "react";
import type { KeyboardEvent, MouseEvent, PointerEvent } from "react";
import { MathUtils, Vector3 } from "three";
import type { Group } from "three";
import { TeeLoader } from "../../components/brand";
import { easeOut, useReducedMotion } from "../../lib/motion";
import { isConverting } from "../../lib/viewmodel";
import { DEFAULT_PROFILE, useLook, useProfile, useStage } from "../../state";
import AvatarModel from "./AvatarModel";
import Garments, { Boundary } from "./Garment";
import Hotspots, { faces, useSpots } from "./Hotspots";
import type { Spot } from "./Hotspots";
import { bodyHeightScale, MorphDriver } from "./morphs";
import styles from "./Stage.module.css";

type View = { eye: Vector3; yaw: number };
type Point = { clientX: number; clientY: number };
type GestureEvent = UIEvent & Point & { scale: number };

const DEG = Math.PI / 180;
const TURN = 2 * Math.PI;
const DRAG_STEP = 0.4 * DEG;
const KEY_STEP = 15 * DEG;
const FOV = 30;
const TAN_HALF_FOV = Math.tan((FOV / 2) * DEG);
const HOME = new Vector3(0, 0.92, 4.2);
const NEAR = 1.2;
// m: the body's half extents, as far as the view center may pan at full zoom
const PAN_X = 0.37;
const PAN_Y = 0.92;
const FOCUS_OFFSET = new Vector3(0, 0, 1);
const UP = new Vector3(0, 1, 0);
const EASE_S = 0.55;
// 1/s: ~95% of the way to a wheel notch in 300 ms
const CHASE_RATE = 10;
const WHEEL_ZOOM = 0.0015;
const PINCH_ZOOM = 0.01;
const NOTCH = 50;
// px per deltaMode unit: pixel, line, page; firefox only reports lines if deltaMode is read first
const WHEEL_UNIT = [1, 40, 800];
const ZOOM_STEP = 1.25;
const KEY_ZOOM: Partial<Record<string, number>> = { "+": 1 / ZOOM_STEP, "=": 1 / ZOOM_STEP, "-": ZOOM_STEP, _: ZOOM_STEP };
// safari reports trackpad pinch as gesture events instead of ctrl+wheel
const GESTURES = ["gesturestart", "gesturechange", "gestureend"];
const LABEL = "your avatar. drag or use arrow keys to turn, scroll or use plus and minus to zoom, double-click to reset.";

const POOL_VERTEX = `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;

const POOL_FRAGMENT = `
varying vec2 vUv;
void main() {
  float a = 1.0 - smoothstep(0.0, 0.5, distance(vUv, vec2(0.5)));
  gl_FragColor = vec4(1.0, 1.0, 1.0, 0.4 * a * a);
}`;

// live camera position; Scene moves it toward goal or along tween every frame
const eye = HOME.clone();
let goal: Vector3 | null = null;
let tween: { from: View; to: View; t: number } | null = null;
let saved: View | null = null;

const onButton = (e: { target: EventTarget }) => (e.target as Element).closest("button") !== null;

const nearestTurn = (yaw: number) => Math.round(yaw / TURN) * TURN;

function release() {
  tween = null;
  saved = null;
}

function easeTo(to: View) {
  goal = null;
  tween = { from: { eye: eye.clone(), yaw: useStage.getState().yaw }, to, t: 0 };
}

// dolly along the ray with slopes (sx, sy) so the point it meets at z = 0 stays put; pan room shrinks to none at HOME
function zoomed(from: Vector3, factor: number, sx: number, sy: number) {
  const z = MathUtils.clamp(from.z * factor, Math.min(NEAR, from.z), HOME.z);
  const room = (HOME.z - z) / (HOME.z - NEAR);
  return new Vector3(
    MathUtils.clamp(from.x + sx * (from.z - z), -PAN_X * room, PAN_X * room),
    MathUtils.clamp(from.y + sy * (from.z - z), HOME.y - PAN_Y * room, HOME.y + PAN_Y * room),
    z,
  );
}

function zoomBy(factor: number, sx: number, sy: number, ease: boolean) {
  release();
  goal = zoomed(goal ?? eye, factor, sx, sy);
  if (!ease) eye.copy(zoomed(eye, factor, sx, sy));
}

function zoomAt(el: Element, { clientX, clientY }: Point, factor: number, ease: boolean) {
  const { left, top, width, height } = el.getBoundingClientRect();
  const sx = ((2 * (clientX - left) - width) / height) * TAN_HALF_FOV;
  const sy = ((height - 2 * (clientY - top)) / height) * TAN_HALF_FOV;
  zoomBy(factor, sx, sy, ease);
}

function resetView() {
  release();
  easeTo({ eye: HOME, yaw: nearestTurn(useStage.getState().yaw) });
}

function focusOn({ x, y, z }: Spot) {
  const { yaw } = useStage.getState();
  const turn = faces(eye, z) ? yaw : nearestTurn(yaw);
  saved ??= { eye: eye.clone(), yaw };
  easeTo({ eye: new Vector3(x, y * bodyHeightScale(), z).applyAxisAngle(UP, turn).add(FOCUS_OFFSET), yaw: turn });
}

function unfocus() {
  if (saved) easeTo(saved);
}

function stepView(delta: number, reduced: boolean) {
  if (tween) {
    tween.t = reduced ? 1 : Math.min(1, tween.t + delta / EASE_S);
    const { from, to, t } = tween;
    const k = easeOut(t);
    eye.lerpVectors(from.eye, to.eye, k);
    useStage.getState().setYaw(from.yaw + (to.yaw - from.yaw) * k);
    if (t < 1) return;
    // a finished return ends the focus
    if (to === saved) saved = null;
    tween = null;
  } else if (goal) {
    eye.lerp(goal, reduced ? 1 : 1 - Math.exp(-CHASE_RATE * delta));
    if (eye.distanceTo(goal) < 1e-4) {
      eye.copy(goal);
      goal = null;
    }
  }
}

function CameraFocus() {
  const spots = useSpots();
  const selected = useStage((s) => s.selected);
  // selection alone moves the camera, never outfit changes
  useEffect(() => {
    const spot = spots.find((s) => s.item.id === selected);
    if (spot) focusOn(spot);
    else if (!selected) unfocus();
  }, [selected]);
  return null;
}

function Scene() {
  const base = useDeferredValue(useProfile((s) => s.profile?.base ?? DEFAULT_PROFILE.base));
  const reduced = useReducedMotion();
  const turntable = useRef<Group>(null);
  useFrame(({ camera }, delta) => {
    stepView(delta, reduced);
    camera.position.copy(eye);
    turntable.current!.rotation.y = useStage.getState().yaw;
  }, -1);

  return (
    <>
      <MorphDriver />
      <CameraFocus />
      <hemisphereLight color="#ffffff" groundColor="#15468a" intensity={1.2} />
      <directionalLight position={[2.5, 3.5, 4]} intensity={2.2} />
      <directionalLight position={[-3, 2.5, -3.5]} intensity={3} />
      <Environment>
        <Lightformer position={[2.5, 2.5, 3.5]} scale={[1.5, 4]} intensity={2} target={[0, 1, 0]} />
        <Lightformer position={[-3, 2, -3]} scale={[1, 5]} intensity={3} target={[0, 1, 0]} />
      </Environment>
      <mesh rotation={[-Math.PI / 2, 0, 0]} renderOrder={-1}>
        <planeGeometry args={[1.8, 1.8]} />
        <shaderMaterial vertexShader={POOL_VERTEX} fragmentShader={POOL_FRAGMENT} transparent depthWrite={false} />
      </mesh>
      <group ref={turntable}>
        <Suspense
          fallback={
            <Html center position={[0, 0.9, 0]}>
              <TeeLoader />
            </Html>
          }
        >
          <Boundary>
            <AvatarModel base={base} />
          </Boundary>
          <Garments base={base} />
          <Boundary>
            <Suspense fallback={null}>
              <Hotspots />
            </Suspense>
          </Boundary>
        </Suspense>
      </group>
    </>
  );
}

export default function Stage() {
  const converting = useLook((s) => s.worn.some((id) => isConverting(s.assets[id] ?? s.items[id]?.asset)));
  const root = useRef<HTMLDivElement>(null);
  const drag = useRef<{ pointer: number; x: number; yaw: number | null } | null>(null);

  // native: react's wheel listener is passive and can't prevent page scroll or browser zoom
  useEffect(() => {
    const el = root.current!;
    let pinch: number | null = null;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const px = WHEEL_UNIT[e.deltaMode] * e.deltaY;
      // a pinch already zooming through gesture events must not zoom twice
      if (!px || (e.ctrlKey && pinch !== null)) return;
      // ctrl+wheel is a trackpad pinch; big steps are mouse notches, which ease
      zoomAt(el, e, Math.exp(px * (e.ctrlKey ? PINCH_ZOOM : WHEEL_ZOOM)), !e.ctrlKey && Math.abs(px) >= NOTCH);
    };
    const onGesture = (e: Event) => {
      e.preventDefault();
      const gesture = e as GestureEvent;
      if (e.type === "gesturechange" && pinch !== null) zoomAt(el, gesture, pinch / gesture.scale, false);
      pinch = e.type === "gestureend" ? null : gesture.scale;
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    for (const type of GESTURES) el.addEventListener(type, onGesture, { passive: false });
    return () => {
      el.removeEventListener("wheel", onWheel);
      for (const type of GESTURES) el.removeEventListener(type, onGesture);
    };
  }, []);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || onButton(e)) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { pointer: e.pointerId, x: e.clientX, yaw: null };
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (start?.pointer !== e.pointerId || (start.yaw === null && e.clientX === start.x)) return;
    // the first real move takes the camera over from any focus
    if (start.yaw === null) {
      release();
      start.yaw = useStage.getState().yaw;
    }
    useStage.getState().setYaw(start.yaw + (e.clientX - start.x) * DRAG_STEP);
  };

  const onLostPointerCapture = (e: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointer === e.pointerId) drag.current = null;
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const turn = e.key === "ArrowRight" ? KEY_STEP : e.key === "ArrowLeft" ? -KEY_STEP : 0;
    // cmd/ctrl +/- stays with the browser's own zoom
    const zoom = e.ctrlKey || e.metaKey || e.altKey ? undefined : KEY_ZOOM[e.key];
    if ((!turn && !zoom) || e.target !== e.currentTarget) return;
    e.preventDefault();
    if (zoom) return zoomBy(zoom, 0, 0, true);
    release();
    const { yaw, setYaw } = useStage.getState();
    setYaw(yaw + turn);
  };

  const onDoubleClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!onButton(e)) resetView();
  };

  return (
    <div
      ref={root}
      className={styles.root}
      role="application"
      tabIndex={0}
      aria-label={LABEL}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onLostPointerCapture={onLostPointerCapture}
      onKeyDown={onKeyDown}
      onDoubleClick={onDoubleClick}
    >
      <Canvas camera={{ position: HOME, rotation: [0, 0, 0], fov: FOV, near: 0.1, far: 50 }}>
        <Scene />
      </Canvas>
      {converting && (
        <div className={styles.converting}>
          <TeeLoader size={40} label="converting to 3d" />
        </div>
      )}
    </div>
  );
}
