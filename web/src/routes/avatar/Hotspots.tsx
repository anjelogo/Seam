import { Html } from "@react-three/drei";
import { useFrame, useThree } from "@react-three/fiber";
import type { BodyBase, Slot, Vec3 } from "@shared/types";
import clsx from "clsx";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import type { Camera, Group } from "three";
import type { UiItem } from "../../lib/viewmodel";
import { DEFAULT_PROFILE, useProfile, useStage, useWornItems } from "../../state";
import styles from "./Hotspots.module.css";
import { bodyHeightScale } from "./morphs";

type Anchor = { center: Vec3; size: Vec3 };
type Anchors = Record<BodyBase, Partial<Record<Slot, Anchor>>>;
type Side = "left" | "right";
type Spot = { item: UiItem; side: Side; x: number; y: number; z: number; reach: number; dy: number };

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

function layout(items: UiItem[], anchors: Partial<Record<Slot, Anchor>>, ppm: number): Spot[] {
  const last: Record<Side, number> = { left: -Infinity, right: -Infinity };
  return items
    .flatMap((item) => {
      const anchor = anchors[item.slot];
      if (!anchor) return [];
      const [x, y, z] = anchor.center;
      const [width, , depth] = anchor.size;
      const side: Side = RIGHT.includes(item.slot) ? "right" : "left";
      return [{ item, side, x, y, z: z + depth / 2, reach: Math.round((width / 2) * ppm) + LABEL_GAP }];
    })
    .sort((a, b) => b.y - a.y)
    .map((spot) => {
      const at = -spot.y * ppm;
      const placed = Math.max(at, last[spot.side] + LABEL_STACK);
      last[spot.side] = placed;
      return { ...spot, dy: placed - at };
    });
}

// n · (camera - anchor) > 0 with n = +Z turned by yaw; turning keeps n · anchor = local z
function faces(camera: Camera, z: number) {
  const yaw = useStage.getState().yaw;
  return Math.sin(yaw) * camera.position.x + Math.cos(yaw) * camera.position.z > z;
}

function Node({ spot, selected }: { spot: Spot; selected: boolean }) {
  const { item, side, x, y, z, reach, dy } = spot;
  const camera = useThree((s) => s.camera);
  const group = useRef<Group>(null);
  const [away, setAway] = useState(() => !faces(camera, z));

  // priority -1: after MorphDriver eases the body, before Html projects the anchor
  useFrame(() => {
    group.current!.position.y = y * bodyHeightScale();
    const facing = faces(camera, z);
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
          <span
            className={styles.line}
            style={{
              width: Math.hypot(reach, dy) - DOT_RADIUS,
              transform: `rotate(${Math.atan2(dy, side === "right" ? reach : -reach)}rad) translateX(${DOT_RADIUS}px)`,
            }}
          />
          <span
            className={clsx("glass", "t-label", styles.label)}
            style={side === "right" ? { left: reach, top: dy } : { right: reach, top: dy }}
          >
            {item.category}
          </span>
        </button>
      </Html>
    </group>
  );
}

export default function Hotspots() {
  const base = useDeferredValue(useProfile((s) => s.profile?.base ?? DEFAULT_PROFILE.base));
  const anchors = useAnchors()?.[base];
  const worn = useWornItems();
  const selected = useStage((s) => s.selected);
  const ppm = useThree((s) => s.viewport.factor);
  const spots = useMemo(() => (anchors ? layout(worn, anchors, ppm) : []), [anchors, worn, ppm]);

  return (
    <>
      {spots.map((spot) => (
        <Node key={spot.item.id} spot={spot} selected={spot.item.id === selected} />
      ))}
    </>
  );
}
