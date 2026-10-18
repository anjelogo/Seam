import clsx from "clsx";
import { useEffect, useState } from "react";
import type { ComponentType } from "react";
import { useLocation } from "react-router-dom";
import { fireSurge } from "../components/bg";
import { Wordmark } from "../components/brand";
import { Panel, panelId, tabId, Tabs } from "../components/ui";
import { useReducedMotion } from "../lib/motion";
import { useInventory, useLook } from "../state";
import styles from "./avatar/Avatar.module.css";
import BodyPane from "./avatar/BodyPane";
import CheckoutPill from "./avatar/CheckoutPill";
import CheckoutSheet from "./avatar/CheckoutSheet";
import DetailCard from "./avatar/DetailCard";
import InventoryPane from "./avatar/InventoryPane";
import Stage from "./avatar/Stage";
import StylePane from "./avatar/StylePane";

const TABS = [
  { value: "inventory", label: "inventory" },
  { value: "body", label: "body" },
  { value: "style", label: "style" },
] as const;

type Tab = (typeof TABS)[number]["value"];

const PANES: Record<Tab, ComponentType> = { inventory: InventoryPane, body: BodyPane, style: StylePane };

const ID = "avatar";
const SURGE_MS = 1400;

const isTab = (value: unknown): value is Tab => TABS.some((tab) => tab.value === value);

export default function Avatar() {
  const location = useLocation();
  const reduced = useReducedMotion();
  const [tab, setTab] = useState<Tab>(() => {
    const initial = (location.state as { tab?: unknown } | null)?.tab;
    return isTab(initial) ? initial : "inventory";
  });
  const Pane = PANES[tab];

  useEffect(() => {
    useInventory.getState().search("", true);
    const look = useLook.getState();
    if (look.worn.length) look.ensureAssets();
  }, []);

  const changeTab = (next: string) => {
    if (!isTab(next)) return;
    fireSurge(SURGE_MS);
    setTab(next);
  };

  return (
    <div className={styles.frame}>
      <header className={clsx(styles.bar, "step-in")}>
        <Wordmark size={28} />
      </header>
      <main className={styles.body}>
        <Panel className={clsx(styles.panel, "step-in")}>
          <Tabs tabs={TABS} value={tab} onChange={changeTab} label="avatar panel" idBase={ID} />
          <div
            key={tab}
            role="tabpanel"
            id={panelId(ID, tab)}
            aria-labelledby={tabId(ID, tab)}
            className={clsx(styles.pane, !reduced && "step-in")}
          >
            <Pane />
          </div>
        </Panel>
        <div className={styles.stage}>
          <div className={styles.canvas}>
            <Stage />
          </div>
          <div className={styles.detail}>
            <DetailCard />
          </div>
          <div className={styles.checkout}>
            <CheckoutPill />
          </div>
          <CheckoutSheet />
        </div>
      </main>
    </div>
  );
}
