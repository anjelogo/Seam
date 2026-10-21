# Custom model research

Status: research only, nothing built. Branch `caden/custom-model-research`. Started 2026-10-20.

Goal: decide whether a custom model would serve Seam better than the hosted models it uses now, starting with the bias towards leather items we've seen.

---

## 1. Where models run today

| Step | Code | Model | Output |
|---|---|---|---|
| Tagging | `api/app/cv/tag.py` | `perceptron-mk1.5` (2 tries), then `gemini-3.8-flash` | `ItemTags`: slot, category, colors, material, fit, style_tags, era, size, est_retail, usable_for_3d |
| Condition | `tag.py: condition()` | `isaac-0.1` on fal, else Mk1.5 | `Condition` enum |
| Cutout | `api/app/cv/cutout.py` | BiRefNet + SAM (local, about 11.5 GB RAM, about 53 s per item on the CT) | 1024² RGBA PNG |
| Candidate pool | `api/app/llm/curate.py: _candidates` | No model: size match, then word overlap with the prompt, then cheapest first | Up to 30 items per slot |
| Outfits | `curate.py: _ask` | `claude-sonnet-5-5` | Picked items + reasons |

A "custom model" could replace any of these. Each one fails in a different way, so the first job is finding which step produces the leather skew.

## 2. Where the leather bias could come from

There are at least four possible sources. Only some need a new model, so measure before training anything.

| # | Hypothesis | Evidence in the repo | How to check | Needs a model? |
|---|---|---|---|---|
| H1 | **The inventory is leather-heavy** | `SCRAPE_QUERIES` includes `leather`, and every query runs for all four slots (`leather` + top/bottom/outer/shoes). Several other queries also pull leather (`grunge`, `workwear`, `90s`, `carhartt`). Depop keeps 48 results per query against 12 for the other sources. | SQL: share of items with `tags.material ILIKE '%leather%'` or `category = 'leather_jacket'`, split by `scrape query` and source. | No. Rebalance the queries or cap results per query. |
| H2 | **The tagger over-labels leather** | Shiny, dark or "faux/vegan leather" garments are easy to mislabel. `leather_jacket` is the only category named after a material. `models.py` gives `"leather"` as an example material. | Hand-label 200–300 items and compare against `tags.material` and `category`. Look at false-positive leather by color (black) and by view (on_model or flat_lay). | Maybe. Try a prompt fix first, then a model. |
| H3 | **Retrieval favours leather** | `_candidates` ranks by word overlap with the prompt, which includes `material`. Prompts like "edgy" or "grunge" don't say leather, but the scraped titles do. The final tiebreak is cheapest first. | Log the pool for 20 fixed prompts. Compare the leather share in the pool with the leather share in the inventory. | Embeddings would help here (see §4B). |
| H4 | **Claude picks leather** | The LLM has its own style priors: "edgy" = leather jacket. | Same fixed prompts. Compare the leather share in the picks with the leather share in the pool. | A prompt fix, or a learned reranker / preference model (§4C). |

**Tell-tale numbers:** if H1 holds, leather is overrepresented in the inventory. If H2 holds, labels disagree with humans. If H3 holds, leather is a bigger share of the pool than of the inventory. If H4 holds, leather is a bigger share of the picks than of the pool. One SQL session and a 20-prompt log separate all four.

## 3. Step zero: an evaluation set (needed whichever option we pick)

You can't train or compare models without this.

- **Gold set:** 300–500 of our own listings, stratified by slot, source and suspected material. Hand-label material, category, primary color and usable_for_3d. Include deliberately hard cases: black synthetic jackets, faux leather, coated denim, shiny nylon.
- **Weak labels for free:** listing titles and descriptions often state the material ("100% cotton", "genuine leather", "vegan leather"). A regex pass gives noisy labels on thousands of items. Use them for training data and for spotting disagreements, not as gold.
- **Metrics:** per-class precision/recall (especially leather precision), a confusion matrix, calibration (does confidence 0.9 mean 90% right?) and leather share at each pipeline stage (§2).
- **Rule check:** AGENTS.md bans automated tests. An eval script that prints a report is measurement, not a test suite, but confirm with Anjelo before adding one.

## 4. What a custom model could be

### A. A custom tagger (replaces or backs up Perceptron/Gemini)
The tagger is where wrong labels come from, and those labels feed everything downstream.

| Option | What it is | Pros | Cons |
|---|---|---|---|
| A1. Prompt and schema fix (baseline, not custom) | Add material definitions, a "faux/vegan leather" value, an `unknown` option, and "only say leather if the texture or listing text supports it" | Hours of work, no infrastructure | Hosted models drift. Can't fix a model's deep priors. |
| A2. Frozen fashion embeddings + linear probes | Embed the cutout with Marqo-FashionSigLIP or FashionCLIP and train a small head per attribute (material, category, color, fit) | Cheap to train (CPU-feasible). Fast at inference. Easy to rebalance classes. Embeddings can be reused for retrieval (B). | One head per attribute. No free-text fields (style_tags, era). Probes are only as good as the embedding at telling texture apart. |
| A3. Fine-tune a small VLM with LoRA | Qwen-VL / Gemma / Florence-2 class model, trained to output our exact `TagOut` JSON | One model replaces the whole tagger. Learns our schema and enums exactly. Runs locally, so no per-item API cost. Fashion Florence (2026) reports 63% material accuracy against 43% for GPT-4o-mini. | Needs a GPU for training (rentable). Needs a few thousand labelled examples. More to maintain. Runs slower than A2 on the CT's CPU. |
| A4. Distil the current tagger, then correct it | Use existing `items.tags` as training labels, override them with the gold set and weak labels, and train A2 or A3 on that | Thousands of labels already exist at no extra cost | Copies the current biases unless corrections are weighted heavily |

### B. Retrieval and ranking (replaces word overlap in `_candidates`)
- **What:** embed every item (image + title) and the style prompt into one space, and pull candidates by similarity instead of shared words.
- **Starting point:** off-the-shelf FashionSigLIP. Marqo reports up to 57% better MRR than FashionCLIP 2.0 on retrieval (vendor claim). Later, fine-tune it contrastively on our own data.
- **Pros:** fixes H3 directly. "Edgy" can match studded denim, not only listings that say "leather". Diversity limits like max-marginal-relevance or per-material caps are easy to add.
- **Cons:** needs pgvector or similar in Postgres, which changes the shared migrations and means coordinating with Anjelo. Embeddings carry their own biases, so measure again with §3.

### C. The outfit model (replaces or steers Claude)
- **C1. Constraints first:** a per-material cap per outfit and diversity rules inside `_repair`. This is not a model.
- **C2. Learned reranker:** a small model scores Claude's candidate outfits using signals from users (saved looks in `/me/looks`, refine feedback).
- **C3. Fine-tune an open LLM** on outfit data (Polyvore, our saved looks) with preference methods (§5).
- **Pros:** C2 and C3 personalise to real users.
- **Cons:** we don't yet have enough user signal for C2 or C3. Claude is already strong at this step, and the bias may come from the pool (H1/H3), not from Claude.

### D. Cutout and segmentation
Not related to the leather bias. Worth a look only for memory and speed (about 11.5 GB per job). Skip for this research.

## 5. Training methods compared

| Method | How it works | Good for | Pros | Cons | Fit for Seam |
|---|---|---|---|---|---|
| **Linear probe** | Freeze the encoder, train one layer | Attribute classifiers (A2) | Minutes on a CPU. Hard to overfit. Easy to rebalance. | Can't fix what the encoder can't see | ⭐ Best first experiment |
| **Full fine-tune** | Update every weight | Large, clean datasets | Highest ceiling | Expensive. Forgets general skills. Needs lots of data. | ✗ Overkill |
| **LoRA / QLoRA SFT** | Train small adapter matrices. QLoRA also quantises the base model to 4-bit. | VLM tagger (A3) | Cheap. One consumer or rented GPU (24 GB). Adapters are small and swappable. | Still needs a few thousand good labels. Copies label noise. | ⭐ Main path if A2 isn't enough |
| **Knowledge distillation** | A small student learns from a big teacher's outputs | Cutting API cost (A4) | Labels at no cost. Runs locally. | Inherits the teacher's biases, which is exactly our problem unless corrected | ✓ Combine with corrections |
| **Contrastive (CLIP-style)** | Pull matching image/text pairs together, push others apart | Retrieval embeddings (B) | Learns from listing title + photo pairs, which we already have | Needs big batches and many pairs. Hard negatives matter. | ✓ Second stage, after an off-the-shelf baseline |
| **Class rebalancing** (re-weighting, re-sampling, logit adjustment, focal loss) | Change the loss or the sampling so rare classes count more | Any classifier with a skewed dataset | Targets the bias directly. A few lines of code. | Can over-correct and lose leather recall | ⭐ Use alongside any supervised method |
| **Active learning** | The model flags the items it's least sure about for humans to label | Building the gold set cheaply | Gets the most value per human label | Needs a labelling loop or UI | ✓ For §3 |
| **DPO** | Learn from chosen/rejected pairs without a reward model | Outfit preferences (C3) | Simpler and more stable than PPO | Needs preference pairs, which we don't collect yet | Later |
| **RLHF (PPO + reward model)** | Train a reward model on human preferences, then optimise against it | Subjective quality (outfits) | Most flexible | Complex, unstable and expensive. Reward hacking. | ✗ Not at our scale |
| **RLVR / GRPO** | RL with an automatic reward (correct JSON, matches the label, consistent with the listing text). Compares groups of samples, so no value model. | Tagger outputs that can be checked automatically | Reported to beat SFT on structured-output accuracy and on some VLM perception tasks. Works with small datasets and LoRA. | Only as good as the reward. One study found SFT before GRPO hurt VLM reasoning. More compute than SFT. Less mature tooling for VLMs. | ✓ A later refinement for A3, not a starting point |

**Short version:** for a labelling problem like ours, supervised methods (probe → LoRA SFT) with class rebalancing come first. Reinforcement learning earns its cost when the target is a preference (outfits) or when there's a checkable reward and SFT has plateaued.

## 6. Data sources

| Source | What | Use | Caveat |
|---|---|---|---|
| Our `items` table | Photos, cutouts, titles, descriptions, current tags | Main training and eval data | Inherits the scrape skew (H1). Depop's ToS bans scraping, so it's risky to train on that data. |
| iMaterialist (Fashion) | Attributes incl. material | Material and category pretraining | Check the license |
| Fashionpedia | Segmentation + fine-grained attributes | Category, parts, attributes | CC BY 4.0 |
| DeepFashion / DeepFashion2 / DeepFashion-MultiModal | Categories, attributes, landmarks | Attribute heads, benchmarks | Non-commercial research license |
| Polyvore Outfits | Curated outfits | Outfit compatibility (C) | Old. Retail product photos, not thrift. |

Retail and studio photos look different from thrift listings (bad lighting, hangers, people wearing the clothes). Public data should be for pretraining only. Evaluate on our own gold set.

## 7. Constraints that shape the choice

- **Hardware:** the CT has 4 CPU cores. One cutout job already uses about 11.5 GB. Caden's PC (RTX 3080 Ti, 12 GB VRAM, 32 GB RAM) covers almost every option here:
  - **Easy:** A2 probes and embedding the whole catalogue.
  - **Fine with gradient accumulation:** contrastive fine-tuning of FashionSigLIP, LoRA on VLMs up to about 4B.
  - **Tight:** QLoRA on 7–8B VLMs (batch 1, one image per example, gradient checkpointing). GRPO on models up to about 3B (slow, because it generates several answers per example).
  - **Rent a 24–80 GB GPU for:** 7B+ GRPO or full fine-tunes.
  - **Software:** use WSL2 rather than native Windows (bitsandbytes, Unsloth and flash-attn work best on Linux).
- **Inference cost:** A2 adds milliseconds per item. A3 on CPU could add tens of seconds per item to a backlog that's already growing (about 2,900 scraped vs about 1,400 tagged a day).
- **Demo rule:** no live third-party calls on the demo path. A local model helps with this.
- **Contract:** new tag fields (for example `material_confidence`) are optional additions and must be logged in HANDOFF. Changing the `Category` enum needs Anjelo, because it drives 3D templates.
- **Ownership:** all of this lives in `/api`, apart from a possible pgvector migration in `shared/`.

## 8. Suggested order (for discussion, not committed)

1. **Measure (§2, §3):** SQL breakdown + 20-prompt pool log + a 300-item gold set. This tells us which hypothesis is true. Likely a day or two.
2. **Free fixes:** rebalance `SCRAPE_QUERIES` and cap per query if H1 holds, add the tagger prompt and schema fix if H2 holds, add a per-material cap in `_repair` if H4 holds.
3. **First model:** FashionSigLIP embeddings → material and category probes with class rebalancing (A2). The same embeddings drive retrieval (B). One model fixes two steps.
4. **If probes plateau:** LoRA-SFT a small VLM on distilled + corrected labels (A3 + A4). Then try GRPO with a label-match + JSON-validity reward.
5. **Later, once users exist:** collect preference pairs from saved and refined looks, then DPO or a reranker for outfits (C2/C3).

## 9. Path to production

Assumes the model runs on Anjelo's server (the Proxmox CT that runs `worker-cv`). Nothing in the HANDOFF log says it has a GPU, so this plan assumes CPU-only until Anjelo confirms.

| # | Step | Done when |
|---|---|---|
| 1 | **Set the bar before training.** Use the gold set (§3) to score the current tagger as the baseline. | Written targets, e.g. leather precision ≥ 0.9, category accuracy ≥ baseline, under 1 s per item on the CT |
| 2 | **Train on the 3080 Ti, reproducibly.** Snapshot the data (item ids + labels), keep the config in git, and name the weights by hash. | Any run can be rebuilt from its id |
| 3 | **Export for CPU.** ONNX + int8 quantisation (onnxruntime is already a dependency for BiRefNet). A VLM would need GGUF/llama.cpp on CPU, or vLLM with a GPU. | The exported model matches the PyTorch scores on the gold set |
| 4 | **Wire into `tag.py` behind a flag.** e.g. `TAGGER=local\|perceptron`. The local model fills material and category, and items below a calibrated confidence still go to Perceptron. `ItemTags.tagger` already records which model answered. | Switching the flag needs no code change |
| 5 | **Shadow mode, about a week.** Run both taggers on live items, store both answers, serve Perceptron's. | Agreement and gold-set scores beat the baseline on live data, not only on the test set |
| 6 | **Roll out.** Flip the flag and re-tag the existing backlog (`python -m app.cv`). Add a HANDOFF entry for the new env var and the weights path. | The leather share in the inventory and the pool matches what the hand-labelled set says it should be |
| 7 | **Monitor.** Per day: leather share, confidence histogram, fallback rate, and agreement on a 2% sample re-checked by Perceptron. Add these to `python -m app.worker status`. | Drift shows up within a day |
| 8 | **Retrain loop.** Hand-label the least confident items (active learning), retrain on the 3080 Ti, and swap only if the gold-set score improves. Keep the previous weights for rollback. | Monthly, or when monitoring flags drift |

**Speed on the CT:**
- An int8 ViT-B embedding + classifiers is about 0.1–0.3 s per item on CPU. Cutout takes about 53 s, so the classifier won't be the bottleneck.
- Each tag job now starts a fresh process (4a0fe1e), so the model reloads every item (about 1–2 s for ViT-B). That's acceptable. Don't put a multi-GB VLM in that path.

**Serving:**
- A2 (classifiers): runs inside `worker-cv`. No new service, port or container. Memory adds about 0.5 GB on top of the 11.5 GB peak.
- A3 (VLM): needs its own GPU-backed service (a new compose service, a port, and a HANDOFF entry), or tagging stays slow on CPU.

**Weights:** keep them out of git. Store them in `data/models/<hash>/` on the server volume, with the hash pinned by env var.

## 10. Open questions

- Which surface showed the leather bias: tags, the inventory screen, or the outfits? (Decides between H1–H4.)
- Is there a GPU budget for training, and is local inference on the CT required?
- Are we comfortable training on Depop data given its ToS?
- Does Anjelo agree an eval script isn't an "automated test"?
- Would pgvector in shared migrations be acceptable?
- What are the server's specs (GPU? RAM headroom beyond worker-cv's 11.5 GB?) Proxmox can pass a GPU through to an LXC.

## Sources

- [Fashion Florence: fine-tuning Florence-2 for structured fashion attribute extraction (arXiv 2605.09827)](https://arxiv.org/pdf/2605.09827)
- [Zero-shot product attribute labeling with VLMs, a three-tier evaluation (arXiv 2601.15711)](https://arxiv.org/html/2601.15711)
- [Frozen CLIP + linear probes for fashion attributes (SJSU thesis, 2026)](https://scholarworks.sjsu.edu/etd_theses/5804)
- [Marqo-FashionCLIP / FashionSigLIP (GitHub)](https://github.com/marqo-ai/marqo-FashionCLIP) · [model card](https://huggingface.co/Marqo/marqo-fashionCLIP/blob/main/README.md)
- [Beating FashionSigLIP (blog, unreviewed)](https://hopitai.substack.com/p/beating-fashionsiglip)
- [RL-Struct: RL for reliable structured output (arXiv 2512.00319)](https://arxiv.org/pdf/2512.00319)
- [RL makes MLLMs see better than SFT (arXiv 2510.16333)](https://arxiv.org/pdf/2510.16333)
- [SFT or RL? Training R1-like reasoning VLMs (arXiv 2504.11468)](https://arxiv.org/pdf/2504.11468)
- [RL vs SFT knowledge degradation (arXiv 2507.10616)](https://web3.arxiv.org/pdf/2507.10616)
- [Post-training: when to use SFT, DPO, PPO, GRPO (blog)](https://saketv.substack.com/p/post-training-llms-when-to-use-sft)
- [GRPO fine-tuning guidance (practitioner page)](https://smithery.ai/skills/aws-solutions-library-samples/grpo-finetuning)
- [Unsloth GRPO + LoRA discussion (Hacker News)](https://hn.svelte.dev/item/43124091)
