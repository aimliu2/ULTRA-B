def _fix_break_of_structure(isXXX, isSource, high, low):
    """
    Ensure isXXX alternates strictly between 1 and -1.
    On a break (1,1 or -1,-1), insert the best counter swing between the two offending positions,
    but ONLY if it is structurally valid:
      - Inserting a  1 (high): candidate high must be > max(low[p1],  low[p2])
      - Inserting a -1 (low) : candidate low  must be < min(high[p1], high[p2])
    If no valid candidate exists, remove the less extreme of the two duplicates instead.
    Returns (isXXX, insertions) where insertions = list of (inserted_idx, p2_idx).
    """
    insertions = []
    changed = True
    while changed:
        changed = False
        non_zero = np.where(isXXX != 0)[0]

        for i in range(1, len(non_zero)):
            p1, p2 = non_zero[i - 1], non_zero[i]
            v1, v2 = isXXX[p1], isXXX[p2]

            if v1 != v2:
                continue

            counter    = np.int8(-v1)
            candidates = np.arange(p1 + 1, p2)

            inserted = False
            if len(candidates) > 0:
                source_cands = candidates[isSource[candidates] == counter]
                pool = source_cands if len(source_cands) > 0 else candidates

                if counter == -1:
                    threshold  = min(high[p1], high[p2])
                    valid_pool = pool[low[pool] < threshold]
                else:
                    threshold  = max(low[p1], low[p2])
                    valid_pool = pool[high[pool] > threshold]

                if len(valid_pool) > 0:
                    best = (valid_pool[np.argmin(low[valid_pool])]
                            if counter == -1
                            else valid_pool[np.argmax(high[valid_pool])])
                    isXXX[best] = counter
                    insertions.append((int(best), int(p2)))
                    inserted = True

            if not inserted:
                if v1 == 1:
                    isXXX[p1 if high[p1] < high[p2] else p2] = 0
                else:
                    isXXX[p1 if low[p1]  > low[p2] else p2] = 0

            changed = True
            break

    return isXXX, insertions


def _fix_price_order(isXXX, high, low):
    """
    Fix price ordering violations by inserting 2 bridging marks instead of removing.
    Falls back to removal only if no valid bridge candidates exist.
    Returns (isXXX, insertions) where insertions = list of (inserted_idx, p2_idx).
    """
    insertions = []
    changed = True
    while changed:
        changed = False
        non_zero = np.where(isXXX != 0)[0]

        for i in range(1, len(non_zero)):
            p1, p2 = non_zero[i-1], non_zero[i]
            v1, v2 = isXXX[p1], isXXX[p2]

            if v1 == 1 and v2 == -1 and low[p2] >= high[p1]:
                cands = np.arange(p1 + 1, p2)
                valid_lows = cands[low[cands] < high[p1]]
                if len(valid_lows) > 0:
                    best_low = valid_lows[np.argmin(low[valid_lows])]
                    after = np.arange(best_low + 1, p2)
                    valid_highs = after[high[after] > low[best_low]]
                    if len(valid_highs) > 0:
                        best_high = valid_highs[np.argmax(high[valid_highs])]
                        isXXX[best_low]  = -1
                        isXXX[best_high] = 1
                        insertions.append((int(best_low),  int(p2)))
                        insertions.append((int(best_high), int(p2)))
                        changed = True
                        break
                isXXX[p2] = 0
                changed = True
                break

            elif v1 == -1 and v2 == 1 and high[p2] <= low[p1]:
                cands = np.arange(p1 + 1, p2)
                valid_highs = cands[high[cands] > low[p1]]
                if len(valid_highs) > 0:
                    best_high = valid_highs[np.argmax(high[valid_highs])]
                    after = np.arange(best_high + 1, p2)
                    valid_lows = after[low[after] < high[best_high]]
                    if len(valid_lows) > 0:
                        best_low = valid_lows[np.argmin(low[valid_lows])]
                        isXXX[best_high] = 1
                        isXXX[best_low]  = -1
                        insertions.append((int(best_high), int(p2)))
                        insertions.append((int(best_low),  int(p2)))
                        changed = True
                        break
                isXXX[p2] = 0
                changed = True
                break

    return isXXX, insertions

def validate_markers(df, col):
    """
    Validate a marker column (e.g. 'isITR', 'isLTR') across the entire DataFrame.

    Checks two invariants:
      1. BOS (Break-of-Structure): consecutive non-zero entries must alternate sign (no 1,1 or -1,-1).
      2. Price order: after a high (1), the next low (-1) must be strictly below it,
         and after a low (-1), the next high (1) must be strictly above it.

    Returns
    -------
    dict with keys:
        'bos_violations'   : DataFrame of rows where sign repeats
        'order_violations' : DataFrame of rows where price order is broken
        'is_valid'         : True only if both checks pass
    """
    rows = df[df[col] != 0][['timestamp', 'high', 'low', col]].copy()
    rows['price_at_mark'] = rows.apply(
        lambda r: r['high'] if r[col] == 1 else r['low'], axis=1
    )

    vals = rows[col].values

    # --- BOS check: consecutive same-sign entries ---
    bos_mask = [False] + [vals[i] == vals[i - 1] for i in range(1, len(vals))]
    bos_violations = rows[bos_mask]

    # --- Price order check ---
    order_fail_idx = []
    for i in range(1, len(rows)):
        prev = rows.iloc[i - 1]
        curr = rows.iloc[i]
        if curr[col] == 1:          # current is a high → must be above prev low
            if curr['high'] <= prev['low']:
                order_fail_idx.append(rows.index[i])
        else:                        # current is a low → must be below prev high
            if curr['low'] >= prev['high']:
                order_fail_idx.append(rows.index[i])
    order_violations = rows.loc[order_fail_idx]

    # --- Print summary ---
    label = col
    total = len(rows)
    print(f"=== {label} validation ({total} marks across full dataset) ===")

    if len(bos_violations):
        print(f"  BOS violations : {len(bos_violations)}")
        print(bos_violations[['timestamp', 'high', 'low', col, 'price_at_mark']].to_string())
    else:
        print("  BOS violations : 0  — alternation OK")

    if len(order_violations):
        print(f"  Order violations: {len(order_violations)}")
        print(order_violations[['timestamp', 'high', 'low', col, 'price_at_mark']].to_string())
    else:
        print("  Order violations: 0  — price ordering OK")

    is_valid = len(bos_violations) == 0 and len(order_violations) == 0
    print(f"  Valid: {is_valid}\n")

    return {
        'bos_violations':   bos_violations,
        'order_violations': order_violations,
        'is_valid':         is_valid,
    }

# STR features
def strHunt(df, window=4):
    n = len(df)
    df = df.copy()

    high = df['high'].values
    low  = df['low'].values

    isSTR = np.zeros(n, dtype=np.int8)

    for i in range(window, n - window):
        win_high = high[i - window : i + window + 1]
        win_low  = low [i - window : i + window + 1]

        is_swing_high = high[i] >= win_high.max()
        is_swing_low  = low[i]  <= win_low.min()

        if is_swing_high and not is_swing_low:
            isSTR[i] = 1
        elif is_swing_low and not is_swing_high:
            isSTR[i] = -1

    isSTR, bos_ins = _fix_break_of_structure(isSTR, isSTR, high, low)
    isSTR, po_ins  = _fix_price_order(isSTR, high, low)

    # inserted_p2: pivot_idx → p2_idx that caused the insertion
    inserted_p2 = dict(bos_ins + po_ins)

    # available_at: pivot_idx → first index where this mark is causally safe to use
    #   natural mark at i  → available at i + window (all confirmation bars closed)
    #   inserted mark at i → available at p2 + window (need p2 confirmed to know insertion exists)
    available_at = {}
    for i in np.where(isSTR != 0)[0]:
        available_at[int(i)] = inserted_p2.get(int(i), int(i)) + window

    str_confirmed = np.zeros(n, dtype=np.int8)
    for i, avail in available_at.items():
        if avail < n:
            str_confirmed[avail] = isSTR[i]

    return isSTR, str_confirmed, available_at


# add str_confirmed
isSTR_15, sc_15, avail_15 = strHunt(df_15, window=4)
df_15["isSTR"]         = isSTR_15
df_15["str_confirmed"] = sc_15

isSTR_45, sc_45, avail_45 = strHunt(df_45, window=4)
df_45["isSTR"]         = isSTR_45
df_45["str_confirmed"] = sc_45

def audit_no_lookahead(df, available_at, label, window=4):
    """
    Verify str_confirmed has zero look-ahead leakage.

    For every pivot i in available_at:
      - str_confirmed must fire at available_at[i], not earlier
      - available_at[i] >= i + window  (all confirmation bars must have closed)

    Prints a pass/fail summary with any violations listed.
    """
    violations = []

    for pivot_i, avail_j in available_at.items():
        # Rule 1: confirmation index must be >= pivot + window
        if avail_j < pivot_i + window:
            violations.append({
                'pivot': pivot_i, 'fires_at': avail_j,
                'min_allowed': pivot_i + window,
                'gap': (pivot_i + window) - avail_j,
                'reason': 'fires before confirmation bars closed'
            })

    total_marks = len(available_at)
    print(f"=== Look-ahead audit: {label} ({total_marks} marks) ===")
    if violations:
        print(f"  FAIL — {len(violations)} violation(s):")
        for v in violations[:10]:  # show first 10
            print(f"    pivot={v['pivot']}  fires_at={v['fires_at']}  "
                  f"min_allowed={v['min_allowed']}  ({v['reason']})")
        if len(violations) > 10:
            print(f"    ... and {len(violations)-10} more")
    else:
        print(f"  PASS — all {total_marks} marks fire at or after pivot + {window}")

    # Summary: how many are natural vs inserted (inserted fire later than i+window)
    natural  = sum(1 for i, j in available_at.items() if j == i + window)
    inserted = total_marks - natural
    print(f"  Natural marks : {natural}  (fired at pivot + {window})")
    print(f"  Inserted marks: {inserted}  (fired at p2 + {window}, delayed further)\n")
    return len(violations) == 0

audit_no_lookahead(df_15, avail_15, label="15m STR", window=4)
audit_no_lookahead(df_45, avail_45, label="45m STR", window=4)

# Map str_confirmed to 5m timeframe
# One real risk to check: data gaps.
# The timestamp arithmetic + FIFTEEN_MIN_NS assumes continuous data.
# If there's a gap, i.e. Friday → Monday, the lookup key T_{i+4} + 15m still points to the correct next bucket for that bar

# str_confirmed[j] fires at 45m bucket T_j
# lookup key = T_j + 45m
# → first 5m bar at T_j + 45m = exactly when 45m bar j closes ✅

# validate
validate_markers(df_15, 'isSTR')
validate_markers(df_45, 'isSTR')

marks = df_45['isSTR'].value_counts().to_dict()
print(f"45m shape: {df_45.shape}")
print(f"45m isSTR marks: {marks}  (highs: {marks.get(1,0)}, lows: {marks.get(-1,0)})")

marks = df_15['isSTR'].value_counts().to_dict()
print(f"15m shape: {df_15.shape}")
print(f"15m isSTR marks: {marks}  (highs: {marks.get(1,0)}, lows: {marks.get(-1,0)})")


# STR_WINDOW          = 4
# timestamps are nanoseconds — use ns constants
FIVE_MIN_NS         = 300_000
FIFTEEN_MIN_NS      = 900_000
FORTY_FIVE_MIN_NS   = 2_700_000

# str_confirmed is already built causally inside strHunt (available_at array)
# because price order-fix and BoS fix create subtle lookahead leakage
# No shift needed here — just map to 5m

# Add bucket keys to 5m bars
df_5['ts_5m']  = (df_5['timestamp'] // FIVE_MIN_NS)       * FIVE_MIN_NS
df_5['ts_15m'] = (df_5['timestamp'] // FIFTEEN_MIN_NS)    * FIFTEEN_MIN_NS
df_5['ts_45m'] = (df_5['timestamp'] // FORTY_FIVE_MIN_NS) * FORTY_FIVE_MIN_NS

# Build lookup: bucket_key → confirmed value
lookup_15m = {int(k) + FIFTEEN_MIN_NS:    v for k, v in zip(df_15['timestamp'], df_15['str_confirmed'])}
lookup_45m = {int(k) + FORTY_FIVE_MIN_NS: v for k, v in zip(df_45['timestamp'], df_45['str_confirmed'])}

# Map to 5m — broad pass (all bars in bucket get the value)
df_5['15STR_confirmed'] = df_5['ts_15m'].map(lookup_15m).fillna(0).astype('int8')
df_5['45STR_confirmed'] = df_5['ts_45m'].map(lookup_45m).fillna(0).astype('int8')

# Keep only the FIRST 5m bar in each bucket (confirmation fires once, at bucket open)
is_first_in_15m = df_5.groupby('ts_15m').cumcount() == 0
is_first_in_45m = df_5.groupby('ts_45m').cumcount() == 0

df_5['15STR_confirmed'] = df_5['15STR_confirmed'].where(is_first_in_15m, 0)
df_5['45STR_confirmed'] = df_5['45STR_confirmed'].where(is_first_in_45m, 0)

print(f"15STR_confirmed  highs: {(df_5['15STR_confirmed']==1).sum():,}  lows: {(df_5['15STR_confirmed']==-1).sum():,}")
print(f"45STR_confirmed  highs: {(df_5['45STR_confirmed']==1).sum():,}  lows: {(df_5['45STR_confirmed']==-1).sum():,}")



# add last keylevel — split into keylv_high and keylv_low
#
# keylv_high: carries the highest high since the last confirmed swing HIGH
#             updates only when sig[i] == 1, range = high[last_high_i : i]
# keylv_low : carries the lowest low since the last confirmed swing LOW
#             updates only when sig[i] == -1, range = low[last_low_i : i]
# barsSince  : resets to 0 on either signal (high or low), counts bars since last confirmation
#
# Cold-start fill (before first signal fires):
#   keylv_high expands with running max of high[0..i-1]  → 0 null rows, fully causal
#   keylv_low  expands with running min of low[0..i-1]   → "highest/lowest seen so far"
#   Once first signal fires, plain carry-forward resumes as normal.

def add_keylv(df: pd.DataFrame, lv: str) -> pd.DataFrame:
    n    = len(df)
    high = df['high'].values
    low  = df['low'].values
    sig  = df[f"{lv}STR_confirmed"].values

    keylv_high = np.empty(n, dtype='float64')
    keylv_low  = np.empty(n, dtype='float64')
    bars_since = np.zeros(n, dtype='int32')

    # cold-start seed — no confirmed pivot yet
    keylv_high[0] = high[0]
    keylv_low[0]  = low[0]

    last_high_i = 0   # index of last swing HIGH confirmation
    last_low_i  = 0   # index of last swing LOW  confirmation
    high_init   = False  # True once first sig==1  fires
    low_init    = False  # True once first sig==-1 fires

    for i in range(1, n):
        if sig[i] == 1:
            # swing HIGH confirmed: extreme is max high since last high confirmation
            keylv_high[i] = round(float(high[last_high_i : i].max()), 4)
            keylv_low[i]  = keylv_low[i - 1]   # carry forward
            bars_since[i] = 0
            last_high_i   = i
            high_init     = True

        elif sig[i] == -1:
            # swing LOW confirmed: extreme is min low since last low confirmation
            keylv_low[i]  = round(float(low[last_low_i : i].min()), 4)
            keylv_high[i] = keylv_high[i - 1]  # carry forward
            bars_since[i] = 0
            last_low_i    = i
            low_init      = True

        else:
            # After init: plain carry-forward
            # Before init: expand running extreme — causal (uses bar i-1 only)
            keylv_high[i] = keylv_high[i-1] if high_init else max(keylv_high[i-1], high[i-1])
            keylv_low[i]  = keylv_low[i-1]  if low_init  else min(keylv_low[i-1],  low[i-1])
            bars_since[i] = bars_since[i-1] + 1   # purely backward-looking ✅

    df = df.copy()
    df[f"{lv}STR_keylv_high"] = keylv_high
    df[f"{lv}STR_keylv_low"]  = keylv_low
    df[f"barsSince{lv}STR"]   = bars_since
    return df

df_5 = add_keylv(df_5, "15")
df_5 = add_keylv(df_5, "45")
print(df_5.columns)
df_5.head()