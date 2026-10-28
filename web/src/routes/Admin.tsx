import clsx from "clsx";
import { useEffect, useState } from "react";
import { TeeLoader, TeeMark, Wordmark } from "../components/brand";
import { Button, IconCheck, InfoTip, TextLink } from "../components/ui";
import { exportItems, getAdminStats } from "../lib/api";
import type { RequestError } from "../lib/api";
import styles from "./Admin.module.css";

type Stats = Awaited<ReturnType<typeof getAdminStats>>;
type Phase = { kind: "idle" } | { kind: "working" } | { kind: "done"; name: string } | { kind: "failed"; message: string };

export default function Admin() {
  const [stats, setStats] = useState<Stats | "denied" | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });

  useEffect(() => {
    getAdminStats().then(setStats, () => setStats("denied"));
  }, []);

  if (stats === null) return <TeeLoader className={styles.center} />;
  if (stats === "denied")
    return (
      <main className={clsx(styles.denied, "step-in")}>
        <TeeMark size={72} />
        <h1 className={styles.big}>nothing here.</h1>
        <Button to="/avatar" size="lg">
          back to seam
        </Button>
      </main>
    );

  const run = async () => {
    setPhase({ kind: "working" });
    try {
      const { blob, name } = await exportItems();
      const url = URL.createObjectURL(blob);
      const a = Object.assign(document.createElement("a"), { href: url, download: name });
      a.click();
      URL.revokeObjectURL(url);
      setPhase({ kind: "done", name });
    } catch (e) {
      setPhase({ kind: "failed", message: (e as RequestError).detail ?? "export failed." });
    }
  };

  return (
    <div className={styles.frame}>
      <header className={clsx(styles.bar, "step-in")}>
        <span className={styles.brand}>
          <Wordmark size={28} />
          <span className={styles.label}>admin</span>
        </span>
        <TextLink to="/avatar">back to seam</TextLink>
      </header>
      <main className={styles.main}>
        <section className={clsx("glass", "step-in", styles.card)} aria-labelledby="admin-title">
          <div className={styles.heading}>
            <h1 id="admin-title" className={styles.title}>
              export items.
            </h1>
            <InfoTip
              label="what's in the export"
              text="every row of the items table as json lines: listing, tags and status. no users, sessions or looks."
            />
          </div>
          <dl className={styles.stats}>
            {(["items", "tagged", "active"] as const).map((k) => (
              <div key={k} className={styles.stat}>
                <dt className={styles.label}>{k}</dt>
                <dd className={styles.value}>{stats[k].toLocaleString()}</dd>
              </div>
            ))}
          </dl>
          <div className={styles.rule} />
          <div className={styles.actions} aria-live="polite">
            {phase.kind === "working" ? (
              <>
                <TeeLoader size={40} label="exporting" />
                <span>exporting…</span>
              </>
            ) : phase.kind === "done" ? (
              <>
                <span className={styles.check}>
                  <IconCheck size={18} />
                </span>
                <span>{phase.name} saved</span>
                <button type="button" className={styles.again} onClick={() => setPhase({ kind: "idle" })}>
                  again
                </button>
              </>
            ) : (
              <>
                <Button size="lg" onClick={run}>
                  export items
                </Button>
                <span className={styles.muted}>{phase.kind === "failed" ? phase.message : ".jsonl · items table only"}</span>
              </>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
