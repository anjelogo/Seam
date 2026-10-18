import clsx from "clsx";
import { useState } from "react";
import { IconCheck } from "../../components/ui";
import { isCutout, SILHOUETTE_PATHS } from "../../lib/lookJob";
import type { CardState, Phase } from "../../lib/lookJob";
import styles from "./ListingCard.module.css";
import { SilhouetteLoader } from "./SilhouetteLoader";

type Status = "found" | "picked" | "dim" | "gone" | "waiting" | "building" | "ready" | "failed";

function statusOf({ picked, model }: CardState, phase: Phase): Status {
  if (phase === 2) return picked ? "picked" : "dim";
  if (phase !== 3 && phase !== 4 && phase !== 5) return "found";
  if (!picked) return "gone";
  return model === "idle" ? "waiting" : model;
}

export type ListingCardProps = {
  card: CardState;
  phase: Phase;
};

export function ListingCard({ card, phase }: ListingCardProps) {
  const { listing, model, progress } = card;
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const status = statusOf(card, phase);
  const flipped = status === "building" || status === "ready";
  const showImage = listing.imageUrl !== "" && failedUrl !== listing.imageUrl;
  const path = SILHOUETTE_PATHS[listing.silhouette];
  const fill = Math.min(Math.max(progress, 0), 1);
  return (
    <div className={styles.slot} aria-hidden={status === "gone" || undefined}>
      <div className={clsx(styles.card, styles[status])}>
        <div className={clsx(styles.flipper, flipped && styles.flipped)}>
          <div className={clsx(styles.face, styles.front)} aria-hidden={flipped || undefined}>
            <div className={styles.photo}>
              {showImage ? (
                <img
                  src={listing.imageUrl}
                  alt=""
                  draggable={false}
                  decoding="async"
                  className={clsx(styles.image, isCutout(listing.imageUrl) && styles.cutout)}
                  onError={() => setFailedUrl(listing.imageUrl)}
                />
              ) : (
                <svg viewBox="0 0 64 64" className={styles.silhouette} aria-hidden="true" focusable="false">
                  <path
                    d={path}
                    fill={listing.color ?? "#cfc8bc"}
                    stroke="rgba(0, 0, 0, 0.25)"
                    strokeWidth={1}
                    vectorEffect="non-scaling-stroke"
                  />
                </svg>
              )}
              <span className={styles.tag}>{listing.source}</span>
              {status === "failed" && <span className={clsx(styles.tag, styles.twoD)}>2d only</span>}
            </div>
            <span className={styles.name}>{listing.name}</span>
          </div>
          <div className={clsx(styles.face, styles.back)} aria-hidden={!flipped || undefined}>
            <SilhouetteLoader path={path} size={72} slices={4} animate={model === "building"} />
            <span className={styles.meter}>
              {model === "ready" ? (
                <span className={styles.chip}>
                  <IconCheck size={12} strokeWidth={3} />
                  ready
                </span>
              ) : (
                <span className={styles.bar}>
                  <span className={styles.fill} style={{ width: `${fill * 100}%` }} />
                </span>
              )}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
