import { easeOut, prefersReducedMotion } from "../../lib/motion";

type SurgeSample = { offset: number; glow: number; speed: number };

const SHIFT = 1200;
const DRIFT_RATE = SHIFT / 26;
const MAX_SPEED = 8;
const REST_GLOW = 0.6;
const GLOW_RISE = 0.4;
const DEFAULT_MS = 1600;
const SLOPE_STEP = 0.002;

export const REST: Readonly<SurgeSample> = { offset: 0, glow: REST_GLOW, speed: 1 };

const surge = { start: 0, duration: 0, carry: 0, glowCarry: 0 };
const sample: SurgeSample = { ...REST };

export function sampleSurge(now: number): SurgeSample {
  const p = surge.duration > 0 ? Math.min(Math.max((now - surge.start) / surge.duration, 0), 1) : 1;
  if (p >= 1) {
    sample.offset = surge.carry;
    sample.glow = REST_GLOW;
    sample.speed = 1;
    return sample;
  }
  const lo = Math.max(p - SLOPE_STEP, 0);
  const hi = Math.min(p + SLOPE_STEP, 1);
  const rate = (SHIFT * (easeOut(hi) - easeOut(lo))) / (hi - lo) / (surge.duration / 1000);
  sample.offset = (surge.carry + SHIFT * easeOut(p)) % SHIFT;
  sample.glow = REST_GLOW + Math.max(GLOW_RISE * Math.sin(Math.PI * p), surge.glowCarry * (1 - p));
  sample.speed = Math.min(1 + rate / DRIFT_RATE, MAX_SPEED);
  return sample;
}

export function fireSurge(durationMs = DEFAULT_MS) {
  if (prefersReducedMotion()) return;
  const now = performance.now();
  // fold the running surge in so a restart never jumps
  const current = sampleSurge(now);
  surge.carry = current.offset;
  surge.glowCarry = current.glow - REST_GLOW;
  surge.start = now;
  surge.duration = durationMs > 0 ? durationMs : DEFAULT_MS;
}

export function useSurge(): (durationMs?: number) => void {
  return fireSurge;
}
