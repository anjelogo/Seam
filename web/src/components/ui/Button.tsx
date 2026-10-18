import clsx from "clsx";
import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { Link } from "react-router-dom";
import type { LinkProps } from "react-router-dom";
import styles from "./Button.module.css";

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  size?: "md" | "lg";
  to?: string;
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { size = "md", to, type = "button", disabled, className, ...rest },
  ref,
) {
  const classes = clsx(styles.button, styles[size], className);
  if (to !== undefined && !disabled) {
    const linkProps = rest as unknown as Omit<LinkProps, "to">;
    return <Link to={to} className={classes} {...linkProps} />;
  }
  return <button ref={ref} type={type} disabled={disabled} className={classes} {...rest} />;
});
