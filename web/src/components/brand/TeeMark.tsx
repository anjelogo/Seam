import { TEE_PATH } from "./tee";

export type TeeMarkProps = {
  size?: number;
  title?: string;
  className?: string;
};

export function TeeMark({ size = 64, title, className }: TeeMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role={title ? "img" : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
      focusable="false"
      className={className}
    >
      <path
        d={TEE_PATH}
        fill="rgba(255, 255, 255, 0.18)"
        stroke="#fff"
        strokeWidth={4}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
