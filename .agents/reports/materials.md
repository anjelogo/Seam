# Leather share, before and after V9

Dev clone `seam_v3`, 2026-10-21: 2,821 active garments, 2,740 tagged, 2,305 usable_3d.
A garment counts as leather when its material normalizes to `leather`/`faux_leather` or an active listing title matches `leather|pleather|faux` (so "faux fur" counts too).
Before = HEAD `ed1b4ee` (pre-V9), after = `35db856` (V9), both served from a code copy against the same database.

## Inventory by stage

V9 changes what future scrapes search for, not the stock already in the database, so these numbers are the same before and after.

| slot | all | tagged | usable_3d |
|---|---|---|---|
| top | 42/667 (6%) | 42/667 (6%) | 30/570 (5%) |
| bottom | 60/624 (10%) | 60/624 (10%) | 50/545 (9%) |
| outer | 152/833 (18%) | 152/833 (18%) | 132/710 (19%) |
| shoes | 301/601 (50%) | 301/601 (50%) | 233/472 (49%) |
| onepiece | 0/10 | 0/10 | 0/7 |
| accessory | 3/5 | 3/5 | 0/1 |
| all slots | 564/2821 (20%) | 558/2740 (20%) | 445/2305 (19%) |

The 81 untagged garments have no slot yet and only appear in the all-slots row.
Leather outerwear is usable for 3D at the same rate as other outerwear (132/152 = 87% against 710/833 = 85%).

## Scrape plan

`python -m app.worker enqueue-all --dry`.

- **Before:** 10 queries × 4 slots × 4 sources = 160 jobs.
  - `leather` ran on top, bottom, outer and shoes (16 jobs).
  - On ebay, depop and poshmark, every outer search was "<query> jacket" and every shoes search "<query> shoes".
- **After:** the new `SCRAPE_QUERIES` gives 232 jobs.
  - `leather@outer` runs only on outer (4 jobs, searched as "leather windbreaker") and `sneakers@shoes` only on shoes.
  - Outer terms over 15 outer queries: windbreaker 5, cardigan 2, coat 2, jacket 2, overshirt 2, fleece 1, none 1 (the `fleece` query).
  - Shoes terms: sandals 6, boots 3, loafers 3, sneakers 2, none 1.
  - Top terms: tee 4, longsleeve 3, shirt 3, hoodie 2, sweater 2.
  - Bottom terms: pants 4, jeans 3, trousers 3, shorts 2, skirt 2.

## Outfit pool

`curate._candidates`, 30 per slot. Each cell is leather out of 30, before → after.

| prompt | top | bottom | outer | shoes |
|---|---|---|---|---|
| grunge 90s | 0 → 2 | 2 → 2 | 10 → 10 | 19 → 13 |
| y2k going out | 5 → 1 | 5 → 2 | 6 → 7 | 13 → 10 |
| streetwear | 0 → 2 | 4 → 1 | 3 → 6 | 4 → 14 |
| minimal workwear | 0 → 0 | 0 → 0 | 0 → 0 | 18 → 12 |
| total of 120 | 5 → 5 | 11 → 5 | 19 → 23 | 54 → 49 |

The pool is not less leathery overall.
Dropping the cheapest tie-break lets a prompt's pool drift toward the inventory base rate: streetwear outer goes from 10% to 20% and streetwear shoes from 13% to 47%.
The cap only bites above 10 of 30 per material or category.
Where the old pool was already at or above the base rate, the shuffle and cap trimmed it: grunge shoes went from 63% to 43% and workwear shoes from 60% to 40%.

## Outfit pieces

`POST /outfits?v=3`, 4 prompts × 3 outfits, real Claude. One sample per prompt, so these numbers are indicative.

| | top | bottom | outer | shoes | all pieces |
|---|---|---|---|---|---|
| before | 1/12 | 2/12 | 4/12 | 6/12 | 13/48 (27%) |
| after | 0/12 | 1/12 | 2/12 | 6/12 | 9/48 (19%) |

Outers chosen:
- **Before:**
  - grunge: leather jacket, denim jacket, leather jacket.
  - y2k: faux-leather jacket, denim jacket, faux-leather jacket.
  - streetwear: hoodie, nylon jacket, polyester jacket.
  - workwear: polyester, corduroy and cotton jackets.
- **After:**
  - grunge: flannel button-up, denim jacket, leather jacket.
  - y2k: faux-leather jacket, nylon jacket, denim jacket.
  - streetwear: hoodie, canvas jacket, jacket.
  - workwear: jacket, denim jacket, fleece jacket.

## Which stage drove the skew

- **The final pick drove it.** Claude reached for the stereotypical leather jacket in 4 of the 6 grunge and y2k outfits (67%). Those prompts' outer pools were 20–33% leather, and usable outerwear was 19%.
- **The pool added to it for grunge.** Ranking by prompt overlap, then cheapest, raised grunge's outer pool to 33% leather.
- **Tagging and the usable_3d filter did not.** They are flat (outer 18 → 18 → 19%, shoes 50 → 50 → 49%).
- **The scrape sets the base rate.** It accounts for 18% of outer and half of the shoes. Shoe picks simply follow that base rate (6/12 before and after).

After V9, leather outers fell to 2/12, one each for grunge and y2k, and every response used three different outer materials.
The remaining lever is the scrape: the new terms and `leather@outer` only change what tonight's and later scrapes add.

## Material normalization

The backfill rewrote 2,357 of the 2,740 tagged materials. The raw data had 150 distinct values.

After normalizing:

| material | garments |
|---|---|
| cotton_jersey | 681 |
| leather | 465 |
| denim | 386 |
| none | 383 |
| other | 218 |
| polyester | 135 |
| canvas | 84 |
| nylon | 82 |
| faux_leather | 65 |
| fleece | 50 |
| suede | 48 |
| knit | 41 |
| corduroy | 20 |
| silk_satin | 18 |
| wool | 18 |
| mesh | 14 |
| flannel | 11 |
| linen | 11 |
| cotton_twill | 7 |
| rubber | 3 |

The verbatim `normalize_material` picks the longest alias, so "synthetic leather" and "PU leather" become `leather`; that affects 6 garments here.
"polyester blend" and "wool blend" become `other`.
New tags come straight from the `MATERIALS` list in the tagging prompt.
