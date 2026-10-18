import clsx from "clsx";
import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import styles from "./IconButton.module.css";

export type IconButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  "aria-label": string;
  variant?: "ghost" | "glass";
  size?: 44 | 48;
};

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { variant = "ghost", size = 44, type = "button", className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={clsx(
        styles.button,
        size === 48 ? styles.size48 : styles.size44,
        variant === "glass" && "glass",
        className,
      )}
      {...rest}
    />
  );
});
