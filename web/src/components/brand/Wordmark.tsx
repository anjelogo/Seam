import clsx from "clsx";
import type { ElementType } from "react";
import styles from "./Wordmark.module.css";

export type WordmarkProps = {
  size?: number;
  glow?: boolean;
  as?: ElementType;
  className?: string;
};

export function Wordmark({ size = 28, glow = size >= 64, as: Tag = "span", className }: WordmarkProps) {
  return (
    <Tag className={clsx(styles.wordmark, glow && styles.glow, className)} style={{ fontSize: size }}>
      seam
    </Tag>
  );
}
