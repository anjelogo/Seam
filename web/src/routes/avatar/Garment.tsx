import { useGLTF } from "@react-three/drei";
import { SLOT_LAYER_ORDER } from "@shared/types";
import type { BodyBase, Item, Slot } from "@shared/types";
import { Component, Suspense, useDeferredValue, useMemo } from "react";
import type { ReactNode } from "react";
import { Color, Mesh } from "three";
import type { MeshStandardMaterial } from "three";
import { toUiItem } from "../../lib/viewmodel";
import type { UiItem } from "../../lib/viewmodel";
import { useLook } from "../../state";
import { useBodyMorphs } from "./morphs";

const TEMPLATE_FOR_SLOT: Partial<Record<Slot, string>> = {
  top: "tee_v1",
  outer: "jacket_v1",
  bottom: "pants_v1",
  onepiece: "dress_v1",
};
const FABRIC = "#cfc8bc";
const HEX = /^#?(?:[0-9a-f]{3}){1,2}$/i;
// horizontal scale per layer index so outer layers never z-fight inner ones
const NUDGE = 0.006;

type Piece = { ui: UiItem; layer: number; template?: string; tint: string };

export class Boundary extends Component<{ fallback?: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? (this.props.fallback ?? null) : this.props.children;
  }
}

function tintOf(item: Item) {
  const color = item.tags?.colors[0];
  const hex = color?.hex.trim() ?? "";
  if (HEX.test(hex)) return hex.startsWith("#") ? hex : `#${hex}`;
  const name = color?.name.toLowerCase().replace(/[\s_-]/g, "") ?? "";
  return Object.hasOwn(Color.NAMES, name) ? name : FABRIC;
}

function Template({ url, tint }: { url: string; tint: string }) {
  const { scene } = useGLTF(url, false);
  const garment = useMemo(() => {
    const clone = scene.clone();
    clone.traverse((object) => {
      if (!(object instanceof Mesh)) return;
      const material = (object.material as MeshStandardMaterial).clone();
      material.color.set(tint);
      object.material = material;
    });
    return clone;
  }, [scene, tint]);
  useBodyMorphs(garment);
  return <primitive object={garment} />;
}

function Model({ url, ui }: { url: string; ui: UiItem }) {
  const { scene } = useGLTF(url, false);
  const garment = useMemo(() => scene.clone(), [scene]);
  useBodyMorphs(ui.followsBodyMorphs ? garment : null);
  const fit = !ui.followsBodyMorphs && ui.fit;
  if (!fit) return <primitive object={garment} />;
  return (
    <group position={fit.position} rotation={fit.rotation} scale={fit.scale}>
      <primitive object={garment} />
    </group>
  );
}

export default function Garments({ base }: { base: BodyBase }) {
  const worn = useLook((s) => s.worn);
  const items = useLook((s) => s.items);
  const assets = useLook((s) => s.assets);
  const current = useMemo(
    () =>
      worn
        .flatMap((id): Piece[] => {
          const item = items[id];
          const asset = assets[id] ?? item?.asset;
          const ui = item ? toUiItem(item, base, asset) : null;
          const templateId = ui && (asset?.template_id ?? TEMPLATE_FOR_SLOT[ui.slot]);
          if (!ui || (!ui.modelUrl && !templateId)) return [];
          const template = templateId ? `/assets/templates/${templateId}_${base}.glb` : undefined;
          return [{ ui, layer: SLOT_LAYER_ORDER.indexOf(ui.slot), template, tint: tintOf(item) }];
        })
        .sort((a, b) => a.layer - b.layer),
    [worn, items, assets, base],
  );
  // keeps current meshes on screen until replacement GLBs have loaded
  const pieces = useDeferredValue(current);

  return (
    <>
      {pieces.map(({ ui, layer, template, tint }) => {
        const fallback = template ? <Template url={template} tint={tint} /> : null;
        const nudge = 1 + NUDGE * layer;
        return (
          <group key={ui.id} scale={[nudge, 1, nudge]}>
            <Suspense fallback={null}>
              <Boundary key={template}>
                <Boundary key={ui.modelUrl} fallback={fallback}>
                  {ui.modelUrl ? <Model url={ui.modelUrl} ui={ui} /> : fallback}
                </Boundary>
              </Boundary>
            </Suspense>
          </group>
        );
      })}
    </>
  );
}
