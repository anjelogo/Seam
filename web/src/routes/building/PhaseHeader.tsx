import { useEffect, useState } from "react";
import styles from "./PhaseHeader.module.css";

const SETTLE_MS = 500;

export type PhaseHeaderProps = {
  title: string;
  sub: string;
};

// the visible sub counts up every ~100 ms, so readers get it once it settles
function SettledSub({ text }: { text: string }) {
  const [settled, setSettled] = useState(text);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(text), SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [text]);
  return <p className="sr-only">{settled}</p>;
}

export function PhaseHeader({ title, sub }: PhaseHeaderProps) {
  return (
    <div role="status" aria-live="polite" aria-atomic="true" className={styles.header}>
      <div key={title} className={styles.content}>
        <h1 className={styles.title}>{title}</h1>
        <p className={styles.sub} aria-hidden="true">
          {sub}
        </p>
        <SettledSub text={sub} />
      </div>
    </div>
  );
}
