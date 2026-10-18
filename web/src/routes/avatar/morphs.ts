import { useFrame } from "@react-three/fiber";
import { BODY_SLIDERS } from "@shared/types";
import { useLayoutEffect, useMemo, useRef } from "react";
import { Mesh } from "three";
import type { Object3D } from "three";
import { useReducedMotion } from "../../lib/motion";
import { useBodyProfile, useProfile } from "../../state";

export type BodySlider = (typeof BODY_SLIDERS)[number];
type FitMorphs = { ease: number; crop: number };

// 1/s: ~95% of the way to the target in 300 ms
const EASE_RATE = 10;
const FIT_MORPHS: (keyof FitMorphs)[] = ["ease", "crop"];

// live eased influences by morph name; MorphDriver rewrites them first every frame
export const bodyMorphs = Object.fromEntries(BODY_SLIDERS.map((name) => [name, 0.5])) as Record<BodySlider, number>;

// body height vs the default mesh (gen3d scales y by 1 + 0.18 * (height - 0.5))
export const bodyHeightScale = () => 1 + 0.18 * (bodyMorphs.height - 0.5);

const easeFactor = (delta: number, snap: boolean) =>
  snap || useProfile.getState().dragging ? 1 : 1 - Math.exp(-EASE_RATE * delta);

function useMorphMeshes(root: Object3D | null) {
  return useMemo(() => {
    const found: Mesh[] = [];
    root?.traverse((object) => {
      if (object instanceof Mesh && object.morphTargetDictionary) found.push(object);
    });
    return found;
  }, [root]);
}

export function MorphDriver() {
  const body = useBodyProfile();
  const reduced = useReducedMotion();
  const settled = useRef(false);
  useFrame((_, delta) => {
    const k = easeFactor(delta, !settled.current || reduced);
    for (const name of BODY_SLIDERS) bodyMorphs[name] += (body[name] - bodyMorphs[name]) * k;
    settled.current = true;
  }, -1);
  return null;
}

export function useBodyMorphs(root: Object3D | null) {
  const meshes = useMorphMeshes(root);
  useFrame(() => {
    for (const mesh of meshes) {
      for (const name of BODY_SLIDERS) {
        const i = mesh.morphTargetDictionary![name];
        if (i !== undefined) mesh.morphTargetInfluences![i] = bodyMorphs[name];
      }
    }
  });
}

export function useFitMorphs(root: Object3D, fit: FitMorphs) {
  const meshes = useMorphMeshes(root);
  const reduced = useReducedMotion();
  const target = useRef(fit);
  const eased = useRef<FitMorphs | null>(null);
  useLayoutEffect(() => {
    target.current = fit;
  });
  useFrame((_, delta) => {
    const k = easeFactor(delta, !eased.current || reduced);
    const now = (eased.current ??= { ease: 0, crop: 0 });
    for (const name of FIT_MORPHS) {
      now[name] += (target.current[name] - now[name]) * k;
      for (const mesh of meshes) {
        const i = mesh.morphTargetDictionary![name];
        if (i !== undefined) mesh.morphTargetInfluences![i] = now[name];
      }
    }
  });
}
