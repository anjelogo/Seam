import clsx from "clsx";
import styles from "./ProgressBar.module.css";

export type ProgressBarProps = {
  segments: number;
  done: number;
  label?: string;
  className?: string;
};

export function ProgressBar({ segments, done, label = "progress", className }: ProgressBarProps) {
  const now = Math.min(Math.max(done, 0), segments);
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={segments}
      aria-valuenow={now}
      aria-valuetext={`${now} of ${segments}`}
      className={clsx(styles.bar, className)}
    >
      {Array.from({ length: segments }, (_, index) => (
        <span key={index} className={clsx(styles.segment, index < now && styles.done)} />
      ))}
    </div>
  );
}
