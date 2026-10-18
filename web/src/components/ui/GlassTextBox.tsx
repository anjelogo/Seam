import clsx from "clsx";
import { forwardRef, useId } from "react";
import type { TextareaHTMLAttributes } from "react";
import styles from "./GlassTextBox.module.css";

export type GlassTextBoxProps = TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string };

export const GlassTextBox = forwardRef<HTMLTextAreaElement, GlassTextBoxProps>(function GlassTextBox(
  { label, id, rows = 3, className, style, ...rest },
  ref,
) {
  const autoId = useId();
  const boxId = id ?? autoId;
  return (
    <div className={clsx(styles.field, className)} style={style}>
      <label htmlFor={boxId} className="sr-only">
        {label}
      </label>
      <textarea ref={ref} id={boxId} rows={rows} className={clsx("glass", styles.box)} {...rest} />
    </div>
  );
});
