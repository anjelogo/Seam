import clsx from "clsx";
import { useSyncExternalStore } from "react";
import { Lockup } from "../components/brand";
import { Button, TextLink } from "../components/ui";
import styles from "./Splash.module.css";

const subscribe = (onChange: () => void) => {
  window.addEventListener("resize", onChange);
  return () => window.removeEventListener("resize", onChange);
};

const heroSize = () => Math.round(Math.min(Math.max(window.innerWidth * 0.104, 96), 176));

const TAG_ROWS = [
  ["item", "band tee"],
  ["size", "m"],
  ["source", "ebay"],
] as const;

export default function Splash() {
  const size = useSyncExternalStore(subscribe, heroSize);

  // step-in sits on the glass itself: a fading ancestor switches off its backdrop blur
  return (
    <main className={styles.splash}>
      <div className={clsx(styles.hero, "step-in")}>
        <Lockup as="h1" size={size} />
        <p className={styles.tagline}>
          thrift a vibe, try it in 3d. <span className={styles.seamless}>seamless.</span>
        </p>
        <div className={styles.actions}>
          <Button size="lg" to="/signup">
            sign up
          </Button>
          <TextLink to="/login">log in</TextLink>
        </div>
      </div>
      <aside className={clsx("glass", "step-in", styles.tag)} aria-hidden="true">
        <span className={styles.hole} />
        <dl className={styles.rows}>
          {TAG_ROWS.map(([label, value]) => (
            <div key={label}>
              <dt className="t-label">{label}</dt>
              <dd className={styles.value}>{value}</dd>
            </div>
          ))}
        </dl>
        <span className={styles.stamp}>tried on</span>
      </aside>
    </main>
  );
}
