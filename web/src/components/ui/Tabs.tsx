import clsx from "clsx";
import { useRef } from "react";
import type { KeyboardEvent } from "react";
import styles from "./Tabs.module.css";

export type TabOption = { value: string; label: string };

export type TabsProps = {
  tabs: readonly TabOption[];
  value: string;
  onChange: (value: string) => void;
  label: string;
  idBase: string;
  className?: string;
};

export const tabId = (idBase: string, value: string) => `${idBase}-tab-${value}`;

export const panelId = (idBase: string, value: string) => `${idBase}-panel-${value}`;

export function Tabs({ tabs, value, onChange, label, idBase, className }: TabsProps) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const active = tabs.some((tab) => tab.value === value) ? value : tabs[0]?.value;

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = tabs.length - 1;
    let next: number;
    if (event.key === "ArrowRight") next = index === last ? 0 : index + 1;
    else if (event.key === "ArrowLeft") next = index === 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else return;
    event.preventDefault();
    buttons.current[next]?.focus();
    if (tabs[next].value !== value) onChange(tabs[next].value);
  };

  return (
    <div role="tablist" aria-label={label} className={clsx("glass", styles.tabs, className)}>
      {tabs.map((tab, index) => {
        const selected = tab.value === active;
        return (
          <button
            key={tab.value}
            ref={(node) => {
              buttons.current[index] = node;
            }}
            type="button"
            role="tab"
            id={tabId(idBase, tab.value)}
            aria-selected={selected}
            aria-controls={panelId(idBase, tab.value)}
            tabIndex={selected ? 0 : -1}
            className={clsx(styles.tab, selected && styles.selected)}
            onClick={() => {
              if (tab.value !== value) onChange(tab.value);
            }}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
