import clsx from "clsx";
import { useState } from "react";
import { fireSurge } from "../../components/bg";
import { TeeLoader } from "../../components/brand";
import { InfoTip, UnderlineField } from "../../components/ui";
import type { Look } from "../../lib/viewmodel";
import { useLook } from "../../state";
import styles from "./StylePane.module.css";

const SURGE_MS = 1400;

export default function StylePane() {
  const [text, setText] = useState(() => useLook.getState().prompt);
  const building = useLook((s) => s.building);
  const lastError = useLook((s) => s.lastError);
  const saved = useLook((s) => s.saved);

  const submit = () => {
    if (!text.trim()) return;
    fireSurge(SURGE_MS);
    void useLook.getState().build(text);
  };

  const wear = (look: Look) => {
    setText(look.prompt);
    useLook.getState().wearLook(look);
  };

  return (
    <div className={styles.pane}>
      <UnderlineField
        label="describe a vibe"
        autoComplete="off"
        maxLength={200}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          if (lastError) useLook.getState().clearError();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.nativeEvent.isComposing) submit();
        }}
      />
      {building ? (
        <TeeLoader label="building your look" className={styles.loader} />
      ) : (
        lastError && <p className="t-muted">{lastError}</p>
      )}
      <div className={styles.head}>
        <h2 className="t-heading">saved fits</h2>
        <InfoTip text="outfits you save land here." label="about saved fits" className={styles.tip} />
      </div>
      <ul className={styles.list}>
        {saved.map((look) => (
          <li key={JSON.stringify(look)}>
            <button type="button" className={clsx("glass-dark", styles.look)} onClick={() => wear(look)}>
              <span className={styles.prompt}>{look.prompt}</span>
              <span className="t-label">
                {look.itemIds.length} {look.itemIds.length === 1 ? "piece" : "pieces"}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
