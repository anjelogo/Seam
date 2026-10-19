import type { BodyBase } from "@shared/types";
import clsx from "clsx";
import { InfoTip, PillGroup, Slider } from "../../components/ui";
import { formatFtIn, fromLb } from "../../lib/viewmodel";
import type { Profile, TopSize } from "../../lib/viewmodel";
import { DEFAULT_PROFILE, useProfile } from "../../state";
import type { ProfilePatch } from "../../state";
import { SIZE_OPTIONS } from "../onboarding/steps";
import styles from "./BodyPane.module.css";

const BASES = [
  { value: "masc", label: "masculine" },
  { value: "fem", label: "feminine" },
];

const SHAPE: { key: keyof Profile["body"]; label: string }[] = [
  { key: "shoulders", label: "shoulders" },
  { key: "chest", label: "chest" },
  { key: "waist", label: "waist" },
  { key: "hips", label: "hips" },
  { key: "legs", label: "leg length" },
];

const WAISTS = [26, 28, 30, 32, 34, 36, 38, 40].map((inches) => ({ value: `W${inches}`, label: `w${inches}` }));

const patch = (next: ProfilePatch) => useProfile.getState().patch(next);

const drag = {
  onDragStart: () => useProfile.getState().setDragging(true),
  onDragEnd: () => useProfile.getState().setDragging(false),
};

export default function BodyPane() {
  const profile = useProfile((s) => s.profile) ?? DEFAULT_PROFILE;
  const { heightCm, weightUnit, body } = profile;
  const weight = Math.round(profile.weight);

  return (
    <div className={styles.pane}>
      <PillGroup
        name="base"
        legend="body base"
        options={BASES}
        value={profile.base}
        onChange={(base) => patch({ base: base as BodyBase })}
        className={styles.base}
      />
      <Slider
        label="height"
        min={140}
        max={210}
        value={heightCm}
        readout={`${formatFtIn(heightCm)} · ${heightCm} cm`}
        onChange={(next) => patch({ heightCm: next })}
        {...drag}
      />
      <Slider
        label="weight"
        min={Math.round(fromLb(90, weightUnit))}
        max={Math.round(fromLb(300, weightUnit))}
        value={weight}
        readout={`${weight} ${weightUnit}`}
        onChange={(next) => patch({ weight: next })}
        {...drag}
      />
      {SHAPE.map(({ key, label }) => (
        <Slider
          key={key}
          label={label}
          min={0}
          max={100}
          value={body[key]}
          readout={String(body[key])}
          onChange={(next) => patch({ body: { [key]: next } })}
          {...drag}
        />
      ))}
      <div className={styles.head}>
        <h2 className="t-heading">sizes</h2>
        <InfoTip text="used to show how each piece will actually fit you." label="about sizes" className={styles.tip} />
      </div>
      <p className={clsx("t-label", styles.label)} aria-hidden="true">
        top
      </p>
      <PillGroup
        name="top-size"
        legend="top size"
        options={SIZE_OPTIONS}
        value={profile.topSize}
        onChange={(topSize) => patch({ topSize: topSize as TopSize })}
        className={styles.sizes}
      />
      <p className={clsx("t-label", styles.label)} aria-hidden="true">
        bottom
      </p>
      <PillGroup
        name="bottom-size"
        legend="bottom size"
        options={WAISTS}
        value={profile.bottomSize}
        onChange={(bottomSize) => patch({ bottomSize })}
        className={clsx(styles.sizes, styles.waists)}
      />
    </div>
  );
}
