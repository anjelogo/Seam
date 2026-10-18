# /web — Anjelo

Vite + React + TS. R3F, drei, zustand, Tailwind installed, unused.
UI follows .agents/DESIGN_SPEC.md exactly. Do not invent beyond it.
Types only from "@shared/types". Never redefine API types locally.
Calls /api via /api proxy and /gen3d via /gen3d proxy, through src/lib/api.ts only.
