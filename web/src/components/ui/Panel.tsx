import clsx from "clsx";
import type { HTMLAttributes } from "react";
import styles from "./Panel.module.css";

export type PanelProps = HTMLAttributes<HTMLElement> & { as?: "section" | "div" | "aside" };

export function Panel({ as: Tag = "section", className, ...rest }: PanelProps) {
  return <Tag className={clsx("glass", styles.panel, className)} {...rest} />;
}
