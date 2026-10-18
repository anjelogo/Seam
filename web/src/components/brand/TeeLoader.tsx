import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "../../lib/motion";
import { attachLoader, webglUnavailable } from "./loaderRenderer";
import styles from "./TeeLoader.module.css";
import { TeeMark } from "./TeeMark";

export type TeeLoaderProps = {
  size?: number;
  label?: string;
  className?: string;
};

export function TeeLoader({ size = 72, label = "loading", className }: TeeLoaderProps) {
  const reduced = useReducedMotion();
  const [failed, setFailed] = useState(webglUnavailable);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animated = !reduced && !failed;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!animated || !canvas) return;
    return attachLoader(canvas, size, () => setFailed(true));
  }, [animated, size]);

  return (
    <span role="status" className={clsx(styles.loader, className)} style={{ width: size, height: size }}>
      {animated ? (
        <canvas ref={canvasRef} className={styles.canvas} aria-hidden="true" />
      ) : (
        <TeeMark size={size} />
      )}
      <span className="sr-only">{label}</span>
    </span>
  );
}
