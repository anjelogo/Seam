import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { Vector2, Vector3 } from "three";
import { useReducedMotion } from "../../lib/motion";
import styles from "./RibbonBackground.module.css";
import { fragmentShader, vertexShader } from "./ribbonShader";
import { REST, sampleSurge } from "./surge";

const GL = { antialias: false, alpha: true, powerPreference: "low-power" } as const;
const DPR: [number, number] = [1, 1.5];
const CANVAS_STYLE = { pointerEvents: "none" } as const;
const RESIZE = { scroll: false } as const;
const LOOP_SECONDS = 520;
const DEFAULT_STOPS = ["#081631", "#15468a", "#0a2350"];

function setHex(target: Vector3, value: string) {
  let hex = value.trim().replace(/^#/, "");
  if (hex.length === 3) hex = hex.replace(/./g, "$&$&");
  if (!/^[0-9a-f]{6}$/i.test(hex)) return target;
  const n = Number.parseInt(hex, 16);
  return target.set(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
}

function readStops(stops: Vector3[]) {
  const style = getComputedStyle(document.documentElement);
  stops.forEach((stop, i) => setHex(stop, style.getPropertyValue(`--grad-${i}`)));
  return stops;
}

function Ribbons({ reduced }: { reduced: boolean }) {
  const invalidate = useThree((state) => state.invalidate);
  const uniforms = useMemo(
    () => ({
      time: { value: 0 },
      speed: { value: REST.speed },
      glowPulse: { value: REST.glow },
      surge: { value: REST.offset },
      stops: { value: readStops(DEFAULT_STOPS.map((hex) => setHex(new Vector3(), hex))) },
      resolution: { value: new Vector2(1, 1) },
      dpr: { value: 1 },
    }),
    [],
  );

  useEffect(() => {
    const observer = new MutationObserver(() => {
      readStops(uniforms.stops.value);
      invalidate();
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, [uniforms, invalidate]);

  useFrame(({ size, viewport }) => {
    const now = performance.now();
    const surge = reduced ? REST : sampleSurge(now);
    uniforms.resolution.value.set(size.width, size.height);
    uniforms.dpr.value = viewport.dpr;
    uniforms.time.value = reduced ? 0 : (now / 1000) % LOOP_SECONDS;
    uniforms.surge.value = surge.offset;
    uniforms.glowPulse.value = surge.glow;
    uniforms.speed.value = surge.speed;
  });

  return (
    <mesh frustumCulled={false}>
      <planeGeometry args={[2, 2]} />
      <shaderMaterial
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={uniforms}
        toneMapped={false}
        depthTest={false}
        depthWrite={false}
      />
    </mesh>
  );
}

export function RibbonBackground() {
  const reduced = useReducedMotion();
  return (
    <div className={styles.root} aria-hidden="true">
      <Canvas
        style={CANVAS_STYLE}
        resize={RESIZE}
        gl={GL}
        dpr={DPR}
        flat
        linear
        frameloop={reduced ? "demand" : "always"}
      >
        <Ribbons reduced={reduced} />
      </Canvas>
    </div>
  );
}
