import clsx from "clsx";
import { useEffect, useId, useRef } from "react";
import { Button } from "../../components/ui";
import { useStage, useWornTotal } from "../../state";
import styles from "./CheckoutPill.module.css";

const open = () => useStage.getState().setCheckoutOpen(true);

export default function CheckoutPill() {
  const { count, label } = useWornTotal();
  const summaryId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);

  // the sheet unmounts on close, so focus comes back to its trigger
  useEffect(
    () =>
      useStage.subscribe((state, prev) => {
        if (prev.checkoutOpen && !state.checkoutOpen) buttonRef.current?.focus();
      }),
    [],
  );

  return (
    <div className={clsx("glass", styles.pill)}>
      <span id={summaryId} className={styles.summary}>
        {count} {count === 1 ? "item" : "items"} · {label}
      </span>
      <Button ref={buttonRef} disabled={count === 0} aria-describedby={summaryId} onClick={open}>
        check out
      </Button>
    </div>
  );
}
