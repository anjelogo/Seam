# Clean-room record: the Newton port of the drape sim

This records how the Newton backend was written so that none of the warp fork's code reached it. It is
licensing hygiene, not legal advice.

## Why

The drape stage ran on `NvidiaWarp-GarmentCode` at `63baf6855efdd89b2834b74640f84b3bb0d86b50`, under
the NVIDIA Source Code License. Its §3.3 allows research or evaluation use only, and its §3.2 carries
that limit into every derivative work. Copying, translating or closely paraphrasing the fork's code
into our backend would have made the backend a derivative, so the port kept the people who read the
fork apart from the people who wrote the new engine.

## Rules applied

- **Readers.** Only designated reader agents opened fork files. They wrote behaviour in plain prose
  (`SIM_SPEC.md`) with no code, no pseudocode and no fork-internal identifiers, and cited published
  methods instead.
- **Audit.** The lead audited every reader output before any implementer could read it. Reader
  output was staged outside the repo and merged into `SIM_SPEC.md` only after its audit.
- **Implementers' inputs.** Implementers worked only from `SIM_SPEC.md`, `NEWTON_MAP.md`, the Wave 2
  interface contract (outside the repo), Newton 1.7.0 and warp-lang 1.18 source and docs
  (Apache-2.0), pygarment (MIT), published papers, and the fork's black-box output files (meshes,
  per-frame position dumps, timings). Every brief forbade:
  - opening, listing or grepping any path containing the fork;
  - upstream warp before 1.7 (pre-Apache), and any `warp/sim` source;
  - running the fork env on the pod;
  - opening pygarment's `meshgen/simulation.py`.
- **pygarment's `meshgen/simulation.py`.** The file carries an NVIDIA proprietary copyright header
  (it derives from a warp example) although the GarmentCode repo is MIT, so it was handled like the
  fork. Its behaviour is in `SIM_SPEC.md` §2, and our frame loop, `drape/gc_sim/simulation.py`, was
  written from that spec.
- **pygarment's `meshgen/garment.py` (MIT)** was adapted into `drape/gc_sim/garment.py`, with its
  notice on the first line and the MIT text in `drape/gc_sim/LICENSE`.
- **Newton and warp code.** The XPBD spring, bending and delta kernels are imported from Newton, not
  copied. Two pieces were adapted under Apache-2.0, each with a one-line attribution:
  - the body-contact response in `drape/sim_newton/body.py`, from Newton's
    `solve_particle_shape_contacts`, with the final accumulation changed to the behaviour in §10.5;
  - the ray–triangle test in `drape/sim_newton/self_contact.py`, a port of warp 1.18's
    `intersect_ray_tri_woop` (`warp/native/intersect.h`), the watertight test of Woop et al. 2013.

## Who read what

| role | session | fork files opened | wrote |
| --- | --- | --- | --- |
| lead | this session | none | orchestration, NEWTON_MAP lead decision, §10 merge, §10.14, scripts, docs |
| S1 reader | ses_e93dcbd15ffeMmihZNx3zci0fJ | yes, listed in SIM_SPEC §9.1 | SIM_SPEC.md §0–§9 |
| S1b reader, 2 attempts | ses_e93a9a14dffelE1DdT1jXRp2Rs, ses_e9399ac9affeM7CdpOYS2FYAKy | yes; both stalled on infrastructure timeouts | nothing |
| S1c reader | ses_e9367bcf7ffe7ECwtXRLI4D652 | yes, listed in SIM_SPEC §10.13 | the §10 staging file |
| S1d reader | ses_e906768f3ffe5rQhxx0PdqR4Gx | yes, listed in SIM_SPEC §10.14 | a staging note on point–triangle features |
| S1e reader | ses_e9058a3bbffeyx8CPnPAE6wQU0 | yes, listed in SIM_SPEC §10.14 | a staging note on the point–triangle gradients |
| S1f reader | ses_e905077a3ffeNiKUlKtGsqFaS0 | yes, listed in SIM_SPEC §10.14 | a staging note on sidedness and the survey's triangle test |
| S2 Newton survey | ses_e93db3eaeffeSaSZPE3AZXhA7n | no | NEWTON_MAP.md |
| S3 parity harness | ses_e93da381dffeEcOODwXoj3npwz | no; executed the fork env as a black box | drape/parity.py, runs/out_fork_ref |
| plan agent | ses_e93a5a283ffe6SCRG1jFTIot65 | no | the Wave 2 interface contract |
| N1 | ses_e9366f693ffenTzWMdjDRCWlfc | no | drape/gc_sim/*, sim_newton/{__init__,builder,solver}.py |
| N2 | ses_e9365d0f1ffeEIgTIRCH7W54NU | no | sim_newton/body.py |
| N3 | ses_e936553bfffexh0pseaOrCwLKH | no | sim_newton/self_contact.py |
| N4 | ses_e9364db9affemdU36t16T3NKFd | no | sim_newton/attach.py |
| N5 | ses_e9359e1d1ffe62wOcs7JUgCjVX | no | sim_newton/panel_drag.py, smoothing.py |
| N6 | ses_e93599d39ffeu2MWeo0nVBxi2c | no | drape.py, engine_fork.py, sim_newton/integrate.py |
| §10 fix agents | N1f ses_e9338639cffedT9ugFZxWB6YPC, ses_e93338297ffe5uBNXRVms1VQ5D, ses_e9331bcb4ffefduogmU8owAnbS, ses_e93280543ffeSHV0BpPExvVURz; N2f ses_e933917f5ffekdrW5cyOeViO4D; N3f ses_e9337e468ffeMf3xqiqLktLafQ, ses_e931b5f0bfferMvmcW1WjExswu; N5f ses_e933781eeffe1ck97hyRGzA956; N6f ses_e93372e58ffeegzcxN6OequAQD | no | §10 conformance edits |
| parity fix loop 1 (N3) | ses_e908d6e15ffey4AP0j8lakHQIg | no | self-contact buffer capacity (b00905e) |
| parity fix loop 2 (N3) | ses_e9079d414ffePOyjS0dNnyIPtx | no | watertight piercing test (905c083) |
| blind reviewer | ses_e9046c04bffeqFOwo2zCocaCQK | no; saw only the unlabelled contact sheets | the verdicts in RESULTS_NEWTON.md |

**Lead disclosure.** The lead opened no fork file. During orientation, before noticing its NVIDIA
header, the lead read pygarment's `meshgen/simulation.py` once. Nothing from it was pasted to any
agent, and the lead wrote no driver code. The lead's code edits were limited to the install scripts,
the `--engine` default and ignore rules, and two docstring trims in `parity.py`. The lead's parity
diagnostics ran our own engine in scratch scripts outside the repo and compared its output against
the fork's recorded dumps; they never ran the fork.

## The spec handed over

`SIM_SPEC.md` was committed in three parts: §0–§9 in d736338, §10.1–§10.13 in 4a3207b, and §10.14
with the Newton default switch. Each reader part was audited in three steps:

1. A mechanical scan for code fences, `def`/`class`/loop/`if` lines, `wp.` calls, decorators,
   `tid`, braces, semicolons, `->`, `==`, `[i]` and `self.`.
2. An inventory of every code-formatted identifier. Only API names that pygarment itself calls,
   config keys and Model field names were present.
3. A full read of every line, looking for paraphrased code.

Result: no code, pseudocode or fork-internal kernel or helper names. One §10 paragraph walked through
a gradient derivation, so before merging it was condensed to the observable effect it implies (a
two-body denominator). §10.14 is the lead's own summary of the S1d–S1f notes. Those notes reached no
implementer: both parity fix loops were briefed before them, from the lead's black-box evidence,
SIM_SPEC §4.7, §5.5, §6.27 and §10, and upstream warp's Apache-2.0 source.

## Implementer statements

Every N1–N6 report ended with this line, verbatim: "I did not open any NvidiaWarp-GarmentCode file or
pygarment/meshgen/simulation.py." The N2f and N5f fix agents confirmed the same in their completion
markers. The final reports of N1f, N3f and N6f could not be retrieved because the agent session store
returned errors. Their briefs carried the same rule, and the lead reviewed every line of their diffs,
which name no fork identifier. Both parity fix loops ended with: "Clean-room: I did not open or run
any NvidiaWarp-GarmentCode file or the fork env."

## Black-box runs

S3 ran the fork env on the pod (`drape.drape`, `drape.coverage`, `drape.parity --noise`) to produce
the reference drapes, and never opened a fork file. Implementers never ran the fork env. The lead
kept its own fork-env commands to the setup script and S3's batch, and filtered their output to
status lines, so no fork source lines were displayed. The first pod, the only machine that ever held
the fork env, was removed by RunPod when the account balance ran out mid-run. Its replacement had
only the default install.

## Final install

`drape/scripts/setup_gpu.sh` installs `newton` 1.7.0 and `warp-lang` 1.18.0 from PyPI: no fork clone
and no source build. It was run from scratch on two fresh pods, and both license reports are
identical. The fork sits behind `drape/scripts/setup_fork.sh`, an opt-in research env in
`.venv-fork`. Outside that script, the fork's name appears only in markdown records and in two raw
logs from the earlier license spike (`spike/fork_delta_raw.txt`, `spike/port.log`). No code, config
or install step references it. The license report for the default env is in RESULTS_NEWTON.md.
