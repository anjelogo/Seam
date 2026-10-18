import clsx from "clsx";
import { Slider } from "../../components/ui";
import { formatFtIn } from "../../lib/viewmodel";
import styles from "./Onboarding.module.css";

export type HeightPickerProps = {
  cm: number;
  onChange: (cm: number) => void;
};

export function HeightPicker({ cm, onChange }: HeightPickerProps) {
  return (
    <div className={clsx(styles.height, "step-in")}>
      <p className={styles.readout}>
        <span className={clsx("t-big", styles.digits)}>{formatFtIn(cm)}</span>
        <span className={clsx("t-heading", "t-muted", styles.digits)}>{cm} cm</span>
      </p>
      <Slider
        label="height"
        hideLabel
        min={140}
        max={210}
        value={cm}
        onChange={onChange}
        readout={`${cm} cm`}
        className={styles.slider}
      />
    </div>
  );
}
