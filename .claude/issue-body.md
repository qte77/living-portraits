Thanks for how you handled this batch: catching the import regression before it merged, measuring our #33 claim on your own host instead of taking our word for it, and retracting your `wan2_7` and 720p comments when they didn't hold up.

**One thing we got wrong that isn't in any single PR: the pace.** 15 PRs and 20 issues, 34 of them inside two days, against a repo one person maintains. Six merged, eight issues resolved, three closed on premises that didn't survive — and seven more PRs existed only to be folded into #28 and #29. Even the good ones cost you a review and a port into your private tree. We've stopped. This issue puts everything in one place — pick what's useful, bin the rest.

## Four fixes in main

Four bugs we introduced are still in `main`. Each is small — the e2e fix is #37's +29/-1. We can revert instead if you'd rather; our read is that fix-forward is cheaper for you, since a revert needs the same review and the same private-tree port, done twice. Your call.

| | Fix | From |
|---|---|---|
| `tests/run_all.py:103` | `**kw` on the shim. `test_verify.py:36` passes `allow_module_level`, so `run_all.py` exits 1 without cv2 while pytest exits 0 — and `run_all.py:298`'s purpose-built skip never runs, because both `except` arms precede it. Your approval bench used pytest, so there was no way to see this. | #3 |
| `.github/workflows/e2e.yaml:79-86` | teardown for the backgrounded `http.server`. Fails only on a uv cache miss, at 300 s in the prune step — your diagnosis from the #29 review, and the reason #35 was red with a passing browser test. #37 has the fix and its run was a genuine cache miss, so that green is a controlled result. **One correction:** #37's commit message *and* the comment it adds both blame a 25-minute job timeout; it's a 5-minute prune timeout. Both want fixing. | #29 |
| `AGENTS.md:83` | *"It adds no writer"* isn't right — `live_view.py:63` passes `--policy` and the walker publishes `pose/<char>.json`. The code is fine (`--no-walker` at :181); the sentence isn't. | #29 |
| `runtime/capture_demo.py:607` | a discarded call left by an F841 fix. Worth knowing: nothing catches this shape — not `ruff --select ALL`, not pylint W0106. | #14 |

## Five more things we found auditing our own changes

Take any, all, or none.

**Nothing checks a paid clip.** `autogen.py` never imports `verify`, and `verify_clip` has no production callers; where it is used it compares `clip_frames[0]` and `[-1]` (`verify.py:495`). We reproduced a melt-then-snap passing at SSIM 1.000.

**The suite can't fail on an import spelling.** `conftest.py:43-51` inserts root + `runtime/` + `director/` + `pipeline/`, so both the bare and the package spelling resolve no matter which entry point a test came from — which is why the #8 change you caught by eye was invisible to 338 green tests. Running each entry point as its own process, the way it actually starts, takes ~5 s and would have failed. Separately, a probe that imports the walker's PURE set with only the stdlib available takes ~70 ms, and nothing asserts that contract today.

**The lint gate covers the parked player, not the live one.** `ruff check .` is 90 and the CI list is 0; `ARCHITECTURE.md:198-199` marks `_preview_graph.py` LIVE and `player.py` Disabled. Three of the 90 are in `_preview_graph.py` itself.

**`scripts/unstick.py:189`** writes `autogen_poses.json` outside the autogen lock while `lp-gen` runs every 20 min, reads `store` once before a multi-minute loop, and `_record_pose` drops `extra_links`.

**Two doc lines.** `ROADMAP.md:169` and `video_graph.py:18` call Seraphina single-pose; the built graph has 4 nodes / 19 edges, 3 from the bedtime chain — *"no second daytime pose"* is the accurate version. And `ARCHITECTURE.md:237` explains the panels not racing by a per-character path split, but both cyclers run in one `main()` — the property holds, that's just not the reason.

## #31 and #32 need nothing; #33 needs three fixes

**#31 and #32** — your corrections beat our proposals, and #32's 720p premise was ours to begin with. **#33** we want to extend, not argue with: your reframe to *"cheaper and different, not free,"* scored per behaviour class at panel size, is the right one. Three plumbing bugs to fold in: `maxx` has no `motion` key, so `_bake_liveportrait.py:447-449` exits for one of two live characters; the bake's filename stem can't match the live glob at `video_graph.py:403`; and it registers into the parked `clip_graph` rather than the live `video_graph`.

## What this looks like from our side

Worth stating plainly, so you can calibrate what we are good for and what to discount.

We cannot see the installation. No host access and no proxy credentials, so nothing about live behaviour, real media, credit spend or `_bakeoff/` is checkable by us — only what is in the repo. When we make a claim about the running system it is inference, and yours beats ours by default. We also cannot land anything permanently: the public repo is generated, so every change we make is provisional until you port it, which is a real per-PR cost and should shape how many we send.

We generate faster than one person can review. That is the root of the pace problem and it does not self-correct, which is why we have capped ourselves below rather than promising to be careful. And our verification is only as good as our local environment — the #8 regression was invisible to us because the suite puts every entry point's import path on `sys.path` at once, so an import spelling that only works from one entry point still passes there. We now run a bench that reproduces both `main` bugs above from a clean tree, but the general point stands: a green run here is not evidence about your host.

Where we are useful is reading the whole tree at once, checking documentation against code, reproducing from a bare clone, and auditing our own output — most of the list above came from that last one. Where we have been unreliable is confident claims drawn from documents rather than from execution; three of our issues died that way. If something we write sounds certain and is not cited to a command we ran, treat it as a guess.

## Going forward

Your #20 rules, which we should have followed from the start: land the unblocking fix alone then batch, three lines is a PR, file an issue when the decision is yours, say so when CI is red. Plus one you shouldn't have had to ask for: **at most two open PRs from us, and never more in a week than you merged the week before.**

On our side: local guards now refuse pushes and PRs to this remote, and a pre-flight bench runs both documented runners and both lint scopes — it reproduces rows 1 and 2 of the table above from a clean tree. If any of this is the wrong shape, say so; it is our read, not a settled arrangement.

## What should we send, and in what order?

Tick anything you want and leave the rest. We won't open a PR or file an issue until you answer, and "nothing" is a real answer.

- [ ] The four fixes above, one PR each
- [ ] Restore 5 truncated PR bodies (#19, #21, #22, #27, #29) — body edits only, no notification, no port
- [ ] Paid-clip QA gap (nothing checks a paid clip), as an issue
- [ ] Run each entry point as its own process in CI, and/or the stdlib-purity probe
- [ ] The two doc corrections (Seraphina pose count, panel-race explanation)
- [ ] Cross-character edges, as an issue with a branch — 2 lines in `video_graph.py` plus dropping a dead clause in the walker's edge filter builds walk-safe at 20 nodes / 100 edges (98 today, +2), **0 credits** on placeholder media. It changes production walker behaviour, so it's a decision for you, not a PR.
- [ ] Nothing — we'll keep the list and stay out of the way

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
