import clsx from "clsx";
import { useId } from "react";
import type { ReactNode } from "react";
import { TeeLoader, Wordmark } from "../../components/brand";
import { Button, IconChevronLeft, TextLink } from "../../components/ui";
import styles from "./AuthFrame.module.css";
import type { AuthForm } from "./useAuthForm";

export type AuthFrameProps = {
  title: string;
  action: string;
  ready: boolean;
  form: AuthForm;
  link: { to: string; label: string };
  children: ReactNode;
};

export function AuthFrame({ title, action, ready, form, link, children }: AuthFrameProps) {
  const titleId = useId();
  const shake = form.shake === 0 ? undefined : form.shake % 2 ? styles.shakeOdd : styles.shakeEven;

  // step-in sits on the glass itself: a fading ancestor switches off its backdrop blur
  return (
    <div className={styles.frame}>
      <header className={clsx(styles.bar, "step-in")}>
        <TextLink to="/" icon={<IconChevronLeft />}>
          back
        </TextLink>
        <Wordmark size={28} />
      </header>
      <main className={clsx(styles.main, shake)}>
        <form
          noValidate
          aria-labelledby={titleId}
          onSubmit={form.onSubmit}
          className={clsx("glass", "step-in", styles.card)}
        >
          <h1 id={titleId} className={styles.title}>
            {title}
          </h1>
          <div className={styles.fields}>{children}</div>
          <div className={styles.actions}>
            <Button type="submit" size="lg" disabled={!ready}>
              {action}
            </Button>
            {form.pending ? <TeeLoader size={24} /> : null}
            <TextLink to={link.to} className={styles.link}>
              {link.label}
            </TextLink>
          </div>
          <p role="alert" className="sr-only">
            {form.error?.message}
          </p>
        </form>
      </main>
    </div>
  );
}
