import clsx from "clsx";
import { useEffect, useId, useLayoutEffect, useRef } from "react";
import type { CSSProperties } from "react";
import styles from "./Slider.module.css";

export type SliderProps = {
  label: string;
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (value: number) => void;
  readout?: string;
  hideLabel?: boolean;
  onDragStart?: () => void;
  onDragEnd?: () => void;
  id?: string;
  className?: string;
};

export function Slider({
  label,
  min,
  max,
  step = 1,
  value,
  onChange,
  readout,
  hideLabel = false,
  onDragStart,
  onDragEnd,
  id,
  className,
}: SliderProps) {
  const autoId = useId();
  const inputId = id ?? autoId;
  const drag = useRef({ onDragStart, onDragEnd });
  const stopDrag = useRef<(() => void) | null>(null);
  const fill = max > min ? ((Math.min(Math.max(value, min), max) - min) / (max - min)) * 100 : 0;

  useLayoutEffect(() => {
    drag.current = { onDragStart, onDragEnd };
  });

  useEffect(() => () => stopDrag.current?.(), []);

  const startDrag = () => {
    if (stopDrag.current) return;
    const stop = () => {
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
      stopDrag.current = null;
      drag.current.onDragEnd?.();
    };
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
    stopDrag.current = stop;
    drag.current.onDragStart?.();
  };

  return (
    <div className={clsx(styles.slider, className)}>
      <div className={clsx(styles.labelRow, hideLabel && "sr-only")}>
        <label htmlFor={inputId} className="t-label">
          {label}
        </label>
        {readout !== undefined && (
          <span className={styles.readout} aria-hidden="true">
            {readout}
          </span>
        )}
      </div>
      <input
        id={inputId}
        className={styles.input}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        aria-valuetext={readout}
        style={{ "--fill": `${fill}%` } as CSSProperties}
        onChange={(event) => onChange(Number(event.currentTarget.value))}
        onPointerDown={startDrag}
      />
    </div>
  );
}
