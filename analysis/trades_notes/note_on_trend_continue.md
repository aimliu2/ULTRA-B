# Trend Continuation Notes

## 2025-06-04T21:45:00Z — SA entry, strong trend continuation

**Case**: `D.watch_pathSA`, SHORT, timeout `+0.353R`, risk 15.0 pips, `watch_extreme`, `counter_ichoch_immediate`.

**Observation**: This entry occurred in the absence of a shallow Phase B setup. Price was in strong trend continuation — no meaningful counter-pullback depth was established before `D.watch` opened and the iChoCh fired. The SA path fired on the iChoCh alone without structural evidence of a genuine pullback attempt.

**Open design question**: Should `E.pullback_developing` persist into the 90–51% premium range (wide HTF PD range) without requiring a Phase B or `C.pullback` structure first? In a strong trend, price may remain in the upper premium zone and still satisfy the `E.pullback_developing` gate mechanically, but there is no shallow-B or pullback-depth evidence to anchor the fade.

**Consideration**: For wide HTF PD ranges, consider whether to require a `shallow.B` or `C.pullback` node before permitting `D.watch` to open. This would filter out trend-continuation SA entries where the pullback depth is insufficient to justify a counter-thesis fade.

**Status**: Deferred design decision. Do not implement until Phase B entry engine is built and tested. Revisit after Phase B range-depth evidence is available.

---

## 2024-10-16T00:15:00Z — SA entry, strong bearish trend

**Case**: `D.watch_pathSA`, LONG, timeout `-0.273R`, risk 15.0 pips, `watch_extreme`, `counter_ichoch_immediate`.

**Observation**: Strong bearish macro trend context. Phase D counter-trade (long fade) was against the prevailing direction and got easily rekt — price had no real bullish structural commitment backing the entry; the iChoCh fired mechanically but the thesis never developed. Loss avoided only by timeout, not by target reach.

**Pattern**: In a strong trend, shallow pullback trades (pro-trend, Phase B shallow) would shine here. A counter-thesis Phase D fade in a deep bearish move is low-probability — the D.watch iChoCh is the weakest possible evidence when the dominant flow is still bearish.

---

## 2024-05-10T03:45:00Z — C2 entry, bullish trend continuation, shallow pullback

**Case**: `D.watch_pathC2`, SHORT, timeout `-0.133R`, risk 15.0 pips, `watch_extreme`, `d_watch_mss_plain`.

**Observation**: Genuine loss due to bullish trend continuation. Price made only a shallow counter-pullback before the `D.watch → C.pullback` MSS transition fired. The C2 entry is a transition-bar fade against the dominant bullish flow — in strong trend continuation with no meaningful depth, this is a low-probability counter trade. The short barely survived to timeout without hitting target.

**Pattern**: Same root problem as the SA trend-continuation cases. Shallow pullback in a strong trend feeds an MSS transition that C2 immediately fires on — but the structural story is thin. A shallow Phase B track (pro-trend) would have the edge here, not a counter-thesis C2 fade.

**Additional note**: Cold start at `2024-05-10T00:00:00Z` could not relocate to the correct node for this episode — see `analysis/restart_self_relocation.md`.

---

## 2024-03-27T12:15:00Z — C2 entry, bearish trend continuation

**Case**: `D.watch_pathC2`, LONG, loss `-1R`, risk 17.9 pips, `watch_extreme`, `d_watch_mss_plain`.

**Observation**: Genuine loss due to bearish trend continuation. The `D.watch → C.pullback` MSS transition fired a long counter-trade into a dominant bearish move. No meaningful bullish structural recovery — hit SL.

**Pattern**: Same class as the other trend-continuation losses. Counter-thesis Phase D/C fade in a strong trend without shallow Phase B depth confirmation.

---

---

## 2021-01-13T17:30:00Z + 2021-01-14T07:00:00Z — Path B, double punishment in bearish trend

**Cases**:
- `2021-01-13T17:30:00Z` LONG skipped `late_entry_risk_too_wide`, 41.9 pips — would have been liquidity swept immediately if opened.
- `2021-01-14T07:00:00Z` LONG accepted, loss `-1R`, 15.0 pips — re-entered the same zone, got rekt again.

**Observation**: Both are counter-trend long trades inside a bearish macro context. The first would have been swept by liquidity before price could breathe. The second re-entered after the ITR armed inside the same HTF S/D zone — and still lost. Two attempts, same zone, same counter-trend direction, same outcome. Classic double-punishment in a trend-continuation regime.

**Pattern**: Path B ITR arming provides better geometry than SA, but it cannot fix the fundamental problem — a counter-thesis long in a bearish trend is low-probability regardless of the zone quality. The zone existed, the ITR armed correctly, the iChoCh fired — all mechanics were valid, but the regime was wrong.

---

## Conclusion — Phase D integrity vs regime

Phase D path mechanics (SA, C2, B) are all **structurally correct** — geometry, SL anchoring, trigger sequencing, and budget rules are working as designed.

The recurring loss pattern is **not a path integrity failure** — it is a regime mismatch. Phase D counter-thesis trades (fading the dominant trend) have low probability in strong trend-continuation regimes. The paths fire mechanically correct entries into the wrong context.

**When Phase D counter trades work**: genuine reversal setups where the HTF structure is at an extreme, pullback depth is meaningful, and the dominant trend is losing momentum. These are the cases where SA/C2/B earn their edge.

**When they fail**: shallow pullbacks in strong trends, re-entries into swept zones in trend continuation, counter-longs in bearish macro and counter-shorts in bullish macro without structural exhaustion evidence.

**Fix direction**: upstream regime filtering — require pullback depth gate, HTF exhaustion evidence, or shallow Phase B confirmation before permitting `D.watch` to open in wide premium/discount ranges. Deferred until Phase B entry engine is built.
