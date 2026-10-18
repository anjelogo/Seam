import clsx from "clsx";
import type { CSSProperties } from "react";
import { useReducedMotion } from "../../lib/motion";
import styles from "./SilhouetteLoader.module.css";

const STROKE_OPACITY: Record<number, number[]> = {
  4: [1, 0.65, 0.45, 0.3],
  6: [1, 0.65, 0.52, 0.42, 0.32, 0.25],
};

function paintOf(i: number, slices: number) {
  if (i === 0) return { fill: "rgba(255, 255, 255, 0.18)", strokeWidth: 4, strokeOpacity: 1 };
  const table = STROKE_OPACITY[slices];
  return {
    fill: i === slices - 1 ? "rgba(255, 255, 255, 0.12)" : "none",
    strokeWidth: 2,
    strokeOpacity: table ? table[i] : 0.65 - (0.4 * (i - 1)) / Math.max(1, slices - 2),
  };
}

export type SilhouetteLoaderProps = {
  path: string;
  size: number;
  slices: number;
  animate: boolean;
};

export function SilhouetteLoader({ path, size, slices, animate }: SilhouetteLoaderProps) {
  const reduced = useReducedMotion();
  return (
    <span className={styles.loader} style={{ fontSize: size }} aria-hidden="true">
      <span className={clsx(styles.stack, animate && !reduced && styles.animate)}>
        {Array.from({ length: slices }, (_, n) => {
          const i = slices - 1 - n;
          return (
            <svg
              key={i}
              viewBox="0 0 64 64"
              className={styles.slice}
              style={{ "--i": i } as CSSProperties}
              aria-hidden="true"
              focusable="false"
            >
              <path
                d={path}
                stroke="#fff"
                strokeLinejoin="round"
                strokeLinecap="round"
                {...paintOf(i, slices)}
              />
            </svg>
          );
        })}
      </span>
    </span>
  );
}
