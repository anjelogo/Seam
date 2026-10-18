import clsx from "clsx";
import { useEffect, useState } from "react";
import { Button, IconButton, IconClose, TextLink } from "../../components/ui";
import { useLook, useStage, useWornItems } from "../../state";
import styles from "./DetailCard.module.css";

const close = () => useStage.getState().select(null);

export default function DetailCard() {
  const selected = useStage((s) => s.selected);
  const item = useWornItems().find((worn) => worn.id === selected);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const stale = selected !== null && !item;

  useEffect(() => {
    if (stale) close();
  }, [stale]);

  if (!item) return null;

  const takeOff = () => {
    useLook.getState().takeOff(item.id);
    close();
  };

  return (
    <section className={clsx("glass", styles.card)} aria-label="item details">
      <div className={styles.head}>
        <p className={clsx("t-label", styles.meta)}>
          {item.category} · {item.source}
        </p>
        <IconButton aria-label="close" onClick={close}>
          <IconClose />
        </IconButton>
      </div>
      <div className={styles.photo}>
        {item.imageUrl !== "" && failedUrl !== item.imageUrl && (
          <img src={item.imageUrl} alt="" draggable={false} onError={() => setFailedUrl(item.imageUrl)} />
        )}
      </div>
      <h2 className={styles.name}>{item.name}</h2>
      <p className={styles.facts}>
        {item.size && <span className="t-muted">size {item.size}</span>}
        <span className={styles.price}>{item.priceLabel}</span>
      </p>
      <TextLink href={item.listingUrl} external className={styles.link}>
        view listing ↗
      </TextLink>
      <Button className={styles.takeOff} onClick={takeOff}>
        take off
      </Button>
    </section>
  );
}
