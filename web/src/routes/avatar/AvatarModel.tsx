import { useGLTF } from "@react-three/drei";
import type { BodyBase } from "@shared/types";
import { useMemo } from "react";
import { Mesh, MeshPhysicalMaterial } from "three";
import { useBodyMorphs } from "./morphs";

const avatarUrl = (base: BodyBase) => `/assets/avatar_${base}.glb`;

// depthWrite off so garments read through the shell
const GLASS = new MeshPhysicalMaterial({
  color: "#eaf2ff",
  transparent: true,
  opacity: 0.4,
  roughness: 0.15,
  clearcoat: 0.6,
  clearcoatRoughness: 0.1,
  depthWrite: false,
});

export default function AvatarModel({ base }: { base: BodyBase }) {
  const { scene } = useGLTF(avatarUrl(base), false);
  const body = useMemo(() => {
    const clone = scene.clone();
    clone.traverse((object) => {
      if (object instanceof Mesh) object.material = GLASS;
    });
    return clone;
  }, [scene]);
  useBodyMorphs(body);
  return <primitive object={body} />;
}

useGLTF.preload(avatarUrl("masc"), false);
useGLTF.preload(avatarUrl("fem"), false);
