import clsx from "clsx";
import { PillGroup } from "../../components/ui";
import { fromLb, toLb } from "../../lib/viewmodel";
import type { Profile } from "../../lib/viewmodel";
import styles from "./Onboarding.module.css";

type Unit = Profile["weightUnit"];

const UNITS = [
  { value: "lb", label: "lb" },
  { value: "kg", label: "kg" },
];

export function parseWeight(text: string): number | null {
  const value = Number(text);
  return value > 0 ? value : null;
}

function cleanWeight(raw: string) {
  const [whole, ...rest] = raw.replace(/[^\d.]/g, "").split(".");
  return (rest.length ? `${whole}.${rest.join("")}` : whole).slice(0, 5);
}

export type WeightFieldProps = {
  weight: string;
  unit: Unit;
  onChange: (next: { weight: string; weightUnit?: Unit }) => void;
  onEnter: () => void;
};

export function WeightField({ weight, unit, onChange, onEnter }: WeightFieldProps) {
  const switchUnit = (next: string) => {
    const weightUnit = next as Unit;
    const value = parseWeight(weight);
    const converted = value === null ? weight : String(Math.round(fromLb(toLb(value, unit), weightUnit)));
    onChange({ weight: converted, weightUnit });
  };

  return (
    <div className={styles.weight}>
      <span className={clsx(styles.weightBox, "step-in")}>
        <span className={styles.weightGlow} aria-hidden="true">
          {weight}
        </span>
        <input
          className={styles.weightInput}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          aria-label="weight"
          value={weight}
          onChange={(event) => onChange({ weight: cleanWeight(event.target.value) })}
          onKeyDown={(event) => {
            if (event.key === "Enter") onEnter();
          }}
        />
      </span>
      <PillGroup
        name="unit"
        legend="unit"
        options={UNITS}
        value={unit}
        onChange={switchUnit}
        className={styles.glassIn}
      />
    </div>
  );
}
