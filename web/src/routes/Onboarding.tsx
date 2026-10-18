import type { BodyBase } from "@shared/types";
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";
import { fireSurge } from "../components/bg";
import { Wordmark } from "../components/brand";
import {
  Button,
  GlassTextBox,
  IconButton,
  IconChevronLeft,
  InfoTip,
  PillGroup,
  ProgressBar,
} from "../components/ui";
import type { Profile, TopSize } from "../lib/viewmodel";
import { DEFAULT_PROFILE, useLook, useProfile } from "../state";
import { HeightPicker } from "./onboarding/HeightPicker";
import styles from "./onboarding/Onboarding.module.css";
import { BASE_OPTIONS, SIZE_OPTIONS, SKIN_OPTIONS, STEPS } from "./onboarding/steps";
import { parseWeight, WeightField } from "./onboarding/WeightField";

const ADVANCE_MS = 420;
const SURGE_MS = 1600;

type Draft = {
  heightCm: number;
  weight: string;
  weightUnit: Profile["weightUnit"];
  base: BodyBase | null;
  skinTone: string | null;
  topSize: TopSize | null;
};

function initialDraft(): Draft {
  const saved = useProfile.getState().profile;
  const { heightCm, weight, weightUnit } = saved ?? DEFAULT_PROFILE;
  return {
    heightCm,
    weight: String(weight),
    weightUnit,
    base: saved?.base ?? null,
    skinTone: saved?.skinTone ?? null,
    topSize: saved?.topSize ?? null,
  };
}

export default function Onboarding() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [draft, setDraft] = useState(initialDraft);
  const [prompt, setPrompt] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const focusedStep = useRef(step);
  const advanceTimer = useRef<number>();
  const weight = parseWeight(draft.weight);
  const { question, tip } = STEPS[step - 1];

  const edit = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }));

  const go = (next: number) => {
    window.clearTimeout(advanceTimer.current);
    advanceTimer.current = undefined;
    fireSurge(SURGE_MS);
    setStep(next);
  };

  const next = () => {
    if (step === 2 && weight === null) return;
    go(step + 1);
  };

  const advance = () => {
    if (advanceTimer.current !== undefined) return;
    const target = step + 1;
    advanceTimer.current = window.setTimeout(() => go(target), ADVANCE_MS);
  };

  useEffect(() => () => window.clearTimeout(advanceTimer.current), []);

  useEffect(() => {
    if (focusedStep.current === step) return;
    focusedStep.current = step;
    heading.current?.focus({ preventScroll: true });
  }, [step]);

  const submit = () => {
    const text = prompt.trim();
    if (!text) return;
    const { profile, setProfile } = useProfile.getState();
    setProfile({
      heightCm: draft.heightCm,
      weight: Number(draft.weight),
      weightUnit: draft.weightUnit,
      base: draft.base ?? DEFAULT_PROFILE.base,
      skinTone: draft.skinTone ?? DEFAULT_PROFILE.skinTone,
      topSize: draft.topSize ?? DEFAULT_PROFILE.topSize,
      body: profile?.body ?? DEFAULT_PROFILE.body,
    });
    void useLook.getState().build(text);
    fireSurge(SURGE_MS);
    navigate("/avatar", { state: { tab: "style" } });
  };

  const onPromptKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    submit();
  };

  return (
    <div className={styles.frame}>
      <header className={clsx(styles.header, "step-in")}>
        <div className={styles.bar}>
          <Wordmark size={28} />
          <span className="t-label">
            step {step} / {STEPS.length}
          </span>
        </div>
        <ProgressBar segments={STEPS.length} done={step} label="onboarding progress" />
      </header>
      <main className={styles.main}>
        <div key={step} className={styles.step}>
          <div className={clsx("t-question", "step-in", styles.question)}>
            <h1 ref={heading} tabIndex={-1} className={clsx("t-question", styles.heading)}>
              {question}
            </h1>
            <InfoTip text={tip} label="about this question" className={styles.tip} />
          </div>
          {step === 1 && <HeightPicker cm={draft.heightCm} onChange={(heightCm) => edit({ heightCm })} />}
          {step === 2 && (
            <WeightField weight={draft.weight} unit={draft.weightUnit} onChange={edit} onEnter={next} />
          )}
          {step === 3 && (
            <PillGroup
              variant="cards"
              name="base"
              legend="body base"
              options={BASE_OPTIONS}
              value={draft.base}
              onChange={(base) => edit({ base: base as BodyBase })}
              onCommit={advance}
              className={styles.glassIn}
            />
          )}
          {step === 4 && (
            <PillGroup
              variant="swatches"
              name="skin"
              legend="skin tone"
              options={SKIN_OPTIONS}
              value={draft.skinTone}
              onChange={(skinTone) => edit({ skinTone })}
              onCommit={advance}
              className="step-in"
            />
          )}
          {step === 5 && (
            <PillGroup
              name="size"
              legend="top size"
              options={SIZE_OPTIONS}
              value={draft.topSize}
              onChange={(topSize) => edit({ topSize: topSize as TopSize })}
              onCommit={advance}
              className={styles.glassIn}
            />
          )}
          {step === 6 && (
            <GlassTextBox
              label="style prompt"
              placeholder="grunge 2000s, cowboy, quiet luxury..."
              maxLength={200}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={onPromptKeyDown}
              className={clsx(styles.prompt, styles.glassIn)}
            />
          )}
        </div>
      </main>
      <footer className={styles.footer}>
        <IconButton
          aria-label="back"
          className={clsx(step === 1 && styles.hidden)}
          onClick={() => go(step - 1)}
        >
          <IconChevronLeft />
        </IconButton>
        {step <= 2 && (
          <Button size="lg" disabled={step === 2 && weight === null} onClick={next} className="step-in">
            next
          </Button>
        )}
        {step === 6 && (
          <Button size="lg" disabled={!prompt.trim()} onClick={submit} className="step-in">
            build my look
          </Button>
        )}
      </footer>
    </div>
  );
}
