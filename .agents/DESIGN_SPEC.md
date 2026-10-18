seam · design spec v1
Oct 17, 2026 · @anjelo
Overview
seam turns a style prompt into a thrifted outfit and shows it on your own 3D avatar before you buy. This spec locks the v1 frontend look and behavior for the DubHacks 2026 build; edit any section and hand the doc to the build agent.
Tagline: thrift a vibe, try it in 3d. seamless.
Live reference: the seam screens design canvas (splash, sign up, onboarding, avatar, logo + wordmark boards). Where this doc and the canvas disagree, this doc wins.
Principles
1. all lowercase. Every heading, label, button, tag and tooltip is lowercase. Only user-typed input keeps its case.
2. few buttons. Prefer direct manipulation: tap the thing, drag the thing, press enter. A screen has at most one primary button.
3. no descriptive text. Explanations live behind an info icon tooltip, never as helper lines under inputs.
4. glassy PS3 XMB. Deep blue gradient, flowing light ribbons, frosted-glass surfaces, white glow for selection.
5. one question per screen in onboarding, each with the input that fits it (slider, number, radio cards, swatches, pills, text box). Never a chat box, except the final style prompt.
Platform: desktop web only, 1280–1440 px wide. No mobile layout in v1.
Brand
The mark is a plain t-shirt outline (concept 10 on the canvas); its loader extrudes the flat tee into 3D and back, echoing the image-to-3D pipeline.
Element
Spec
Name
seam, always lowercase
Tagline
thrift a vibe, try it in 3d. seamless. ("seamless." in weight 800 with a soft white glow)
Short line
thrift, seamlessly. (under the logo where space is tight)
Mark
tee outline, 64×64 viewBox, stroke #FFFFFF 4 units, round joins, fill #FFFFFF at 18%
Wordmark
"seam" in M PLUS Rounded 1c 800, letter-spacing −0.04em, white with 0 0 48px glow at hero size
Lockup
mark left of wordmark, mark height ≈ 0.86× font size, gap ≈ 0.15× font size
App icon
mark on a 30%-radius tile, gradient #15468A → #081631; light variant: #0A1F45 mark on #F2F5FA
Tee path (viewBox 0 0 64 64):
M22 10 L14 14 L6 24 L14 30 L18 26 L18 54 L46 54 L46 26 L50 30 L58 24 L50 14 L42 10 C 40 15, 36 17, 32 17 C 28 17, 24 15, 22 10 Z
Loader (2d → 3d → 2d)
• 8 copies of the tee path stacked in depth; front slice is the logo, back slices are thinner outlines fading from 65% to 22% opacity, last slice fill 12%.
• Loop 2.8 s, cubic-bezier(0.6, 0, 0.3, 1): 0–12% flat · 34% slices spread to depth · 60% turned rotateY −42° rotateX 14° · 80% rotateY 32° rotateX 8° · 100% flat again.
• Small sizes drop slices: 72 px → 6, 40 px → 4, 24 px → 3.
• Reduced motion: show the flat mark, no animation.
• Production: build as an extruded three.js shape with an animated depth uniform rather than stacked SVGs.
Assets delivered: seam-devpost-thumbnail.png (1500×1000), seam-logo-square.png and seam-logo-square-wordmark.png (1024×1024).
Design tokens
Everything is white on a deep blue gradient; selection is shown by turning an element solid white with a glow, never by a hue change.
Color
Token
Value
Use
text
#FFFFFF
all text and icons
text-muted
rgba(255,255,255,0.72–0.75)
labels, secondary info
text-on-light
#0A1F45
text on white buttons and selected pills
line
rgba(255,255,255,0.55)
underline fields, guide lines
line-faint
rgba(255,255,255,0.2)
dividers, empty progress bars
tooltip-bg
rgba(6,14,32,0.92) + 1px rgba(255,255,255,0.2)
tooltips
Themes (background gradient, 170°, stops 0% / 55% / 100%)
Theme
Stops
Default
blue
#081631 · #15468A · #0A2350
yes
teal
#04222A · #0E6070 · #06343D

violet
#150B32 · #4B2B8C · #20124A

crimson
#22070F · #7E1B30 · #360B17

Add a radial white glow over the gradient: ellipse 70% × 50% centered around 50% / 62%, rgba(255,255,255,0.12–0.2) fading to transparent.
Glass surface
background: linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.05));
border: 1px solid rgba(255,255,255,0.24);
box-shadow: inset 0 1px 0 rgba(255,255,255,0.35), 0 20px 60px rgba(0,0,0,0.25);
backdrop-filter: blur(22px) saturate(140%);
Glow (selection and primary)
• Primary button / selected pill: background #FFFFFF, color #0A1F45, box-shadow 0 0 18–32px rgba(255,255,255,0.45–0.6).
• Big numbers and the wordmark: text-shadow 0 0 40–48px rgba(255,255,255,0.45).
Type
• Family: M PLUS Rounded 1c (Google Fonts), weights 400 / 500 / 700 / 800. Fallback system-ui.
• Scale: question 40–60 px / 800 · big value 104 px / 800 · panel heading 18–20 px / 700 · body 15–17 px · label 12–13 px / 700, letter-spacing 0.14em · wordmark hero 96–176 px / 800, −0.04em.
Shape and spacing
• Radius: pills 999 px · cards 18–26 px · panels 26 px · sign-up card 28 px · tooltips 12 px.
• Spacing base 4 px; common gaps 6 / 12 / 16 / 20 / 28 / 48 px. Page gutters clamp(16px, 5vw, 64px).
• Touch targets ≥ 44 × 44 px.
Motion
Token
Value
ease-out
cubic-bezier(0.12, 0.7, 0.2, 1) (surge, step change)
ease-in-out
cubic-bezier(0.6, 0, 0.3, 1) (loader)
fast
150–250 ms (hover, selection, tooltip fade)
step-in
550 ms fade + 14 px rise
surge
1.6 s onboarding · 1.4 s avatar
Animated background
Every screen sits on the theme gradient with two ribbons of thin glowing lines drifting left; navigating fires a one-shot surge that whips them forward and settles back.
Ribbons
• Two ribbons: A = 16 lines, base y 440, amplitude 95, phase 0, spread 3 · B = 10 lines, base y 520, amplitude 60, phase 2.2, spread 4 (in a 1200 × 800 space stretched to the screen).
• Line i at x: y = base + sin(t + phase + 0.09·i) · (amp + (i − n/2) · spread) + sin(2t + 1.7·phase) · 0.22·amp, with t = 2π·x / 1200. The curve repeats every 1200 units, so a 1200-unit shift loops seamlessly.
• Lines are white, 1–1.1 px, with a 6 px white glow. Opacity by distance from the ribbon center: core 0.55, mid 0.26, edge 0.10 (ribbon B: 0.36 / 0.18 / 0.08).
• Drift: A loops every 26 s, B every 40 s, linear.
Surge
• Trigger: onboarding next/back, avatar tab change, style prompt submit.
• Effect: an extra 1200-unit shift over the surge duration with ease-out (fast start, long settle), plus the center glow pulsing from 0.6 to 1.0 opacity and back.
• Retrigger restarts it cleanly; never stack surges.
Production: render as a full-screen WebGL / three.js shader with time and speed uniforms; the surge is speed jumping to ~8× and easing back to 1× over the surge duration. Reduced motion: static ribbons, no surge.
Components
Twelve reusable pieces cover every screen; build them once and compose.
Component
Look
Behavior
primary button
white pill, #0A1F45 text 16–18 px / 700, min 44–56 px tall, glow
one per screen at most
text link
white 16–18 px / 700, underlined, 44 px hit area
secondary actions (log in, view listing)
icon button
44–48 px circle, transparent or glass, white stroke icon
needs aria-label
underline field
transparent, 1.5 px bottom border at 55% white, 20–24 px text; focus → solid white border
label above in label style
glass text box
glass surface, radius 24 px, 28 px text, 3 rows, no resize
onboarding style prompt only
pill group
glass track, pills turn white + glow when selected
real radio inputs, keyboard navigable
info tooltip
44 px info icon (circle + i, 70% white) next to a label; dark box, 13 px, max 240–280 px wide
shows on hover and focus; holds all explanatory text
item card
glass-dark card, square photo, store + [$] line, name
the whole card is the button: tap toggles wearing; selected = white border + glow + white check badge top right
hotspot node
16 px white ring dot with slow pulse; 1 px glowing guide line to a glass label pill (category)
tap opens the detail card; selected = filled dot, white label
detail card
glass, radius 22 px, 264 px wide, top right of stage
category · store, photo, name, size, price, "view listing ↗" link, one "take off" button, close icon
checkout pill
glass pill, bottom right of stage: "N items · $total" + white "check out" button
opens an in-app checkout sheet, mocked in v1 (item list, total, fake pay button, success state); disabled when nothing is worn
progress bar
6 segments, 4 px, done = white + glow, todo = 20% white
onboarding only
Screens
Four screens in one straight flow: splash → sign up → onboarding → avatar; log in returns to avatar.
1 · splash
• Lockup: tee mark + "seam" at hero size (96–176 px), wordmark glow.
• Tagline under it: thrift a vibe, try it in 3d. seamless.
• One primary button: sign up → sign up. One text link: log in → log in screen.
• Decorative glass hang tag on the right (item / size / source, "tried on" stamp); hidden below 700 px width.
2 · sign up
• Back link (chevron + back) top left, small "seam" wordmark top right.
• Centered glass card, max 480 px: heading "make an account."; underline fields name, email, password (no placeholders).
• Password rule "8 or more characters." lives in an info tooltip on its label.
• Primary button: continue → onboarding. Text link: i have an account → log in screen.
2b · log in
• Same frame as sign up: back link, glass card, heading "welcome back.", underline fields email and password.
• Primary button: log in → avatar. Text link: make an account → sign up.
• Mocked until the backend supports auth: any non-empty email + password logs in; keep the call behind one login(email, password) function so the real endpoint drops in later.
• Wrong-credentials state (for when it is real): shake the card 300 ms and show the error in an info-style tooltip on the password label, no inline red text.
3 · onboarding (6 steps, one artboard, shared state)
Header: wordmark left, "step n / 6" right, progress bar under. Footer: back chevron left, next button right (hidden on tap-to-advance steps). Every question carries an info tooltip with the helper text shown in quotes below.
1. how tall are you? Slider 140–210 cm (white accent), big readout in ft′ in″ with cm beside it. Tooltip: "sets your avatar's height so lengths and hems sit right."
2. what do you weigh? Big number field (no −/+ buttons) + lb / kg pill toggle that converts the value. Tooltip: "only used to shape your avatar. never shown to anyone."
3. pick a body base. Two glass radio cards with silhouettes: masculine, feminine. Tap = answer and advance after 420 ms. Tooltip: "a starting shape. you can fine-tune every proportion later."
4. choose a skin tone. 8 round swatches, 64 px: #F6D9C6 #EBC1A0 #D9A57E #B9805A #93603F #6E452C #4A2E1F #2E1C13. Tap advances. Tooltip: "so colors read the way they would on you."
5. what size do you usually wear up top? Pills XS S M L XL XXL. Tap advances. Tooltip: "helps us flag listings that will actually fit."
6. what style do you want to build today? Glass text box (the one place free text is allowed), placeholder "grunge 2000s, cowboy, quiet luxury…". Not skippable: build my look → avatar stays disabled until the box has text. Tooltip: "describe a vibe, a place, a person, an era. we pull thrift pieces that match and dress your avatar."
4 · avatar
Header: wordmark only. Body: left context panel (glass, 360–460 px, 760 px tall) + right 3D stage.
Left panel has a segmented tab control: inventory · body · style. Arriving from onboarding it opens on style, with the prompt pre-filled and that outfit already built and worn. Switching tabs fires a surge and fades the pane in.
• inventory: underline search field ("search every store") over a 2-column grid of item cards that scrolls inside the panel. Tap a card to put it on or take it off. No category chips, no try-on buttons.
• body: masculine / feminine pill toggle, then 7 sliders with readouts: height (140–210 cm), weight (90–300 lb), shoulders, chest, waist, hips, leg length (0–100). Changes update the avatar live. No reset button.
• style: "describe a vibe" underline field; enter submits, rebuilds the outfit and fires a surge. "saved fits" heading with info tooltip "outfits you save land here."
Right stage is transparent so the ribbons show through, with a soft light pool under the avatar.
• Avatar: glassy, semi-transparent body (masc or fem base) scaled by the body sliders.
• Rotate: drag horizontally for a full 360° turn of the whole body (0.4°/px, no clamp), arrow keys ±15°, double-click resets. No rotate buttons.
• Hotspot nodes on every worn item (Tesla-dashboard style). Labels sit right of the body for right-side anchors and left for left-side anchors. Nodes follow the item's 3D anchor as the avatar turns or reshapes. Nodes on the far side fade to 25% and ignore taps until they turn back into view.
• Tap a node → detail card; tap again or close → hide. Take off removes the item and its node.
• Checkout pill bottom right.
Interaction, motion and accessibility
Motion signals progress; nothing moves without a reason, and everything still works with motion off or no mouse.
Motion rules
• Step or tab change: background surge + new content fades up 14 px over 550 ms.
• Selection changes animate 250–300 ms (glow, border, fill). Avatar reshapes and node positions ease 300 ms, but track the pointer instantly while dragging.
• Loading anything (search, outfit build, 3D conversion) shows the tee loader, never a spinner.
• prefers-reduced-motion: reduce turns off ribbon drift, surge, step fades, node pulse and the loader animation.
Accessibility
• Real elements: buttons are <button>, links <a>, choices native radio inputs inside labels, fields have <label>. Never click handlers on divs.
• Icon-only controls (back chevron, info icons, close) carry an aria-label; tooltips use role="tooltip" and are linked with aria-describedby.
• Visible focus ring everywhere: 2 px white outline, 3 px offset.
• The 3D stage is focusable with an aria-label describing drag, arrow keys and double-click.
• Known issue to fix in the build: on tap-to-advance steps, arrow-key navigation between radios must change the value without advancing. Advance only on pointer click / tap, enter or space.
• Text contrast: white on the darkest gradient stops passes 4.5:1. Keep muted text at ≥ 72% white.
Implementation notes
The spec is framework-agnostic; the agent should build the four screens with mocked data first, then wire the real pipeline behind the same shapes.
Stack
• Frontend framework: [team to confirm]. Suggested: React + three.js via react-three-fiber, so the avatar stage, background shader and loader share one renderer.
• Fonts: M PLUS Rounded 1c from Google Fonts. Tokens as CSS variables; theme switch swaps the three gradient stops.
• Testing: manual by Anjelo. Do not add Playwright or other automated UI tests unless asked.
3D stage
• Avatar meshes: masc and fem base bodies, morph targets (or bone scales) for height, weight, shoulders, chest, waist, hips, leg length.
• Garments are the image-to-3D outputs fitted to the body; each garment carries one anchor point (local position) for its hotspot.
• Hotspots are an HTML overlay: every frame, project each anchor with vector.project(camera) and position the node; fade nodes whose anchor faces away from the camera (anchor normal · camera direction < 0) to 25% opacity over 200 ms and make them non-interactive.
• Orbit: OrbitControls with full 360° horizontal rotation, damping on, double-click resets.
Data shapes
type Item = {
  id: string; name: string;
  category: 'tops' | 'bottoms' | 'outerwear' | 'shoes';
  source: string;          // store name, e.g. ebay, depop
  price: number; size?: string;
  imageUrl: string; listingUrl: string;
  modelUrl?: string;       // 3D garment once converted
  anchor?: [number, number, number];
};

type Profile = {
  heightCm: number; weight: number; weightUnit: 'lb' | 'kg';
  base: 'masc' | 'fem'; skinTone: string; topSize: 'XS'|'S'|'M'|'L'|'XL'|'XXL';
  body: { shoulders: number; chest: number; waist: number; hips: number; legs: number }; // 0–100
};

type Look = { prompt: string; itemIds: string[] };
Acceptance checklist
[ ] All visible copy lowercase; no helper text outside tooltips
[ ] Splash, sign up, onboarding, avatar match the canvas at 1280–1440 px
[ ] Ribbons drift on every screen; surge fires on step change, tab change and style submit
[ ] Onboarding steps 3–5 advance on tap; keyboard arrows do not advance
[ ] Item card tap toggles wearing; node appears on the avatar at the item's anchor
[ ] Drag and arrow keys rotate the avatar; nodes follow
[ ] Detail card opens from a node; take off removes item and node
[ ] Checkout pill shows count and total, disabled at zero items, opens the mocked checkout sheet
[ ] Tee loader shown for every wait
[ ] Reduced motion disables all decorative animation
Open questions and change log
Open questions
None open.
Change log
Version
Date
Change
v1.2
Oct 17, 2026
Decided: real log in screen, mocked until the backend supports auth; far-side hotspots fade
v1.1
Oct 17, 2026
Decided: desktop only; checkout is an in-app sheet, mocked for now; style prompt not skippable; avatar turns a full 360°; avatar opens on the style tab after onboarding
v1
Oct 17, 2026
Locked from the design canvas: PS3 glass look, lowercase, tooltips over text, reduced buttons, tee mark with 2d→3d loader, tagline
