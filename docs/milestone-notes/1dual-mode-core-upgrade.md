# Dual Mode Core Upgrade

## Purpose

This note captures the **current dual-mode replay architecture** after the core
upgrade is working.

Use it as an impact map:

- if I change a replay rule, what backend object moves?
- if I change a chart behavior, what frontend path moves?
- if I change an event family, what parts of the system will feel it?

This is about the replay app under:

- [app.py](/Users/aimliu/Library/CloudStorage/OneDrive-Personal/_CODE/Python/py-systemC-studies/py-ULTRA-B/src/ultrab/replayer/app.py)
- [replay_session.py](/Users/aimliu/Library/CloudStorage/OneDrive-Personal/_CODE/Python/py-systemC-studies/py-ULTRA-B/src/ultrab/replayer/replay_session.py)
- [config.yaml](/Users/aimliu/Library/CloudStorage/OneDrive-Personal/_CODE/Python/py-systemC-studies/py-ULTRA-B/src/ultrab/replayer/config.yaml)
- [index.html](/Users/aimliu/Library/CloudStorage/OneDrive-Personal/_CODE/Python/py-systemC-studies/py-ULTRA-B/src/ultrab/replayer/templates/index.html)

## Current Scope

Dual mode means:

- one symbol only
- two timeframes only
- same asset on both charts
- lower timeframe chart on top
- higher timeframe chart on bottom
- one shared chronological event log

This is **not**:

- cross-symbol mode
- arbitrary TF pairing
- one TF painted on top of another TF inside the same candle canvas

## Fixed Timeframe Combos

The current allowed dual combos are locked in config:

- `1H / 1D`
- `15M / 4H`
- `5M / 1H`
- `1M / 15M`

They live in [config.yaml](/Users/aimliu/Library/CloudStorage/OneDrive-Personal/_CODE/Python/py-systemC-studies/py-ULTRA-B/src/ultrab/replayer/config.yaml) under:

```yaml
dual_mode:
  combos:
```

### Impact if changed

If a combo is added/renamed/removed:

- config dropdown options change
- dual session creation validation changes
- frontend selected combo behavior changes
- rewind mapping still assumes lower/higher are clean multiples

So new combos should still be neat lower->higher multiples unless rewind and
higher-bar mutation logic are revisited.

## Master Clock

The lower timeframe is the **master clock**.

Meaning:

- one replay step = one new lower-TF closed bar becomes known
- `Back 1` means one lower-TF step back
- rewind rebuild targets are ultimately resolved against the lower-TF timeline

### Impact if changed

If master clock changes, it affects:

- `DualReplaySession.step()`
- `DualReplaySession.rewind_one()`
- `DualReplaySession.rewind_to_time()`
- higher-bar mutation timing
- both chart rewind-pick semantics
- event log ordering expectations

This is one of the highest-impact architecture levers.

## Backend Architecture

## Session Objects

There are now two replay session types in
[replay_session.py](/Users/aimliu/Library/CloudStorage/OneDrive-Personal/_CODE/Python/py-systemC-studies/py-ULTRA-B/src/ultrab/replayer/replay_session.py):

- `ReplaySession`
  - single timeframe
- `DualReplaySession`
  - dual timeframe

The Flask entry point in
[app.py](/Users/aimliu/Library/CloudStorage/OneDrive-Personal/_CODE/Python/py-systemC-studies/py-ULTRA-B/src/ultrab/replayer/app.py)
chooses which one to build in:

- `POST /api/replay/session`

based on:

- `mode`
- `dual_combo`

## DualReplaySession Data Model

`DualReplaySession` owns:

- `lower_bars`
- `higher_bars`
- `lower_marker`
- `higher_marker`
- `current_lower_index`
- `current_higher_index`
- `visible_events`
- `lower_start_index`
- `higher_start_index`
- `lower_label`
- `higher_label`
- `master_tf`

### Important design choice

Both marker engines are **independent by timeframe**:

- lower TF events are triggered only by lower TF bars
- higher TF events are triggered only by higher TF bars

There is no event-layer cross-triggering.

### Impact if changed

If the event layer becomes cross-timeframe aware, it would affect:

- marker causality assumptions
- event log trustworthiness
- replay determinism
- future trade-layer separation

That boundary should stay strict unless the whole model is intentionally
reworked.

## Higher-TF Mutation

The higher chart mutates live between higher-TF closes.

Current implementation:

- `DualReplaySession._current_higher_partial_bar()`

builds an in-progress higher-TF candle from the lower-TF segment inside the
current higher-TF bar.

So visually:

- higher-TF `open` stays fixed
- higher-TF `high/low/close` mutate as lower-TF bars arrive

But event confirmation still happens only when a real higher-TF bar closes:

- `DualReplaySession._process_lower_step()`

### Impact if changed

If partial higher-bar mutation changes, it affects:

- bottom chart visual truth
- dual rewind intuition
- “watch the context forming” workflow

If higher-TF events are allowed to fire before higher-TF close, that is a much
bigger semantic change and would affect the entire causal contract.

## Event Serialization Contract

Shared helpers:

- `_serialize_bar(...)`
- `_serialize_event(...)`

currently normalize replay payloads for both single and dual mode.

Serialized event payload currently includes:

- `tf`
- `tier`
- `event_code`
- `event_name`
- `bar_event`
- `event_type`
- `side`
- `decision_ts`
- `anchor_ts`
- `price`

BoS currently may also include:

- `level_ts`
- `level_price`
- `level_side`

### Impact if changed

If event schema changes:

- event log rendering changes
- copy-log output changes
- marker filtering by timeframe changes
- future overlay rendering may break

This payload is now a central contract between engine and UI.

## Event Ordering

Dual event log is merged inside:

- `DualReplaySession._process_lower_step()`

Current rule:

- sort by `decision_ts`
- if timestamps tie:
  - higher TF first
  - lower TF second

### Why it matters

This rule is not just cosmetic.
It prepares the ground for future trade-layer reasoning where higher-TF context
should be seen first.

### Impact if changed

Changing tie-break order affects:

- replay readability
- copied logs
- future sequence-driven logic built on event order

## Frontend Architecture

## Single vs Dual Mode UI

Frontend mode selection lives in
[index.html](/Users/aimliu/Library/CloudStorage/OneDrive-Personal/_CODE/Python/py-systemC-studies/py-ULTRA-B/src/ultrab/replayer/templates/index.html).

Current controls:

- `Mode`
- `Symbol`
- `Timeframe`
- `Dual Combo`
- `Cursor start time`

Current rule:

- in `single` mode:
  - timeframe selector is visible
- in `dual` mode:
  - timeframe selector is hidden
  - dual combo selector is shown

Handled by:

- `updateModeUi(...)`

### Impact if changed

If UI mode rules change:

- fetch payload shape changes
- user workflow changes
- dual session creation assumptions change

## Chart Panes

The frontend now uses a stacked chart layout:

- top pane = lower TF
- bottom pane = higher TF

The DOM is split into:

- `topPane`
- `bottomPane`
- `topChart`
- `bottomChart`

and pane state is held in:

- `paneStates.top`
- `paneStates.bottom`

Each pane owns:

- chart instance
- candlestick series
- resize observer
- marker primitive
- latest visible bars
- latest hover time
- latest hover X
- current detected price precision

### Impact if changed

If pane count or pane responsibility changes:

- render path changes
- tooltip path changes
- rewind guide path changes
- marker routing changes

## Snapshot Rendering

Main frontend renderer:

- `applySnapshot(snapshot, options = {})`

Current rule:

- single mode:
  - top chart only
  - render `snapshot.bars`
- dual mode:
  - top chart uses `snapshot.lower_bars`
  - bottom chart uses `snapshot.higher_bars`
  - events are filtered by `tf` and routed to native pane only

Native marker routing rule:

- lower TF events render on lower chart only
- higher TF events render on higher chart only

### Impact if changed

If native events are ever projected cross-pane:

- marker routing changes
- collision policy changes
- event-to-pane assumptions break

This would be a deliberate architecture change, not a small tweak.

## Marker System

Marker visuals are configured in
[config.yaml](/Users/aimliu/Library/CloudStorage/OneDrive-Personal/_CODE/Python/py-systemC-studies/py-ULTRA-B/src/ultrab/replayer/config.yaml):

- `str`
- `str_bos`
- `itr`
- `ltr`

The frontend uses:

- `buildSeriesMarkers(...)`
- `renderMarkersForPane(...)`

Collision rule is currently:

```yaml
collision_policy: priority_hide
priority:
  - ltr
  - itr
  - str_bos
  - str
```

This affects only **chart visibility**, not event log truth.

The event log keeps everything.

### Impact if changed

If priority or collision behavior changes:

- chart readability changes
- perceived event truth on chart changes
- but event log remains the source of full truth

## Rewind Model

## Core Rule

Rewind is **step-level rebuild**, not event-by-event undo.

That is why multi-event bars remain sane.

## Implemented Paths

Backend:

- `rewind_one()`
- `rewind_to_time(...)`

Current rebuild rule:

- reset state
- replay forward to target point
- rebuild bars, markers, and event log

This is safer than trying to surgically remove “the last event”.

## Rewind-Pick on Charts

Current rule:

- top/lower chart click:
  - rewind to just before selected lower-TF bar
- bottom/higher chart click:
  - rewind to just before selected higher-TF bar open

Frontend support lives in:

- `setRewindPickMode(...)`
- `updateRewindGuide(...)`
- `nearestBarTimeFromHover(...)`
- `rewindToPickedBar(...)`

Event log rewind rule:

- after rewind, only events with `decision_ts < target_time` should remain

### Impact if changed

If rewind semantics change:

- both chart interactions change
- event log meaning changes
- dual mutation intuition changes

This is another high-impact lever.

## Shared Overlay Contract

The first shared overlay family is now only a placeholder in config:

```yaml
shared_overlays:
  supply_demand_block:
    enabled: false
    projection: higher_to_lower
    duplicate_on_both_charts: true
```

This is not rendered yet.

But the intended contract is already clear:

- higher TF is the source
- lower TF receives projection
- overlay is duplicated on both charts

### Impact if changed

If shared overlay families become real:

- backend snapshot will need overlay payloads
- frontend pane renderers will need overlay primitives
- rewind must rebuild overlays consistently

## What Is Safe To Change

Relatively safe, localized changes:

- marker colors/text/shapes
- button icon swaps
- chart tooltip wording
- copy-log formatting
- dual combo default selection
- placeholder overlay style config

## What Has Bigger Blast Radius

High-impact changes:

- master clock definition
- event schema shape
- event ordering tie-break
- higher-TF pre-close event firing
- cross-timeframe event triggering
- projecting native pivot markers across panes
- rewind semantics
- arbitrary timeframe pairing

Those touch both code and mental model.

## Current Mental Model

The clean way to think about the current codebase is:

- lower TF drives time
- higher TF mutates visually but confirms causally on its own closes
- event engines stay pure to their own timeframe
- event log merges both worlds chronologically
- native pivot markers stay on native charts
- rewind rebuilds the whole world, not just one event

If a future change violates one of those lines, it is probably not a patch.
It is an architecture revision.

- one symbol
- fixed timeframe pair
- lower TF master clock
- lower chart on top
- higher chart on bottom
- native pivots stay native
- shared overlays project down
- event layer stays timeframe-pure
- trade layer handles cross-timeframe reaction later
