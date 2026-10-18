import { useGLTF } from "@react-three/drei";
import { SLOT_LAYER_ORDER } from "@shared/types";
import type { Asset3D, BodyBase, Item, Slot } from "@shared/types";
import { Component, Suspense, useDeferredValue, useMemo } from "react";
import type { ReactNode } from "react";
import { Color, Mesh } from "three";
import type { MeshStandardMaterial } from "three";
import { garmentFit } from "../../lib/fit";
import type { GarmentFit } from "../../lib/fit";
import { toUiItem } from "../../lib/viewmodel";
import type { UiItem } from "../../lib/viewmodel";
import { DEFAULT_PROFILE, useLook, useProfile } from "../../state";
import { useBodyMorphs, useFitMorphs } from "./morphs";

const TEMPLATE_FOR_SLOT: Partial<Record<Slot, string>> = {
  top: "tee_v1",
  outer: "jacket_v1",
  bottom: "pants_v1",
  onepiece: "dress_v1",
  shoes: "shoe_v1",
};
const FABRIC = "#cfc8bc";
const HEX = /^#?(?:[0-9a-f]{3}){1,2}$/i;
// horizontal scale per layer index so outer layers never z-fight inner ones
const NUDGE = 0.006;

type Source = { url: string; kind: "model" | "template" };
type Piece = { item: Item; ui: UiItem; layer: number; sources: Source[]; tint: string };

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

function openModelUrl(asset: Asset3D | null | undefined, base: BodyBase) {
  if (asset?.status !== "ready" || !asset.glb_url) return undefined;
  return asset.glb_url.replace(/\.glb$/, base === "fem" && asset.follows_body_morphs ? "_open_fem.glb" : "_open.glb");
}

const model = (url: string | undefined): Source[] => (url ? [{ url, kind: "model" }] : []);

const template = (id: string | undefined, variant: string, base: BodyBase): Source[] =>
  id ? [{ url: `/assets/templates/${id}${variant}_${base}.glb`, kind: "template" }] : [];

function Template({ url, tint, fit }: { url: string; tint: string; fit: GarmentFit }) {
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
  useFitMorphs(garment, fit);
  return <primitive object={garment} />;
}

function Model({ url, ui, fit }: { url: string; ui: UiItem; fit: GarmentFit }) {
  const { scene } = useGLTF(url, false);
  const garment = useMemo(() => scene.clone(), [scene]);
  useBodyMorphs(ui.followsBodyMorphs ? garment : null);
  useFitMorphs(garment, fit);
  const transform = !ui.followsBodyMorphs && ui.fit;
  if (!transform) return <primitive object={garment} />;
  return (
    <group position={transform.position} rotation={transform.rotation} scale={transform.scale}>
      <primitive object={garment} />
    </group>
  );
}

export default function Garments({ base }: { base: BodyBase }) {
  const worn = useLook((s) => s.worn);
  const items = useLook((s) => s.items);
  const assets = useLook((s) => s.assets);
  const profile = useProfile((s) => s.profile) ?? DEFAULT_PROFILE;
  const current = useMemo(() => {
    const slots = new Set(worn.map((id) => items[id]?.tags?.slot));
    // a jacket over a top or dress tries its open variant first
    const layered = slots.has("top") || slots.has("onepiece");
    return worn
      .flatMap((id): Piece[] => {
        const item = items[id];
        const asset = assets[id] ?? item?.asset;
        const ui = item ? toUiItem(item, base, asset) : null;
        if (!ui) return [];
        const templateId =
          asset?.template_id ?? (item.tags?.category === "boots" ? "boot_v1" : TEMPLATE_FOR_SLOT[ui.slot]);
        const sources =
          layered && ui.slot === "outer"
            ? [
                ...model(openModelUrl(asset, base)),
                ...model(ui.modelUrl),
                ...template(templateId, "_open", base),
                ...template(templateId, "", base),
              ]
            : [...model(ui.modelUrl), ...template(templateId, "", base)];
        if (!sources.length) return [];
        return [{ item, ui, layer: SLOT_LAYER_ORDER.indexOf(ui.slot), sources, tint: tintOf(item) }];
      })
      .sort((a, b) => a.layer - b.layer);
  }, [worn, items, assets, base]);
  // keeps current meshes on screen until replacement GLBs have loaded
  const pieces = useDeferredValue(current);

  return (
    <>
      {pieces.map(({ item, ui, layer, sources, tint }) => {
        const fit = garmentFit(item, profile);
        const nudge = 1 + NUDGE * layer;
        // a source that fails to load falls through to the next
        const chain = sources.reduceRight<ReactNode>(
          (fallback, { url, kind }) => (
            <Boundary key={url} fallback={fallback}>
              {kind === "model" ? <Model url={url} ui={ui} fit={fit} /> : <Template url={url} tint={tint} fit={fit} />}
            </Boundary>
          ),
          null,
        );
        return (
          <group key={ui.id} scale={[nudge, 1, nudge]}>
            <Suspense fallback={null}>{chain}</Suspense>
          </group>
        );
      })}
    </>
  );
}
