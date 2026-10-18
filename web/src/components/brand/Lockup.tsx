import clsx from "clsx";
import type { ElementType } from "react";
import styles from "./Lockup.module.css";
import { TeeMark } from "./TeeMark";
import { Wordmark } from "./Wordmark";

export type LockupProps = {
  size?: number;
  as?: ElementType;
  className?: string;
};

export function Lockup({ size = 120, as: Tag = "div", className }: LockupProps) {
  return (
    <Tag className={clsx(styles.lockup, className)} style={{ gap: size * 0.15 }}>
      <TeeMark size={size * 0.86} className={styles.mark} />
      <Wordmark size={size} />
    </Tag>
  );
}
