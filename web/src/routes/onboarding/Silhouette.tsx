import type { BodyBase } from "@shared/types";

const FIGURES: Record<BodyBase, { head: number; body: string }> = {
  masc: {
    head: 15,
    body: "M66 36.75 L66 44 C70 48 80 49 88 51 C95 53 98 58 98.5 66 L104 126 C105 134 103 140 99.5 140 C96.5 140 95.5 136 95 129 L88.5 80 C87 92 84.5 104 84.5 116 C84.5 122 85.5 128 86 134 C86.5 160 82 186 79.5 204 C80 209 78 212 74 212 L68 212 C66.5 212 66 210 66 207 C66 190 64.5 164 63 148 C62.5 144 61.5 142 60 142 C58.5 142 57.5 144 57 148 C55.5 164 54 190 54 207 C54 210 53.5 212 52 212 L46 212 C42 212 40 209 40.5 204 C38 186 33.5 160 34 134 C34.5 128 35.5 122 35.5 116 C35.5 104 33 92 31.5 80 L25 129 C24.5 136 23.5 140 20.5 140 C17 140 15 134 16 126 L21.5 66 C22 58 25 53 32 51 C40 49 50 48 54 44 L54 36.75",
  },
  fem: {
    head: 14,
    body: "M65 36.08 L65 43 C68.5 47 76 48 83 50 C89 52 92 57 92.5 64 L101.5 124 C102.5 132 100.5 138 97 138 C94 138 93 134 92.5 127 L84 80 C82.5 90 79 99 79 108 C79 118 88.5 126 88.5 140 C88.5 162 79.5 186 76.5 204 C77 209 75 212 71.5 212 L67.5 212 C66 212 65.5 210 65.5 207 C65.5 190 64 168 62.5 154 C62 150 61.5 148 60 148 C58.5 148 58 150 57.5 154 C56 168 54.5 190 54.5 207 C54.5 210 54 212 52.5 212 L48.5 212 C45 212 43 209 43.5 204 C40.5 186 31.5 162 31.5 140 C31.5 126 41 118 41 108 C41 99 37.5 90 36 80 L27.5 127 C27 134 26 138 23 138 C19.5 138 17.5 132 18.5 124 L27.5 64 C28 57 31 52 37 50 C44 48 51.5 47 55 43 L55 36.08",
  },
};

export type SilhouetteProps = {
  base: BodyBase;
  height?: number;
};

export function Silhouette({ base, height = 172 }: SilhouetteProps) {
  const { head, body } = FIGURES[base];
  return (
    <svg
      width={(height * 120) / 220}
      height={height}
      viewBox="0 0 120 220"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx={60} cy={23} r={head} />
      <path d={body} />
    </svg>
  );
}
