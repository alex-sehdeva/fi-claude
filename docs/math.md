# Mathematical Reference

This document covers every formula implemented in fi-claude, organized by
module. Each section shows the equation, how it maps to code, and what
assumptions are baked in.

---

## 1. Curve Infrastructure

### 1.1 Day-Count Fractions

**Source:** `src/fi_claude/curves/day_count.py`

Day-count conventions convert a calendar period into a dimensionless "year
fraction" used in discounting and accrual calculations. We implement five
conventions from ISDA 2006 definitions.

**ACT/360**

$$\alpha = \frac{d_2 - d_1}{360}$$

where $d_2 - d_1$ is the actual number of calendar days between the two
dates. Common for money-market instruments and USD LIBOR/SOFR.

**ACT/365 Fixed**

$$\alpha = \frac{d_2 - d_1}{365}$$

Ignores leap years. Common for GBP and some AUD instruments.

**ACT/ACT (simplified)**

$$\alpha = \frac{d_2 - d_1}{D}$$

where $D$ is the actual number of days in the year(s) spanned by the period.
For single-year periods, $D$ is 365 or 366 (leap year). For multi-year
periods, we average: $D = \text{total days from Jan 1 of start year to Jan 1
of (end year + 1)} \div (\text{year span} + 1)$.

*Note:* This is a simplification of ACT/ACT ISDA, which splits the accrual
period at each year boundary and weights each sub-period by its own
denominator. Sufficient for pricing; would need refinement for exact coupon
calculations on year-boundary-crossing periods.

**30/360 Bond Basis (ISDA)**

$$\alpha = \frac{360(Y_2-Y_1) + 30(M_2-M_1) + (D_2'-D_1')}{360}$$

where:
- $D_1' = \min(D_1, 30)$
- $D_2' = \min(D_2, 30)$ if $D_1' = 30$, else $D_2' = D_2$

This is the standard ISDA 30/360 adjustment that handles end-of-month
conventions.

**BUS/252 (Brazilian Business Days)**

$$\alpha = \frac{n}{252}$$

where $n$ is the number of Brazilian business days between the two dates.
This convention is unique to the Brazilian market and is used for all BRL
DI-linked instruments. The function requires $n$ as an external input
because computing it needs a Brazilian holiday calendar — that dependency is
deliberately excluded from the calculation layer.


### 1.2 Curve Interpolation

**Source:** `src/fi_claude/curves/interpolation.py`

Discount curves are stored as sorted `(date, discount_factor)` pairs. To
obtain a discount factor for an arbitrary date, we interpolate between
bracketing nodes.

**Linear interpolation on discount factors:**

$$\text{df}(t) = \text{df}(t_L) + \frac{t - t_L}{t_R - t_L}
                  \bigl(\text{df}(t_R) - \text{df}(t_L)\bigr)$$

where $t_L, t_R$ are the dates of the left and right bracketing nodes, and
the fraction $\frac{t-t_L}{t_R-t_L}$ is computed in calendar days.

**Log-linear interpolation (default):**

$$\text{df}(t) = \exp\!\Bigl(
  \ln\text{df}(t_L)
  + \frac{t-t_L}{t_R-t_L}\bigl(\ln\text{df}(t_R) - \ln\text{df}(t_L)\bigr)
\Bigr)$$

Equivalently: $\text{df}(t) = \text{df}(t_L)^{1-\lambda}\;\text{df}(t_R)^\lambda$
where $\lambda = (t-t_L)/(t_R-t_L)$.

Log-linear interpolation is the standard default for discount curves because
it preserves positivity of discount factors and produces piecewise-constant
*instantaneous forward rates* between nodes — a desirable property for
hedging and risk calculations.

**Extrapolation:** Flat in both directions (left and right). The first/last
node's discount factor is held constant outside the curve's date range.

---

## 2. Pricer Mathematics

### 2.1 BRL Pre x CDI Swap

**Source:** `src/fi_claude/pricers/brl_pre_cdi.py`

A Pre-CDI swap exchanges a pre-fixed rate against the accumulated CDI
(overnight interbank deposit rate) over the BUS/252 day-count convention.
This is the foundational interest rate derivative in the Brazilian market,
closely tied to B3 DI futures.

**Fixed leg future value:**

$$\text{FV}_{\text{fixed}} = N \cdot (1 + r_{\text{fixed}})^{\alpha}$$

where $N$ is the notional, $r_{\text{fixed}}$ is the annualized pre-fixed
rate, and $\alpha = n/252$ is the BUS/252 year fraction.

The discrete compounding $(1+r)^\alpha$ (rather than $e^{r\alpha}$) is a
market convention: Brazilian DI futures compound discretely on a BUS/252
basis.

**Fixed leg present value:**

$$\text{PV}_{\text{fixed}} = \text{FV}_{\text{fixed}} \cdot \text{df}(T)$$

where $\text{df}(T)$ is the CDI discount factor at the swap end date.

**Float leg present value:**

The CDI leg, at inception, is worth par. Between inception and maturity, its
value is determined by the ratio of discount factors:

$$\text{PV}_{\text{float}} = N \cdot \frac{\text{df}(t_0)}{\text{df}(T)}$$

where $t_0$ is the start date and $T$ is the end date. The intuition: the
float leg will accrue to exactly $N \cdot \text{df}(t_0)/\text{df}(T)$ if
rates evolve as implied by the curve. The ratio $\text{df}(t_0)/\text{df}(T)$
is the forward compounding factor from $t_0$ to $T$.

**Swap NPV (pay-fixed perspective):**

$$\text{NPV} = \text{PV}_{\text{float}} - \text{PV}_{\text{fixed}}$$

Flip sign for receive-fixed.


### 2.2 Inflation-Linked Bond

**Source:** `src/fi_claude/pricers/inflation_bond.py`

Covers US TIPS, Brazilian NTN-Bs, UK index-linked gilts, and similar
structures where both coupons and principal are scaled by a CPI index ratio.

**Index ratio:**

$$I(t) = \frac{\text{CPI}(t)}{\text{CPI}_{\text{base}}}$$

where $\text{CPI}(t)$ is interpolated from the inflation curve at payment
date $t$, and $\text{CPI}_{\text{base}}$ is the CPI level at bond issuance.

**Deflation floor:** If the bond has principal protection (typical for TIPS):

$$I(t) = \max\!\left(\frac{\text{CPI}(t)}{\text{CPI}_{\text{base}}},\; 1.0\right)$$

This means the investor never receives less than par at redemption, even if
the price level has fallen since issuance.

**Coupon cashflow for period $[t_a, t_b]$:**

$$C_i = F \cdot c_{\text{real}} \cdot I(t_{\text{pay}}) \cdot \alpha(t_a, t_b)$$

where $F$ is face value, $c_{\text{real}}$ is the real coupon rate, and
$\alpha$ is the day-count year fraction for the accrual period.

**Redemption at maturity:**

$$R = F \cdot I(T) \qquad\text{(with floor: } R = \max(F \cdot I(T),\; F)\text{)}$$

**Present value:**

$$\text{PV} = \sum_{i} C_i \cdot \text{df}(t_i) + R \cdot \text{df}(T)$$

Discounting uses a *real* yield curve (keyed as `{CCY}-REAL` in MarketData).
The real curve strips out expected inflation — discounting real cashflows by
real rates avoids double-counting the inflation component.


### 2.3 Cross-Currency Basis Swap

**Source:** `src/fi_claude/pricers/xccy_basis_swap.py`

A cross-currency basis swap has two floating legs in different currencies,
with optional initial and final notional exchanges.

**Floating leg PV (single currency):**

Each period's cashflow is estimated from the forward rate implied by the
discount curve:

$$f_i = \frac{\text{df}(t_{i-1})}{\text{df}(t_i)} - 1$$

This is the discrete forward rate for the period $[t_{i-1}, t_i]$, derived
from the no-arbitrage relationship between discount factors.

Period cashflow including the basis spread:

$$\text{CF}_i = N \cdot \left(f_i + s \cdot \frac{\Delta_i}{360}\right)$$

where $s = \text{spread\_bps} / 10{,}000$ and $\Delta_i$ is calendar days in
the period (ACT/360).

Period PV:

$$\text{PV}_i = \text{CF}_i \cdot \text{df}(t_{\text{pay}})$$

**Currency conversion:**

The far leg's PV is computed in its native currency, then converted:

$$\text{PV}_{\text{far}}^{\text{domestic}} = \text{PV}_{\text{far}}^{\text{foreign}} \cdot S$$

where $S$ is the FX spot rate.

**Notional exchange PV:**

At inception (if `initial_exchange`):
$$\text{Exch}_0 = -N_{\text{near}} \cdot \text{df}_{\text{near}}(t_0)
                  + N_{\text{far}} \cdot \text{df}_{\text{far}}(t_0) \cdot S$$

At maturity (if `final_exchange`):
$$\text{Exch}_T = +N_{\text{near}} \cdot \text{df}_{\text{near}}(T)
                  - N_{\text{far}} \cdot \text{df}_{\text{far}}(T) \cdot S$$

The signs reflect the near-leg perspective: at inception you pay out your
notional and receive the foreign notional (converted); at maturity you
receive your notional back and return the foreign one.

**Total NPV:**

$$\text{NPV} = \text{PV}_{\text{near}} - \text{PV}_{\text{far}}^{\text{domestic}}
              + \text{Exch}_0 + \text{Exch}_T$$


### 2.4 TBA (To-Be-Announced)

**Source:** `src/fi_claude/pricers/tba.py`

TBAs are forward contracts on agency mortgage-backed security pools.
Pricing requires projecting mortgage cashflows under a prepayment model,
then discounting. Neither QuantLib nor Strata supports this.

**CPR/SMM prepayment conversion:**

The constant prepayment rate (CPR) is annualized. The single monthly
mortality (SMM) — the fraction of remaining balance that prepays each
month — is:

$$\text{SMM} = 1 - (1 - \text{CPR})^{1/12}$$

This is the PSA (Public Securities Association) convention.

**Monthly cashflow projection:**

For month $k$ with remaining balance $B_k$:

Scheduled payment (level-pay amortization):

$$P_k = B_k \cdot \frac{r_m}{1 - (1+r_m)^{-(T-k+1)}}$$

where $r_m = \text{coupon}/12$ is the monthly rate and $T-k+1$ is
remaining months.

Component split:
$$I_k = B_k \cdot r_m \qquad \pi_k^{\text{sched}} = P_k - I_k$$

Prepayment (applied to the balance after scheduled principal):

$$\pi_k^{\text{prepay}} = (B_k - \pi_k^{\text{sched}}) \cdot \text{SMM}$$

Total cashflow:

$$\text{CF}_k = I_k + \pi_k^{\text{sched}} + \pi_k^{\text{prepay}}$$

Balance update:

$$B_{k+1} = B_k - \pi_k^{\text{sched}} - \pi_k^{\text{prepay}}$$

The initial balance is $B_0 = \text{face} \times \text{pool\_factor}$, where
the pool factor represents the fraction of original principal still
outstanding.

**Present value:**

$$\text{PV} = \sum_{k} \text{CF}_k \cdot \text{df}_{\text{USD}}(t_k)$$

---

## 3. Shock Suite Mathematics

**Source:** `src/fi_claude/risk/shocks.py`

The shock suite operates on a single core transformation: given a discount
factor and a rate bump in basis points, produce a new discount factor. All
shock shapes (parallel, steepen, twist, etc.) reduce to this primitive.

### 3.1 The Discount Factor Bump Primitive

Starting from the continuously-compounded rate representation of a discount
factor:

$$\text{df}(t) = e^{-r \cdot t}$$

A rate shock of $\Delta r$ (in bps, so $\Delta r / 10{,}000$ in decimal)
applied at tenor $t$ years produces:

$$\text{df}'(t) = e^{-(r + \Delta r/10000) \cdot t}
               = \text{df}(t) \cdot e^{-\Delta r \cdot t / 10000}$$

This is implemented at `shocks.py:378-385` as:

```python
def _bump_discount_factor(df, years, bump_fn):
    bump_bps = bump_fn(years)
    return df * math.exp(-bump_bps / 10_000 * years)
```

**Key properties:**
- The transformation is *multiplicative* in discount-factor space.
- A positive `bump_bps` (rates up) always decreases the discount factor.
- The effect grows with tenor: a 25bp parallel shock moves the 10y
  discount factor more than the 1y, because the exponential $e^{-\Delta r \cdot t}$
  depends on $t$.
- The bump is applied node-by-node. Each node's tenor $t$ is computed as
  `(node.date - valuation_date).days / 365.25`.

### 3.2 Shock Shape Functions

Each shock type defines a function $\Delta r(t): \text{tenor} \to \text{bps}$
that is evaluated per curve node. This cleanly separates the *shape* of a
shock from the *mechanics* of applying it.

**Parallel:** $\Delta r(t) = b$

Constant across all tenors. `parallel("USD", 25)` adds 25bps everywhere.

**Steepen:** Linear interpolation between short and long ends.

$$\Delta r(t) = \begin{cases}
  b_s & t \le t_s \\
  b_s + \dfrac{t - t_s}{t_L - t_s}(b_L - b_s) & t_s < t < t_L \\
  b_L & t \ge t_L
\end{cases}$$

where $b_s$, $b_L$ are the short/long bumps and $t_s$, $t_L$ default to
0.25y and 30y. `steepen("USD", -10, 15)` pulls the short end down 10bps
and pushes the long end up 15bps, with linear interpolation in between.

**Flatten:** Identical to steepen but with short and long bumps swapped
internally: $\Delta r(t) = \text{steepen}(t;\; b_s \leftrightarrow b_L)$.

**Twist:** Rotation around a pivot tenor $t_p$.

$$\Delta r(t) = \begin{cases}
  b_s \cdot \bigl(1 - t/t_p\bigr) & t \le t_p \\
  b_L \cdot \dfrac{t - t_p}{30 - t_p} & t > t_p
\end{cases}$$

The pivot tenor has zero bump. The short and long ends move in the
directions specified by $b_s$ and $b_L$, interpolating linearly to/from
zero at the pivot. `twist("USD", 5.0, -20, 20)` is a bear steepener with
the 5y point held fixed.

**Point (Gaussian):** Bump concentrated around a target tenor $t^*$ with
Gaussian falloff:

$$\Delta r(t) = b \cdot \exp\!\left(-\frac{(t - t^*)^2}{2\sigma^2}\right)
\qquad\text{for } |t - t^*| \le 3\sigma$$

where $\sigma$ is the `width` parameter (default 0.5y). Beyond $3\sigma$,
the bump is exactly zero. `point_shock("USD", 5.0, 50)` concentrates a
50bp shock at the 5y point.

**Custom (per-tenor):** User provides a dictionary `{tenor_years: bps}`.
Intermediate tenors are linearly interpolated; tenors outside the range
use flat extrapolation from the nearest endpoint.


### 3.3 FX Spot Shocks

FX spot is shocked directly — no curve mechanics involved:

**Percentage shock:**

$$S' = S \cdot (1 + p/100)$$

where $p$ is the percentage change. `fx_shock("EUR/USD", pct=-2)` drops
EUR/USD by 2%.

**Absolute shock:**

$$S' = S + \delta$$

where $\delta$ is the absolute change. `fx_shock("EUR/USD", absolute=-0.05)`
subtracts 0.05 from the spot rate.

If both `pct` and `absolute` are specified, percentage is applied first,
then the absolute shift.


### 3.4 Inflation (CPI) Shocks

CPI index levels are shifted by a multiplicative factor:

$$\text{CPI}'(t) = \text{CPI}(t) \cdot (1 + \Delta / 10{,}000)$$

where $\Delta$ is `level_bps`. Applied uniformly to all nodes on the
targeted inflation curve.


### 3.5 Covered Interest Parity (CIP) Enforcement

**Source:** `shocks.py:268-313`

When rate curves are shocked, FX forward rates must adjust to avoid
arbitrage. The no-arbitrage CIP relationship is:

$$F(t) = S \cdot \frac{\text{df}_{\text{quote}}(t)}{\text{df}_{\text{base}}(t)}$$

where:
- $F(t)$ is the FX forward rate at time $t$
- $S$ is the FX spot rate
- $\text{df}_{\text{base}}(t)$ is the discount factor for the **base** (left)
  currency of the pair
- $\text{df}_{\text{quote}}(t)$ is the discount factor for the **quote** (right)
  currency

Forward points (stored on `FxForwardCurve.nodes`) are the difference:

$$\text{fwd\_points}(t) = F(t) - S$$

**Application order matters.** `apply_shocks` processes in this sequence:

1. Rate curve shocks (modify discount factors)
2. Inflation shocks (modify CPI levels)
3. FX spot shocks (modify spot rates)
4. **CIP adjustment** (recompute forward points from shocked curves + shocked spot)

Step 4 reads the *already-shocked* discount curves and spot rate, then
recomputes every node on every FX forward curve via the CIP formula. This
means:

- Shocking USD rates alone will move EUR/USD forward points (because
  $\text{df}_{\text{USD}}$ changed).
- Shocking EUR/USD spot alone will move forward points (because $S$ changed).
- Shocking both USD rates and EUR/USD spot produces a combined effect.

**CipPolicy controls:**

| Policy | Behavior |
|--------|----------|
| `ENFORCE` | Recompute all FX forward curves from CIP after all shocks |
| `IGNORE` | Leave FX forward curves untouched regardless of rate shocks |
| `BREAK` | Reserved for stress tests where you deliberately violate CIP |

**Example — USD +100bps, EUR unchanged:**

The EUR/USD pair has `base=EUR`, `quote=USD`. Under CIP:

$$F = S \cdot \frac{\text{df}_{\text{USD}}(t)}{\text{df}_{\text{EUR}}(t)}$$

USD rates up $\Rightarrow$ $\text{df}_{\text{USD}}$ falls $\Rightarrow$
$\text{df}_{\text{USD}}/\text{df}_{\text{EUR}}$ falls $\Rightarrow$ $F$
falls $\Rightarrow$ forward points decrease.

Intuitively: higher USD rates mean USD is more expensive to borrow
forward, so the EUR/USD forward rate drops (USD strengthens in the forward
market).

---

## 4. Scenario Composition

The `scenario()` function composes shocks declaratively. Shocks are applied
sequentially within their category (rate, inflation, FX), but the categories
are applied in fixed order. Within a category, shocks compose additively in
rate space — two parallel shocks of +10bps and +15bps on the same curve
produce the same result as one +25bps shock, because:

$$\text{df}'' = \text{df} \cdot e^{-10t/10000} \cdot e^{-15t/10000}
             = \text{df} \cdot e^{-25t/10000}$$

**Immutability guarantee:** `apply_shocks` never mutates its inputs. Every
step produces a new `MarketData` via Pydantic's `model_copy(update={...})`.
The original market data is untouched — verified by test
`TestComposition::test_original_market_unchanged`.

---

## 5. Assumptions and Limitations

**Interpolation:** Only linear and log-linear are implemented. Cubic spline
and flat-forward are declared in the `InterpolationMethod` enum but fall back
to linear. Production use would need monotone cubic Hermite (Hyman filter)
or Hagan-West for forward-preserving interpolation.

**Day counts:** ACT/ACT is simplified (does not split at year boundaries).
BUS/252 requires external business-day counts.

**BRL swap:** Single-period only (no intermediate coupon dates). The float
leg uses the curve-implied forward compounding factor rather than actual
daily CDI fixings.

**Xccy basis swap:** Forward rates are estimated from discount-factor ratios
(single-curve approach). A dual-curve framework (separate projection and
discounting curves) would be needed for production xccy pricing post-2008.

**TBA prepayment model:** Constant CPR only. Production TBA pricing uses
sophisticated prepayment models (e.g., Bloomberg's BDT, Andrew Davidson's
LoanDynamics) that incorporate interest-rate paths, burnout, seasonality,
and borrower incentive functions.

**CIP enforcement:** Assumes discount curves are keyed by the same string
as their currency code (e.g., `"USD"`, `"EUR"`). The CIP formula uses the
spot rate from `fx_spot_rates` — if the spot hasn't been shocked but rates
have, the formula still recomputes forward points, which is correct (the
spot is just unchanged).
