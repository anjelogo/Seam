import { Environment, Html, Lightformer } from "@react-three/drei";
import { Canvas, useFrame } from "@react-three/fiber";
import { Suspense, useDeferredValue, useRef } from "react";
import type { KeyboardEvent, MouseEvent, PointerEvent } from "react";
import type { Group } from "three";
import { TeeLoader } from "../../components/brand";
import { isConverting } from "../../lib/viewmodel";
import { DEFAULT_PROFILE, useLook, useProfile, useStage } from "../../state";
import AvatarModel from "./AvatarModel";
import Garments, { Boundary } from "./Garment";
import Hotspots from "./Hotspots";
import { MorphDriver } from "./morphs";
import styles from "./Stage.module.css";

const DEG = Math.PI / 180;
const DRAG_STEP = 0.4 * DEG;
const KEY_STEP = 15 * DEG;
const LABEL = "your avatar. drag or use arrow keys to turn, double-click to reset.";

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

const onButton = (e: { target: EventTarget }) => (e.target as Element).closest("button") !== null;

function Scene() {
  const base = useDeferredValue(useProfile((s) => s.profile?.base ?? DEFAULT_PROFILE.base));
  const turntable = useRef<Group>(null);
  useFrame(() => {
    turntable.current!.rotation.y = useStage.getState().yaw;
  }, -1);

  return (
    <>
      <MorphDriver />
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
  const drag = useRef<{ pointer: number; x: number; yaw: number } | null>(null);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || onButton(e)) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { pointer: e.pointerId, x: e.clientX, yaw: useStage.getState().yaw };
  };

  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (start?.pointer === e.pointerId) useStage.getState().setYaw(start.yaw + (e.clientX - start.x) * DRAG_STEP);
  };

  const onLostPointerCapture = (e: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.pointer === e.pointerId) drag.current = null;
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const turn = e.key === "ArrowRight" ? KEY_STEP : e.key === "ArrowLeft" ? -KEY_STEP : 0;
    if (!turn || e.target !== e.currentTarget) return;
    e.preventDefault();
    const { yaw, setYaw } = useStage.getState();
    setYaw(yaw + turn);
  };

  const onDoubleClick = (e: MouseEvent<HTMLDivElement>) => {
    if (!onButton(e)) useStage.getState().setYaw(0);
  };

  return (
    <div
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
      <Canvas camera={{ position: [0, 0.92, 4.2], rotation: [0, 0, 0], fov: 30, near: 0.1, far: 50 }}>
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
