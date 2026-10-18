# seam — "building your look" screen: full design spec

Version: v1.3 (Oct 18, 2026). Source of truth for this one screen. The rest of the app follows "seam · design spec v1" (Claude Docs). A working mockup of this screen is attached as `Loading.dc.html` (canvas board "03b building your look"); where this file and the mockup disagree, this file wins.

---

## 1. What this screen is

seam is a desktop web app (1280–1440 px wide, no mobile layout in v1). It turns a style prompt ("grunge 2000s", "cowboy", "quiet luxury") into a thrifted outfit and shows it on the user's own 3D avatar before they buy.

"building your look" is the loading screen between the end of onboarding and the avatar screen. Its job is to make the wait feel like visible work: the user watches seam search thrift stores, pick pieces that match their vibe, convert each piece into a 3D garment, and dress their avatar. It replaces any generic spinner.

### 1.1 Where it sits in the flow

```
splash → sign up / log in → onboarding (6 steps) → building your look → avatar
```

- **Enter from onboarding:** step 6 ("what style do you want to build today?") has the primary button "build my look". Pressing it goes here. The button is disabled until the style text box has text (the prompt is not skippable).
- **Enter from the avatar screen:** submitting a new vibe in the avatar's "style" tab (press Enter in the "describe a vibe" field) also plays this screen, then returns to the avatar with the new look.
- **Exit:** to the avatar screen, which opens on the "style" tab with the prompt pre-filled and the built outfit already worn.
  - Production: auto-advance 1.2 s after the last piece is ready. No button needed.
  - Mockup only: a primary button "see it on you" appears at the end because the canvas cannot auto-navigate.
- **No skip, no cancel, no other buttons** while it runs. (Global design rule: as few buttons as possible.)

---

## 2. Global visual language this screen must follow

These are app-wide rules; restated here so the screen can be built standalone.

### 2.1 Principles
1. All visible copy is lowercase. Only user-typed input keeps its case (the user's prompt may be shown as typed).
2. No descriptive helper text. Any explanation lives behind an info-icon tooltip (this screen needs none).
3. Look: glassy PS3 XMB (cross media bar). Deep blue gradient, flowing light ribbons, frosted-glass surfaces, white glow marks selection. Selection is never shown with a hue change, only by going solid white + glow.
4. Motion signals progress. Nothing moves without a reason; everything works with motion off.

### 2.2 Color tokens
| token | value | use |
|---|---|---|
| text | `#FFFFFF` | all text and icons |
| text-muted | `rgba(255,255,255,0.72–0.75)` | sub lines, labels |
| text-on-light | `#0A1F45` | text on white pills/buttons |
| line-faint | `rgba(255,255,255,0.2)` | empty progress tracks |
| bg gradient (blue theme, default) | `linear-gradient(170deg, #081631 0%, #15468A 55%, #0A2350 100%)` | page background |
| center glow | `radial-gradient(ellipse 70% 50% at 50% 60%, rgba(255,255,255,0.14), transparent 70%)` | over the gradient |

Other themes (same structure, swap the 3 stops): teal `#04222A · #0E6070 · #06343D`, violet `#150B32 · #4B2B8C · #20124A`, crimson `#22070F · #7E1B30 · #360B17`.

### 2.3 Glass surface (class `glass`)
```css
background: linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.05));
border: 1px solid rgba(255,255,255,0.24);
box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 20px 60px rgba(0,0,0,0.25);
backdrop-filter: blur(22px) saturate(140%);
```

### 2.4 Glow (selected / primary)
- White element: `background:#FFFFFF; color:#0A1F45; box-shadow: 0 0 18–40px rgba(255,255,255,0.45–0.6)`.
- Big text: `text-shadow: 0 0 36px rgba(255,255,255,0.45)`.

### 2.5 Type
- Family: **M PLUS Rounded 1c** (Google Fonts), weights 400/500/700/800; fallback `system-ui, sans-serif`.
- Phase title: `clamp(36px, 4.4vw, 56px)`, weight 800, line-height 1.05, glow text-shadow.
- Sub line: 17 px, weight 500, text-muted, `font-variant-numeric: tabular-nums` (numbers count up).
- Card name: 13 px / 700. Store tag on card: 11 px / 700. Chips: 14 px / 700. Wordmark "seam": 20 px / 800, letter-spacing −0.01em, `text-shadow: 0 0 18px rgba(255,255,255,0.5)`.

### 2.6 Shape
- Pills radius 999 px. Cards radius 16 px. Touch targets ≥ 44 px (chips here are 36 px tall, display only, not interactive).

### 2.7 Motion tokens
| token | value |
|---|---|
| ease-out (surge, phase fade) | `cubic-bezier(0.12, 0.7, 0.2, 1)` / `cubic-bezier(0.2, 0.7, 0.2, 1)` |
| ease-in-out (loader) | `cubic-bezier(0.6, 0, 0.3, 1)` |
| phase fade-in | 550 ms: opacity 0→1, translateY 12px→0 |
| card flip | 800 ms rotateY 0→180°, `cubic-bezier(0.2, 0.7, 0.2, 1)` |
| card opacity/scale changes | 500 ms |
| surge | 1.6 s |

---

## 3. Background (shared with every screen)

### 3.1 Ribbons
Two ribbons of thin glowing lines drift left forever, drawn in a 1200 × 800 coordinate space stretched to the screen.

- Ribbon A: 16 lines, base y 470, amplitude 95, phase 0, spread 3. Ribbon B: 10 lines, base y 560, amplitude 60, phase 2.2, spread 4.
- Line i at x: `y = base + sin(t + phase + 0.09·i) · (amp + (i − n/2) · spread) + sin(2t + 1.7·phase) · 0.22·amp`, with `t = 2π·x / 1200`. Draw x from 0 to 2400 so a 1200-unit shift loops seamlessly.
- Stroke white, 1–1.1 px, `drop-shadow(0 0 6px rgba(255,255,255,0.45))`. Opacity by distance from ribbon center: A core 0.55 / mid 0.26 / edge 0.10; B 0.36 / 0.18 / 0.08.
- Drift: A translates −1200 every 26 s, B every 40 s, linear, infinite.

### 3.2 Surge
- Fired on **every phase change** on this screen (4 times per run).
- Effect: one extra translateX(−1200) of both ribbons over 1.6 s with `cubic-bezier(0.12, 0.7, 0.2, 1)` (fast start, long settle), so it whips forward then settles back to the normal drift. A retrigger restarts it cleanly; never stack surges (the mockup alternates two identical keyframe names to restart).
- Production suggestion: one full-screen WebGL/three.js shader with `time` and `speed` uniforms; surge = `speed` jumps to ~8× and eases back to 1× over 1.6 s.

---

## 4. Layout (1280 × 800 reference)

Full-viewport page. Outer padding: 32 px top/bottom, `clamp(16px, 5vw, 64px)` left/right. Vertical stack with 24 px gaps:

1. **Header row** (space-between, centered vertically)
   - Left: wordmark `seam`.
   - Right: glass pill, min-height 40 px, padding 0 16 px, gap 8 px: muted label `your vibe` + the user's prompt in weight 700 (e.g. `grunge 2000s`).
2. **Phase block** (centered, text-align center), wrapped in `role="status" aria-live="polite"`.
   - Phase title (h1) and sub line, gap 6 px. Re-renders with the 550 ms fade-up whenever the phase changes.
3. **Main area** (flex-grow, centered both axes, gap 28 px). Holds, depending on phase:
   - The **listing grid** (phases 1–3).
   - The **store chips** row (phase 1 only), under the grid.
   - The **finale block** (phases 4–5).
4. **Progress bar** (bottom, centered): width `min(560px, 100%)`, 3 px tall, radius 2 px, track line-faint, fill white with `0 0 10px rgba(255,255,255,0.8)` glow. Fill = overall progress across phases 1–4 (reaches 100% when phase 5 starts).

---

## 5. Elements in detail

### 5.1 Listing grid
- CSS grid, 6 columns `repeat(6, minmax(0, 1fr))`, gap 14 px, max-width 1040 px, width 100%. 12 cards = 2 rows.
- Each card: aspect-ratio 3 / 4, `perspective: 900px` on the wrapper, inner flipper with `transform-style: preserve-3d`, two faces with `backface-visibility: hidden`, the back face pre-rotated 180°.

**Front face (the listing as found):**
- Background `rgba(255,255,255,0.06)`, border 1 px `rgba(255,255,255,0.18)`, radius 16 px, overflow hidden.
- Top 74%: diagonal stripe placeholder `repeating-linear-gradient(135deg, rgba(255,255,255,0.07) 0 10px, rgba(255,255,255,0.03) 10px 20px)` with the item's flat silhouette centered at 62% size, filled with the item's real color, stroke `rgba(0,0,0,0.25)` 1 px. In production this area shows the real listing photo instead (object-fit cover); keep the silhouette as the fallback.
- Store tag: top-left 8 px inset, pill, `rgba(6,14,32,0.6)` background, 11 px / 700, e.g. `ebay`.
- Bottom: item name, 13 px / 700, padding 8 × 10 px.

**Back face (the 3D build):**
- Glass surface, border `rgba(255,255,255,0.7)`, `box-shadow: inset 0 1px 0 rgba(255,255,255,0.5), 0 0 28px rgba(255,255,255,0.3)`. Content centered column, gap 14 px.
- The item's silhouette as the **2d→3d slice loader** at 72 px (see 5.4).
- While building: a progress bar, 70% wide, 4 px, track `rgba(255,255,255,0.2)`, white fill with glow, width = build progress.
- When done: replace the bar with a white pill chip, 12 px / 700, `#0A1F45` text, check icon + `ready`, glow `0 0 14px rgba(255,255,255,0.6)`.

**Card states:**
| state | opacity | scale | flip | front border |
|---|---|---|---|---|
| not yet appeared | 0 | 0.92 | front | default |
| found (phase 1) | 1 | 1.0 | front | default |
| picked, phase 2 | 1 | 1.06 | front | white + `0 0 28px rgba(255,255,255,0.45)` glow |
| not picked, phase 2 | 0.18 | 0.88 | front | default |
| not picked, phase 3 | 0 | 0.88 | front | default |
| picked, waiting to build (phase 3) | 1 | 1.04 | front | default |
| picked, building | 1 | 1.04 | back, bar filling | — |
| picked, ready | 1 | 1.04 | back, `ready` chip | — |
| picked, failed | 1 | 1.04 | flips back to front, front shows a small `2d only` pill (same style as store tag) | default |

### 5.2 Store chips (phase 1)
- Row, wrap, centered, gap 8 px. Five glass pills, min-height 36 px, padding 0 16 px, 14 px / 700: `ebay`, `depop`, `poshmark`, `thredup`, `grailed`.
- While searching, chips light up in turn (solid white, `#0A1F45` text, glow) to show which source is being queried; 200 ms transitions. Mockup cycles them on a pattern; production lights a chip while its source request is in flight.
- Hidden after phase 1.

### 5.3 Finale block (phases 4–5)
Replaces the grid. Centered column, gap 28 px, fades up on entry.
- The big **tee slice loader** at 180 px (6 slices), animating during phase 4 ("dressing you"); in phase 5 the animation stops and the tee sits flat (the logo state).
- Row of 4 glass chips (min-height 36 px, padding 0 14 px, 14 px / 700), each a white check icon + the picked item's name.
- Phase 5, mockup only: primary button `see it on you` (white pill, min-height 56 px, min-width 200 px, 18 px / 700, `#0A1F45`, glow `0 0 40px rgba(255,255,255,0.6)`) linking to the avatar. Production auto-advances instead.

### 5.4 The 2d→3d slice loader (brand loader)
- N copies of the item's silhouette path (viewBox 0 0 64 64) stacked in depth. Front slice = the solid logo state (stroke 4, fill white 18–20%); back slices are thinner outlines fading in opacity; the last slice has a faint fill (12%).
  - 72 px card loader: 4 slices (i = 3 back … 0 front): stroke opacity 0.3 / 0.45 / 0.65 / 1.0.
  - 180 px finale loader: 6 slices: 0.25 / 0.32 / 0.42 / 0.52 / 0.65 / 1.0.
- Each slice: `transform: translateZ(calc(var(--d) * var(--i) * -1))`, with `--d` a registered length (`@property --d { syntax:'<length>'; inherits:true; initial-value:0px }`).
- Container: `perspective: 4em`, `filter: drop-shadow(0 0 0.12em rgba(255,255,255,0.55))`, sized by font-size (1em square).
- Loop 2.8 s, `cubic-bezier(0.6, 0, 0.3, 1)`: 0–12% flat (`--d:0`) · 34% slices spread (`--d:0.03em`) · 60% `rotateY(-42deg) rotateX(14deg)` · 80% `rotateY(32deg) rotateX(8deg)` · 100% flat again.
- Production option: an extruded three.js shape with an animated depth uniform.

### 5.5 Silhouette paths (viewBox 0 0 64 64)
| key | used for | path |
|---|---|---|
| tee | tees, tops | `M22 10 L14 14 L6 24 L14 30 L18 26 L18 54 L46 54 L46 26 L50 30 L58 24 L50 14 L42 10 C 40 15, 36 17, 32 17 C 28 17, 24 15, 22 10 Z` |
| sleeve | jackets, hoodies, long sleeves | `M22 10 L12 14 L4 44 L12 46 L18 28 L18 56 L46 56 L46 28 L52 46 L60 44 L52 14 L42 10 C 40 15, 36 17, 32 17 C 28 17, 24 15, 22 10 Z` |
| pants | pants, jeans | `M18 8 L46 8 L50 56 L37 56 L32 24 L27 56 L14 56 Z` |
| boot | boots | `M20 8 L36 8 L36 38 L54 46 L56 56 L18 56 L18 30 Z` |
| skirt | skirts | `M20 14 L44 14 L52 50 L12 50 Z` |
| shoe | sneakers, low shoes | `M8 40 C 8 30, 22 28, 30 34 L56 40 L56 50 L8 50 Z` |
| belt | belts | `M6 27 L58 27 L58 37 L6 37 Z M28 25 L36 25 L36 39 L28 39 Z` |
| wallet | small accessories | `M14 18 L50 18 L50 46 L14 46 Z` |

The tee path is also the seam logo mark.

---

## 6. Phases, copy and timing

### 6.1 Copy (exact strings, lowercase)
| # | title | sub line |
|---|---|---|
| 1 | `searching every store` | `{n} listings scanned` (n counts up) |
| 2 | `picking your pieces` | `{k} matches for your vibe` |
| 3 | `building them in 3d` | `{r} of {k} ready` |
| 4 | `dressing you` | `fitting {k} pieces to your avatar` |
| 5 | `your look is ready.` | `{k} pieces · {s} stores` |

### 6.2 Mockup timeline (seconds; used when there is no backend, and as the demo pacing)
| time | event |
|---|---|
| 0.0 | phase 1 starts. Cards pop in one at a time: card i fades/scales in over 0.3 s starting at 0.15 + 0.22·i. Listing counter counts 0 → 312 over 3.2 s. Store chips cycle. |
| 3.2 | phase 2 + surge. 4 picks glow and scale to 1.06; others dim to 0.18 / scale 0.88. |
| 5.0 | phase 3 + surge. Non-picks fade to 0. Pick k (k = 0..3) flips at 5.0 + 0.8·k, builds for 2.2 s (bar 0→100%), then shows `ready`. Sub line counts ready pieces. |
| 9.6 | phase 4 + surge. Grid gives way to the finale block; big loader animates. |
| 11.4 | phase 5 + surge. Loader settles flat; production auto-advances 1.2 s later (mockup shows the button). |
| 15.5 | mockup only: loops back to 0 (a `loop` toggle turns this off). |

### 6.3 Production timing (driven by the backend, not a timer)
- Phase 1 runs while store searches are in flight. Cards appear as listings arrive (cap the grid at 12; take the first/highest-ranked). Counter shows the real number of listings scanned. Hold phase 1 for at least 1.5 s so it reads, even if results are instant.
- Phase 2 starts when the LLM/ranker returns the picked items (k, normally 4). Hold at least 1.2 s.
- Phase 3: each picked card flips when its 3D job starts and shows `ready` when its GLB URL arrives. If the backend reports progress, drive the bar from it; otherwise animate the bar toward 90% over the expected duration and jump to 100% on completion.
- Expected duration: TRELLIS.2 (image-to-3D) at 512³ is ~3 s per item on an H100 (~17 s at 1024³). 4 items in sequence ≈ 12 s at 512³. Design for 10–30 s total. Run jobs in parallel if GPU memory allows; the stagger then comes from arrival order.
- Phase 4 starts when every picked item is ready or failed, and runs while garments are fitted to the avatar (load GLBs, attach to body). Hold at least 1.2 s.
- Phase 5, then auto-advance after 1.2 s.

### 6.4 Failure handling
- A single item fails to convert: its card flips back to the front and shows a `2d only` pill. Count it as done for the "ready" total. The look still opens; that item is available as a photo in the avatar's inventory and has no hotspot on the avatar.
- All items fail, or search returns nothing: stay calm, no red text. Title `nothing fit that vibe.`, sub line empty, and show the style text box again pre-filled with the prompt so the user can edit and press Enter. (Open for the team to confirm.)
- Network timeout (> 60 s total): same as above with the title `that took too long.`

---

## 7. Data contract (suggested)

```ts
type LookJobEvent =
  | { type: 'search_started'; sources: string[] }                 // lights store chips
  | { type: 'source_done'; source: string }
  | { type: 'listing'; item: Listing; scanned: number }            // phase 1 card + counter
  | { type: 'picked'; itemIds: string[] }                          // phase 2
  | { type: 'model_started'; itemId: string }                      // phase 3 flip
  | { type: 'model_progress'; itemId: string; progress: number }   // 0..1, optional
  | { type: 'model_ready'; itemId: string; modelUrl: string; anchor: [number, number, number] }
  | { type: 'model_failed'; itemId: string }
  | { type: 'fitting_started' }                                    // phase 4
  | { type: 'look_ready'; look: Look };                            // phase 5 → avatar

type Listing = {
  id: string; name: string;
  category: 'tops' | 'bottoms' | 'outerwear' | 'shoes' | 'accessories';
  silhouette: 'tee' | 'sleeve' | 'pants' | 'boot' | 'skirt' | 'shoe' | 'belt' | 'wallet';
  source: string;            // ebay, depop, poshmark, thredup, grailed
  price: number; size?: string;
  imageUrl: string; listingUrl: string;
  color?: string;            // dominant color for the fallback silhouette
};

type Look = { prompt: string; itemIds: string[] };
```
Deliver events over SSE or a WebSocket. The screen is a pure function of the event log plus the minimum-hold rules in 6.3.

---

## 8. Mock data used in the mockup

Prompt: `grunge 2000s`. 12 listings in grid order (★ = picked, pick order in brackets):

| # | name | store | silhouette | color |
|---|---|---|---|---|
| 1 | mesh top | depop | tee | #2B2B33 |
| 2 | ★ faded band tee [0] | ebay | tee | #A8443D |
| 3 | studded belt | grailed | belt | #26262C |
| 4 | ★ washed denim jacket [1] | depop | sleeve | #5A79A8 |
| 5 | flared jeans | thredup | pants | #7891B8 |
| 6 | zip hoodie | poshmark | sleeve | #55505E |
| 7 | plaid mini skirt | thredup | skirt | #8A3B44 |
| 8 | chain wallet | ebay | wallet | #3A3A42 |
| 9 | ★ black cargo pants [2] | poshmark | pants | #2A2C30 |
| 10 | skate shoes | grailed | shoe | #E8E4DA |
| 11 | ★ platform boots [3] | ebay | boot | #1E1E22 |
| 12 | striped long sleeve | depop | sleeve | #C9C2B3 |

The 4 picks match the avatar screen's default worn outfit (tee, jacket, cargo pants, boots), so the hand-off is continuous. "312 listings scanned" and all items are placeholders.

---

## 9. Accessibility and reduced motion

- Phase title + sub line live in `role="status" aria-live="polite"` so screen readers hear each phase.
- Decorative SVGs (silhouettes, ribbons, loaders) are `aria-hidden="true"`; the finale loader has `role="img" aria-label="seam"`.
- Real `<a>`/`<button>` elements only; visible focus ring `2px solid #FFFFFF`, offset 3 px.
- Contrast: white on the gradient passes 4.5:1; keep muted text ≥ 72% white.
- `prefers-reduced-motion: reduce`: no ribbon drift, no surge, no phase fades, no loader animation (slices stay flat), card flips become instant swaps. Phases and text still advance normally.

---

## 10. Acceptance checklist

- [ ] Onboarding "build my look" and avatar style-tab Enter both open this screen with the user's prompt shown in the header pill.
- [ ] All copy lowercase and matches 6.1 exactly; no helper text; no buttons while running (except the mockup's final button).
- [ ] Ribbons drift; a surge fires on each of the 4 phase changes.
- [ ] Phase 1: cards appear as listings arrive, counter counts, store chips light while their source is queried.
- [ ] Phase 2: exactly the picked cards glow/grow; the rest dim, then disappear in phase 3.
- [ ] Phase 3: each pick flips on model start, bar fills, `ready` chip on GLB arrival; failures show `2d only`.
- [ ] Phase 4: finale loader + chips of picked names while fitting.
- [ ] Phase 5: auto-advance to avatar after 1.2 s; avatar opens on the style tab with the outfit worn.
- [ ] Minimum holds (1.5 / 1.2 / 1.2 s) keep fast runs readable.
- [ ] Reduced motion disables decorative animation without breaking progress.
- [ ] Works at 1280 and 1440 px wide; nothing overflows.

---

## 11. Files

- `Loading.dc.html`: the canvas mockup of this screen (a Design Component file; the markup + `renderVals()` logic show the exact states and timeline). Reference only, not production code.
- Related screens on the same canvas: `Onboarding.dc.html` (step 6 links here), `Avatar.dc.html` (destination).
