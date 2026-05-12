# Milestone 2 Objective

## Purpose

This note narrows the broad hidden-layer idea into a simple working objective for
Milestone 2.

The old note remains a reference. This one is the practical target.

## Objective

Milestone 2 should prove one full trade-decision slice:

```text
HTF bias
LTF pullback
zone / PD touch
LTF trigger
trade
measure outcome
measure null cases
```

The goal is not to add many new event definitions yet.

The goal is to prove that the replay system can:

- read higher-timeframe context
- understand lower-timeframe pullback behavior
- detect location interaction such as zone or PD touch
- wait for a lower-timeframe trigger
- fire a trade
- let the trade resolve
- measure both trades and non-trades

## Five Layer Contracts

Milestone 2 should be organized around five contracts:

```text
Event Layer Contract
Context Layer Contract
Hypothesis Layer Contract
Trigger Layer Contract
Null Case Layer Contract
```

These are thinking and measurement boundaries. They keep raw observations,
interpretation, trade ideas, entry triggers, and backtest measurement separated.

## 1. Event Layer Contract

The event layer records what objectively happened and when it became known.

Events are observations, not strategy decisions.

Examples:

- STR high confirmed
- STR low confirmed
- BoS
- price enters a PD level
- price touches supply or demand

Every event should answer:

- what happened?
- on which timeframe?
- when did it become known?
- where is it anchored?
- what price or level does it refer to?
- is it causally safe?

## 2. Context Layer Contract

The context layer interprets events and recent bars into market state.

This is where noisy event history becomes working context.

Examples:

- HTF bias is bearish
- LTF is bullish
- LTF bullish move is a pullback inside HTF bearish context
- price is in premium
- price is near HTF supply

The context layer should answer:

- what is the current bias?
- what is the current leg?
- is price pulling back, continuing, reversing, or noisy?
- where is price relative to PD?
- what important zones or levels are nearby?

## 3. Hypothesis Layer Contract

The hypothesis layer turns context into a trade idea being watched.

Example:

```text
hypothesis: bearish_mitigation_candidate
source_tf: HTF
execution_tf: LTF
reason: HTF bearish + LTF bullish pullback
location_interest: supply / PD level
status: watching
```

The hypothesis layer should answer:

- what idea is active?
- why is it active?
- what timeframe created the idea?
- what timeframe should execute it?
- what would invalidate it?
- is it inactive, watching, armed, triggered, invalidated, or expired?

## 4. Trigger Layer Contract

The trigger layer turns a valid hypothesis into action.

Example:

```text
HTF bearish
LTF bullish pullback
price reaches supply / premium
LTF confirms bearish shift
trade fires
```

The trigger layer should answer:

- what exact condition fires the trade?
- what must happen before the trigger is valid?
- what cancels the trigger before entry?
- how is the trigger measured in backtest?

## 5. Null Case Layer Contract

The null case layer is mainly for measurement.

It makes sure the system measures not only trades, but also the moments where a
trade idea almost happened and then failed to complete.

Important cases:

- no hypothesis appeared
- hypothesis appeared but never armed
- setup armed but price never reached the zone
- price reached the zone but trigger never fired
- trigger fired and trade launched
- trade launched and completed
- trade won
- trade lost
- trade timed out

This keeps the denominator honest.

## Trade Launch Rule

Once the trade fires, the rocket has launched.

Do not call it back mid-air just because the thinking layer changes its mind.

After entry, the trade should resolve through preplanned rules:

- stop loss
- take profit
- timeout
- predefined management rule
- predefined invalidation rule

Recurrent thinking is useful before entry. After entry, it can introduce panic,
revenge behavior, and over-management.

Milestone 2 should make the bot calmer:

```text
think clearly
wait clearly
launch clearly
measure clearly
```

## Working Mentality

The bot does not need to remember everything forever.

It needs a bounded working memory:

- present state
- recent meaningful events
- recent higher-timeframe context
- active hypothesis
- invalidation level
- zone / PD interaction

The purpose of the hidden layers is clarity.

The bot should not be a nervous stream of reactions. It should build context,
form a hypothesis, wait for the trigger, launch the trade, and let the result
tell the truth.
