import clsx from "clsx";
import { useMemo } from "react";
import { TeeLoader } from "../../components/brand";
import { ItemCard, UnderlineField } from "../../components/ui";
import { useInventory, useLook, useUiItems } from "../../state";
import styles from "./InventoryPane.module.css";

const search = (q: string, immediate?: boolean) => useInventory.getState().search(q, immediate);
const toggle = (id: string) => useLook.getState().toggle(id);

export default function InventoryPane() {
  const query = useInventory((s) => s.query);
  const results = useInventory((s) => s.results);
  const loading = useInventory((s) => s.loading);
  const error = useInventory((s) => s.error);
  const worn = useLook((s) => s.worn);
  const usable = useMemo(() => results.filter((item) => item.tags?.usable_for_3d !== false), [results]);
  const items = useUiItems(usable);

  return (
    <div className={styles.pane}>
      <UnderlineField
        label="search every store"
        type="search"
        autoComplete="off"
        value={query}
        onChange={(event) => search(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") search(query, true);
        }}
      />
      {loading ? (
        <TeeLoader label="searching" className={styles.status} />
      ) : error || !items.length ? (
        <p className={clsx("t-muted", styles.status)}>{error ?? "nothing yet. try another search."}</p>
      ) : (
        <ul className={styles.grid}>
          {items.map((item) => (
            <li key={item.id}>
              <ItemCard item={item} selected={worn.includes(item.id)} onToggle={toggle} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
