import { formatMoney } from "@shared/types";
import clsx from "clsx";
import { useEffect, useId, useRef, useState } from "react";
import { TeeLoader } from "../../components/brand";
import { Button, IconButton, IconClose, TextLink } from "../../components/ui";
import type { UiItem } from "../../lib/viewmodel";
import { useLook, useStage, useWornItems } from "../../state";
import styles from "./CheckoutSheet.module.css";

const PAY_MS = 1200;

const usd = (cents: number) => formatMoney({ cents, currency: "USD" });

const close = () => useStage.getState().setCheckoutOpen(false);

export default function CheckoutSheet() {
  const open = useStage((s) => s.checkoutOpen);
  return open ? <Sheet /> : null;
}

function Sheet() {
  const worn = useWornItems();
  const listings = useLook((s) => s.items);
  const [step, setStep] = useState<"review" | "paying" | "done">("review");
  const [paid, setPaid] = useState<UiItem[]>([]);
  const [broken, setBroken] = useState<string[]>([]);
  const sheetRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const titleId = useId();

  const items = step === "review" ? worn : paid;
  const subtotal = items.reduce((sum, item) => sum + item.priceCents, 0);
  const shipping = items.flatMap((item) => listings[item.id]?.listing.shipping?.cents ?? []);
  const shippingCents = shipping.reduce((sum, cents) => sum + cents, 0);
  const total = subtotal + shippingCents;
  const done = step === "done";
  const title = done ? "you're all set." : "checkout";

  useEffect(() => titleRef.current?.focus(), [step]);

  useEffect(() => {
    if (step !== "paying") return;
    const timer = window.setTimeout(() => setStep("done"), PAY_MS);
    return () => window.clearTimeout(timer);
  }, [step]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") return close();
      if (event.key !== "Tab" || !sheetRef.current) return;
      const nodes = Array.from(sheetRef.current.querySelectorAll<HTMLElement>("a[href], button:not(:disabled)"));
      const last = nodes.length - 1;
      const at = nodes.indexOf(document.activeElement as HTMLElement);
      const wrap = event.shiftKey ? at <= 0 : at === -1 || at === last;
      if (!wrap) return;
      event.preventDefault();
      nodes[event.shiftKey ? last : 0]?.focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  const pay = () => {
    setPaid(worn);
    setStep("paying");
  };

  return (
    <div
      ref={sheetRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className={clsx("glass", "step-in", styles.sheet)}
    >
      <div className={styles.head}>
        <h2 key={title} ref={titleRef} id={titleId} tabIndex={-1} className={done ? "t-question" : "t-heading"}>
          {title}
        </h2>
        <IconButton aria-label="close" onClick={close}>
          <IconClose />
        </IconButton>
      </div>
      <ul className={styles.list}>
        {items.map((item) => (
          <li key={item.id} className={styles.row}>
            <span className={styles.photo}>
              {item.imageUrl !== "" && !broken.includes(item.imageUrl) && (
                <img
                  src={item.imageUrl}
                  alt={item.name}
                  draggable={false}
                  onError={() => setBroken((urls) => [...urls, item.imageUrl])}
                />
              )}
            </span>
            <span className={styles.info}>
              <span className={styles.name}>{item.name}</span>
              <span className="t-label">{item.size ? `${item.source} · size ${item.size}` : item.source}</span>
            </span>
            {done ? (
              <TextLink href={item.listingUrl} external>
                view listing ↗
              </TextLink>
            ) : (
              <span className={styles.price}>{item.priceLabel}</span>
            )}
          </li>
        ))}
      </ul>
      {!done && (
        <dl className={styles.totals}>
          <dt>subtotal</dt>
          <dd>{usd(subtotal)}</dd>
          {shipping.length > 0 && (
            <>
              <dt>shipping</dt>
              <dd>{usd(shippingCents)}</dd>
            </>
          )}
          <dt className={styles.total}>total</dt>
          <dd className={styles.total}>{usd(total)}</dd>
        </dl>
      )}
      {step === "review" && (
        <Button size="lg" disabled={items.length === 0} onClick={pay}>
          pay {usd(total)}
        </Button>
      )}
      {step === "paying" && <TeeLoader size={56} label="paying" />}
      {done && (
        <Button size="lg" onClick={close}>
          done
        </Button>
      )}
    </div>
  );
}
