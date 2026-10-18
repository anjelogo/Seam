import clsx from "clsx";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { Link } from "react-router-dom";
import styles from "./TextLink.module.css";

export type TextLinkProps = {
  to?: string;
  href?: string;
  external?: boolean;
  icon?: ReactNode;
  className?: string;
  children: ReactNode;
} & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">;

export function TextLink({ to, href, external, icon, className, children, ...rest }: TextLinkProps) {
  const props = {
    className: clsx(styles.link, className),
    ...(external ? { target: "_blank", rel: "noopener noreferrer" } : {}),
    ...rest,
  };
  const content = (
    <>
      {icon}
      <span className={styles.text}>{children}</span>
    </>
  );
  return to === undefined ? (
    <a href={href} {...props}>
      {content}
    </a>
  ) : (
    <Link to={to} {...props}>
      {content}
    </Link>
  );
}
