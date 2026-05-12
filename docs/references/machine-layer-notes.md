# Hidden Layers / Thinking Layers

## Purpose

This note captures the current V3 intention for SystemC.

The replay engine is not only for visual replay. It is the time machine for
answering:

- what did the market reveal at each moment?
- what would the bot have known at that moment?
- what would the bot have assumed, waited for, rejected, or traded?

The goal is to bridge the replay/event engine into a trade layer without forcing
the trade layer to consume raw event order directly.

## Current Intention

SystemC V3 is a backtester system built around a replay engine.

The replay app should let me see what happened in time and compare that against
how the bot would have acted if it were trading live.

That means the system needs more than:

- bars
- events
- trade execution

It also needs one or two hidden interpretation layers between events and trades.
Those layers are the bot's working context.

## Why Raw Event Order Is Not Enough

Event logs do not always appear in a clean pattern order such as:

```text
C01 -> C02 -> C01 -> trade
```

The same narrative can repeat in different orders, with different timing, and
with extra noisy STR events in between.

So the trade layer should not depend on a perfect fixed event sequence.

Raw events are observations. They are not the strategy by themselves.

## Candidate Funnel

The rough V3 funnel is:

```text
Bars
  -> Event Layer
  -> Context / Interpretation Layer
  -> Hypothesis Layer
  -> Setup / Trigger Layer
  -> Trade Execution Layer
  -> Outcome / Measurement Layer
```

### Event Layer

The event layer records what objectively happened and when it became known.

Examples:

- STR high confirmed
- STR low confirmed
- BoS
- price enters a PD level
- price touches supply or demand

Events should stay causal and timestamped.

### Context / Interpretation Layer

The context layer compresses many raw observations into the current market state.

Examples:

- higher timeframe bias is bearish
- lower timeframe is bullish
- lower timeframe bullish move is a pullback inside higher timeframe bearish context
- price is in premium
- price is near higher timeframe supply
- recent STR events are noisy and should not all be remembered equally

This is the first hidden/thinking layer.

### Hypothesis Layer

The hypothesis layer turns interpreted context into a trade idea being watched.

Example:

```text
hypothesis: bearish_mitigation_candidate
source_tf: higher timeframe
execution_tf: lower timeframe
reason: HTF bearish + LTF bullish pullback
location_interest: supply / PD level
status: watching
```

This layer should know what idea is active, why it is active, and what would
invalidate it.

### Setup / Trigger Layer

The setup/trigger layer decides when an active hypothesis becomes actionable.

Example:

```text
HTF bearish
LTF bullish pullback
price reaches supply / premium
LTF confirms bearish shift
trade signal fires
```

This is where waiting becomes action.

### Trade Execution Layer

The trade layer should consume a clean signal, not raw event noise.

It should decide:

- entry
- stop
- target
- sizing
- cancellation
- management

### Outcome / Measurement Layer

This layer is required so the system can measure both trades and non-trades.

Important null cases:

- hypothesis never appeared
- hypothesis appeared but price never reached the location
- price reached the location but trigger never fired
- trigger fired but entry was invalidated
- trade entered and won
- trade entered and lost

Without null cases, backtest results can become misleading because the denominator
is missing.

## Two Possible Decision Styles

## 1. Confidence / Rating

One path is:

```text
event + context features -> confidence score -> trade
```

This could later become ML.

The risk is that it can become vague too early unless the score has a clear
meaning.

## 2. Checklist / Setup Logic

The other path is:

```text
conditions observed -> setup armed -> trigger -> trade
```

This is closer to how I manually wait for a trade setup.

For V3, this is probably the better first implementation path.

The checklist should still be measurable and machine-readable so it can become
features for a confidence model later.

Example state:

```text
htf_bias = bearish
ltf_state = bullish_pullback
price_location = htf_supply
pd_location = premium
mitigation_touch = true
entry_trigger = ltf_shift_down
```

## Attention Span Constraint

The bot should not remember everything forever.

It does not need every STR event or every bar high/low from the full dataset.

It needs bounded working memory:

- present state
- recent meaningful events
- maybe the previous 500 higher-timeframe bars
- active structure context
- active hypothesis
- invalidation level
- recent location/zone state

The hidden layer should compress noisy event history into usable state.

Example:

```text
raw STR events:
C01, C02, C01, C01, BoS, C02, C01

compressed context:
ltf_bias = bullish
last_structure_break = bullish
current_pullback_depth = 62%
nearest_htf_supply = 1.08420
hypothesis = bearish_mitigation_candidate
```

This is the practical meaning of attention span.

## Key Distinction To Clarify First

Before defining more events, clarify:

```text
What is an event?
What is an interpretation?
What is a hypothesis?
What is a trigger?
```

Do not mix these too early.

Example:

- `C01 STR high confirmed` is an event.
- `HTF bearish` is interpretation.
- `bearish mitigation candidate` is a hypothesis.
- `LTF bearish shift inside supply` is a trigger/setup condition.
- `enter short` is trade execution.

## Contracts To Define Before More Events

## Event Contract

Every event should answer:

- what happened?
- on which timeframe?
- when did it become known?
- where is it anchored on the chart?
- what price or level does it refer to?
- is it causally safe?

Candidate fields:

```text
tf
event_type
tier
side / direction
decision_ts
anchor_ts
price
level_ts
level_price
causal_availability
```

## Context Contract

The context layer should answer:

- what is the current bias per timeframe?
- what was the last meaningful structure break?
- what is the current leg?
- is price pulling back, continuing, reversing, or noisy?
- where is price relative to premium/discount?
- what zones or levels are active nearby?

## Hypothesis Contract

The hypothesis layer should answer:

- what trade idea is active?
- why is it active?
- which timeframe created the idea?
- which timeframe should execute it?
- what state is it in?
- what invalidates it?

Candidate state:

```text
inactive
watching
armed
triggered
invalidated
expired
```

## Trigger Contract

The trigger layer should answer:

- what exact condition fires the trade?
- what must happen before the trigger is valid?
- what cancels the trigger?
- how is the trigger measured in backtest?

## Null Case Contract

Every checklist and hypothesis should be measurable even when no trade happens.

This means the system should log the lifecycle:

```text
hypothesis_created
setup_armed
setup_touched
trigger_missing
trigger_fired
trade_entered
trade_skipped
trade_invalidated
trade_won
trade_lost
```

## Current Recommendation

Do not add many new event definitions yet.

First build one complete vertical slice:

```text
HTF bias
LTF pullback
zone / PD touch
LTF trigger
trade
outcome
null cases
```

The existing event layer can feed this first slice.

If the slice reveals missing information, then define the next event type because
the need is proven.

So the next milestone should probably be:

```text
same events -> better interpretation -> measurable hypotheses
```

The replay engine already gives time truth.

The next important thing is to make the bot's belief state visible at every
replay step.
