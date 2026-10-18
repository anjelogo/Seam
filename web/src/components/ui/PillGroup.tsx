import clsx from "clsx";
import { useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import styles from "./PillGroup.module.css";

export type PillOption = { value: string; label: string; content?: ReactNode; swatch?: string };

export type PillGroupProps = {
  name: string;
  legend: string;
  options: readonly PillOption[];
  value: string | null;
  onChange: (value: string) => void;
  onCommit?: (value: string) => void;
  variant?: "pills" | "cards" | "swatches";
  className?: string;
};

type Variant = NonNullable<PillGroupProps["variant"]>;

export function PillGroup({
  name,
  legend,
  options,
  value,
  onChange,
  onCommit,
  variant = "pills",
  className,
}: PillGroupProps) {
  const pressed = useRef<string | null>(null);

  const commitPressed = (next: string) => {
    if (pressed.current !== next) return;
    pressed.current = null;
    onCommit?.(next);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>, next: string) => {
    pressed.current = null;
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (event.repeat) return;
    if (next !== value) onChange(next);
    onCommit?.(next);
  };

  return (
    <fieldset className={clsx(styles.group, className)}>
      <legend className="sr-only">{legend}</legend>
      <div className={clsx(styles.track, styles[variant], variant === "pills" && "glass")}>
        {options.map((option) => (
          <label
            key={option.value}
            className={styles.option}
            onPointerDown={() => {
              pressed.current = option.value;
            }}
          >
            <input
              className={styles.input}
              type="radio"
              name={name}
              value={option.value}
              checked={option.value === value}
              onChange={() => {
                onChange(option.value);
                commitPressed(option.value);
              }}
              onClick={() => {
                // a click on the selected option fires no change event
                if (option.value === value) commitPressed(option.value);
              }}
              onKeyDown={(event) => onKeyDown(event, option.value)}
            />
            <Visual option={option} variant={variant} />
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Visual({ option, variant }: { option: PillOption; variant: Variant }) {
  if (variant === "swatches") {
    return (
      <span
        className={clsx(styles.visual, styles.swatch)}
        style={{ backgroundColor: option.swatch }}
      >
        <span className="sr-only">{option.label}</span>
      </span>
    );
  }
  if (variant === "cards") {
    return (
      <span className={clsx("glass", styles.visual, styles.card)}>
        {option.content ? <span className={styles.cardContent}>{option.content}</span> : null}
        <span className={styles.cardLabel}>{option.label}</span>
      </span>
    );
  }
  return <span className={clsx(styles.visual, styles.pill)}>{option.label}</span>;
}
