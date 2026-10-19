import { Html } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import type { BodyBase, Slot, Vec3 } from "@shared/types";
import clsx from "clsx";
import { createRef, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import type { Group, Vector3 } from "three";
import type { UiItem } from "../../lib/viewmodel";
import { DEFAULT_PROFILE, useProfile, useStage, useWornItems } from "../../state";
import styles from "./Hotspots.module.css";
import { bodyHeightScale } from "./morphs";

type Anchor = { center: Vec3; size: Vec3 };
type Anchors = Record<BodyBase, Partial<Record<Slot, Anchor>>>;
type Side = "left" | "right";
export type Spot = { item: UiItem; side: Side; x: number; y: number; z: number; half: number };
type Refs = { line: RefObject<HTMLSpanElement>; label: RefObject<HTMLSpanElement> };

const RIGHT: Slot[] = ["top", "outer", "onepiece"];
const DOT_RADIUS = 8;
// px: garment edge to its label, and min spacing between labels on one side
const LABEL_GAP = 36;
const LABEL_STACK = 40;

let anchorsRequest: Promise<Anchors> | null = null;

function loadAnchors() {
  anchorsRequest ??= fetch("/assets/anchors.json")
    .then((res) => {
      if (!res.ok) throw new Error(`anchors.json ${res.status}`);
      return res.json() as Promise<Anchors>;
    })
    .catch((error: unknown) => {
      anchorsRequest = null;
      throw error;
    });
  return anchorsRequest;
}

function useAnchors() {
  const [anchors, setAnchors] = useState<Anchors | null>(null);
  useEffect(() => {
    let live = true;
    loadAnchors()
      .then((next) => {
        if (live) setAnchors(next);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return anchors;
}

function toSpots(items: UiItem[], anchors: Partial<Record<Slot, Anchor>>): Spot[] {
  return items
    .flatMap((item) => {
      const anchor = anchors[item.slot];
      if (!anchor) return [];
      const [x, y, z] = anchor.center;
      const [width, , depth] = anchor.size;
      const side: Side = RIGHT.includes(item.slot) ? "right" : "left";
      return [{ item, side, x, y, z: z + depth / 2, half: width / 2 }];
    })
    .sort((a, b) => b.y - a.y);
}

export function useSpots() {
  const base = useDeferredValue(useProfile((s) => s.profile?.base ?? DEFAULT_PROFILE.base));
  const anchors = useAnchors()?.[base];
  const worn = useWornItems();
  return useMemo(() => (anchors ? toSpots(worn, anchors) : []), [anchors, worn]);
}

// n · (eye - anchor) > 0 with n = +Z turned by yaw; turning keeps n · anchor = local z
export function faces(eye: Vector3, z: number) {
  const yaw = useStage.getState().yaw;
  return Math.sin(yaw) * eye.x + Math.cos(yaw) * eye.z > z;
}

function draw({ line, label }: Refs, side: Side, reach: number, dy: number) {
  if (!line.current || !label.current) return;
  line.current.style.width = `${Math.hypot(reach, dy) - DOT_RADIUS}px`;
  line.current.style.transform = `rotate(${Math.atan2(dy, side === "right" ? reach : -reach)}rad) translateX(${DOT_RADIUS}px)`;
  label.current.style[side === "right" ? "left" : "right"] = `${reach}px`;
  label.current.style.top = `${dy}px`;
}

// focal: px per meter at 1 m from the camera
function layout(spots: Spot[], refs: Refs[], eye: Vector3, focal: number) {
  const { yaw } = useStage.getState();
  const lift = bodyHeightScale();
  const last: Record<Side, number> = { left: -Infinity, right: -Infinity };
  spots
    .map((spot, i) => {
      const ppm = focal / (eye.z + spot.x * Math.sin(yaw) - spot.z * Math.cos(yaw));
      return { i, top: (eye.y - spot.y * lift) * ppm, reach: Math.round(spot.half * ppm) + LABEL_GAP };
    })
    .sort((a, b) => a.top - b.top)
    .forEach(({ i, top, reach }) => {
      const { side } = spots[i];
      const placed = Math.max(top, last[side] + LABEL_STACK);
      last[side] = placed;
      draw(refs[i], side, reach, placed - top);
    });
}

function Node({ spot, refs, selected }: { spot: Spot; refs: Refs; selected: boolean }) {
  const { item, x, y, z } = spot;
  const camera = useThree((s) => s.camera);
  const group = useRef<Group>(null);
  const [away, setAway] = useState(() => !faces(camera.position, z));

  // priority -1: after MorphDriver eases the body, before Html projects the anchor
  useFrame(() => {
    group.current!.position.y = y * bodyHeightScale();
    const facing = faces(camera.position, z);
    if (facing === away) setAway(!facing);
  }, -1);

  return (
    <group ref={group} position={[x, y * bodyHeightScale(), z]}>
      <Html>
        <button
          type="button"
          className={clsx(styles.node, selected && styles.selected, away && styles.away)}
          aria-label={`${item.category}: ${item.name}`}
          aria-pressed={selected}
          onClick={() => useStage.getState().select(selected ? null : item.id)}
        >
          <span className={styles.dot} />
          <span ref={refs.line} className={styles.line} />
          <span ref={refs.label} className={clsx("glass", "t-label", styles.label)}>
            {item.category}
          </span>
        </button>
      </Html>
    </group>
  );
}

export default function Hotspots() {
  const spots = useSpots();
  const selected = useStage((s) => s.selected);
  const refs = useMemo(() => spots.map((): Refs => ({ line: createRef(), label: createRef() })), [spots]);

  // default priority: after the camera and body move at -1
  useFrame(({ camera, size }) => {
    layout(spots, refs, camera.position, (camera.projectionMatrix.elements[5] * size.height) / 2);
  });

  return (
    <>
      {spots.map((spot, i) => (
        <Node key={spot.item.id} spot={spot} refs={refs[i]} selected={spot.item.id === selected} />
      ))}
    </>
  );
}
