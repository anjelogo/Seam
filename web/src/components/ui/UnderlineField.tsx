import clsx from "clsx";
import { forwardRef, useId } from "react";
import type { InputHTMLAttributes } from "react";
import { InfoTip } from "./InfoTip";
import styles from "./UnderlineField.module.css";

export type UnderlineFieldProps = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  tip?: string;
  tipOpen?: boolean;
  tipLabel?: string;
};

export const UnderlineField = forwardRef<HTMLInputElement, UnderlineFieldProps>(
  function UnderlineField({ label, tip, tipOpen, tipLabel, id, className, style, ...rest }, ref) {
    const autoId = useId();
    const inputId = id ?? autoId;
    return (
      <div className={clsx(styles.field, className)} style={style}>
        <div className={styles.labelRow}>
          <label htmlFor={inputId} className="t-label">
            {label}
          </label>
          {tip ? (
            <InfoTip
              text={tip}
              open={tipOpen}
              label={tipLabel ?? `about ${label}`}
              className={styles.tip}
            />
          ) : null}
        </div>
        <input ref={ref} id={inputId} className={styles.input} {...rest} />
      </div>
    );
  },
);
