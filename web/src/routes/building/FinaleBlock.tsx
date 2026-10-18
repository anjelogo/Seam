import clsx from "clsx";
import { IconCheck } from "../../components/ui";
import { SILHOUETTE_PATHS } from "../../lib/lookJob";
import styles from "./FinaleBlock.module.css";
import { SilhouetteLoader } from "./SilhouetteLoader";

export type FinaleBlockProps = {
  names: string[];
  animate: boolean;
};

export function FinaleBlock({ names, animate }: FinaleBlockProps) {
  return (
    <div className={styles.finale}>
      <span role="img" aria-label="seam" className={clsx(styles.mark, styles.rise)}>
        <SilhouetteLoader path={SILHOUETTE_PATHS.tee} size={180} slices={6} animate={animate} />
      </span>
      {names.length > 0 && (
        <ul className={styles.chips}>
          {names.map((name, index) => (
            <li key={index} className={clsx("glass", styles.chip, styles.rise)}>
              <IconCheck size={16} strokeWidth={3} className={styles.check} />
              <span className={styles.name}>{name}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
