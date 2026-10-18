import clsx from "clsx";
import styles from "./StoreChips.module.css";

export type StoreChipsProps = {
  sources: string[];
  lit: string | null;
};

export function StoreChips({ sources, lit }: StoreChipsProps) {
  return (
    <ul aria-label="stores" className={styles.chips}>
      {sources.map((source) => (
        <li key={source} className={clsx("glass", styles.chip, source === lit && styles.lit)}>
          {source}
        </li>
      ))}
    </ul>
  );
}
