import clsx from "clsx";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import type { FocusEvent } from "react";
import { createPortal } from "react-dom";
import { IconInfo } from "./icons";
import styles from "./InfoTip.module.css";

export type InfoTipProps = {
  text: string;
  label?: string;
  open?: boolean;
  className?: string;
};

const GLYPH = 18;
const OFFSET = 6;
const MARGIN = 12;
const CLOSE_DELAY = 100;

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(value, max));

export function InfoTip({ text, label = "info", open = false, className }: InfoTipProps) {
  const tipId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<number>();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const shown = open || ((hovered || focused) && !dismissed);

  const hold = () => {
    window.clearTimeout(closeTimer.current);
    setHovered(true);
  };

  const release = () => {
    window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => setHovered(false), CLOSE_DELAY);
  };

  const onFocus = (event: FocusEvent<HTMLButtonElement>) => {
    if (!event.currentTarget.matches(":focus-visible")) return;
    setFocused(true);
    setDismissed(false);
  };

  useEffect(() => () => window.clearTimeout(closeTimer.current), []);

  useEffect(() => {
    if (!shown || open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDismissed(true);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [shown, open]);

  useLayoutEffect(() => {
    if (!shown) return;
    const place = () => {
      const button = buttonRef.current;
      const tip = tipRef.current;
      if (!button || !tip) return;
      const rect = button.getBoundingClientRect();
      const width = tip.offsetWidth;
      const height = tip.offsetHeight;
      const viewWidth = document.documentElement.clientWidth;
      const viewHeight = document.documentElement.clientHeight;
      const glyphTop = rect.top + (rect.height - GLYPH) / 2;
      let top = glyphTop - OFFSET - height;
      if (top < MARGIN) top = glyphTop + GLYPH + OFFSET;
      top = clamp(top, MARGIN, viewHeight - MARGIN - height);
      const left = clamp(rect.left + rect.width / 2 - width / 2, MARGIN, viewWidth - MARGIN - width);
      tip.style.top = `${Math.round(top)}px`;
      tip.style.left = `${Math.round(left)}px`;
    };
    place();
    window.addEventListener("scroll", place, { capture: true, passive: true });
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, { capture: true });
      window.removeEventListener("resize", place);
    };
  }, [shown, text]);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={clsx(styles.button, shown && styles.active, className)}
        aria-label={label}
        aria-describedby={tipId}
        onPointerEnter={() => {
          hold();
          setDismissed(false);
        }}
        onPointerLeave={release}
        onFocus={onFocus}
        onBlur={() => setFocused(false)}
        onClick={() => setDismissed(false)}
      >
        <IconInfo size={GLYPH} />
      </button>
      {createPortal(
        <div
          ref={tipRef}
          id={tipId}
          role="tooltip"
          className={clsx(styles.tip, shown && styles.shown)}
          onPointerEnter={hold}
          onPointerLeave={release}
        >
          {text}
        </div>,
        document.body,
      )}
    </>
  );
}
