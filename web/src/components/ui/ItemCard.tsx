import clsx from "clsx";
import { useState } from "react";
import type { ReactNode } from "react";
import type { UiItem } from "../../lib/viewmodel";
import { IconCheck } from "./icons";
import styles from "./ItemCard.module.css";

export type ItemCardProps = {
  item: UiItem;
  selected: boolean;
  onToggle: (id: string) => void;
  overlay?: ReactNode;
  className?: string;
};

export function ItemCard({ item, selected, onToggle, overlay, className }: ItemCardProps) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showImage = item.imageUrl !== "" && failedUrl !== item.imageUrl;
  return (
    <button
      type="button"
      aria-pressed={selected}
      aria-label={`${item.name}, ${item.source}, ${item.priceLabel}`}
      className={clsx("glass-dark", styles.card, selected && styles.selected, className)}
      onClick={() => onToggle(item.id)}
    >
      <span className={styles.photo}>
        {showImage && (
          <img
            src={item.imageUrl}
            alt=""
            loading="lazy"
            draggable={false}
            onError={() => setFailedUrl(item.imageUrl)}
          />
        )}
        {overlay ? <span className={styles.overlay}>{overlay}</span> : null}
      </span>
      <span className={clsx("t-label", styles.meta)}>
        {item.source} · {item.priceLabel}
      </span>
      <span className={styles.name}>{item.name}</span>
      <span className={styles.badge}>
        <IconCheck size={14} strokeWidth={3} />
      </span>
    </button>
  );
}
