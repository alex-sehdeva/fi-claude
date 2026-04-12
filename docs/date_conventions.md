# Date Convention Subtleties

This document covers the date-related conventions that affect pricing for
each of the four instruments in fi-claude. The emphasis is practical: what
the convention is, why it exists, and what goes wrong when you get it wrong.

For the formulas themselves, see [math.md](math.md).

---

## 1. BRL Pre-CDI Swaps

### BUS/252 day count

BRL interest rate instruments use the BUS/252 convention: the year fraction
between two dates is the number of **Brazilian business days** between them,
divided by 252.

$$\alpha = \frac{n_{\text{bus}}}{252}$$

The business-day count excludes weekends and all holidays published in the
ANBIMA (Brazilian Financial and Capital Markets Association) calendar. This
is the convention used by B3 (formerly BM&F Bovespa) for DI futures and by
the OTC market for Pre-CDI swaps.

**Why 252?** The number is a historical convention from Bovespa/B3. It
approximates the typical number of trading days in a Brazilian year once
national holidays, state holidays, and exchange-specific closures are
removed. It is not 250 (a round number sometimes used informally), nor 260
(52 weeks times 5 days, which ignores holidays). The denominator is fixed at
252 regardless of how many business days actually fall in a given calendar
year. This is not an estimate -- it is a market standard baked into every DI
futures contract specification and every CDI accrual calculation.

**What goes wrong:** Getting the holiday calendar wrong by even one day
changes the year fraction and therefore the discount factor. On a 10M BRL
notional 2-year swap at ~13% pre-fixed, a one-business-day error in the
numerator shifts the year fraction by approximately 1/252 = 0.00397, which
moves the fixed leg future value by roughly:

$$\Delta\text{FV} \approx 10{,}000{,}000 \times \ln(1.135) \times 0.00397 \approx 5{,}030 \text{ BRL}$$

That is a real P&L difference, not a rounding error.

In fi-claude, the BUS/252 year-fraction implementation (`day_count.py`)
deliberately requires the caller to supply the business-day count as an
integer. Computing it requires the ANBIMA holiday calendar, which is an
external dependency -- the day-count layer stays pure.

### Discrete compounding

Brazilian convention is **always** discrete compounding:

$$(1 + r)^{\alpha}$$

Never continuous ($e^{r\alpha}$). This applies to DI futures settlement, CDI
accrual, and Pre-CDI swap fixed legs. The `BrlPreCdiSwap` model defaults to
`CompoundingMethod.OVERNIGHT_COMPOUNDED`, and the pricer applies the
discrete formula. If you accidentally use continuous compounding on a 13.5%
rate with alpha = 2.0, the error is:

$$e^{0.135 \times 2} - (1.135)^{2} \approx 1.3100 - 1.2882 = 0.0218$$

That is 2.18% of notional -- catastrophic on any real position.

### CDI overnight fixing

The CDI (Certificado de Deposito Interbancario) rate is published daily by
B3 as an annualized rate on a BUS/252 basis. Each day's accrual is:

$$\text{daily factor} = (1 + \text{CDI}_{\text{annual}})^{1/252}$$

Factors compound multiplicatively across business days. The float leg of a
Pre-CDI swap accumulates these daily factors between start and end dates.
For pricing purposes, fi-claude uses the curve-implied forward compounding
factor (the discount-factor ratio) rather than realized daily fixings. For
historical valuation or back-testing, you would need the actual daily CDI
series from B3.

### Settlement

- **DI futures (B3):** T+0 -- the exchange settles margin daily with no lag.
- **OTC Pre-CDI swaps:** T+1 -- the standard settlement lag in the Brazilian
  interbank market.

If you price an OTC swap using T+0 settlement assumptions, your discount
factor is read off one day earlier on the curve, shifting the PV.

### Holiday calendar dependency

ANBIMA publishes the official Brazilian financial market calendar. It
includes national holidays, some state holidays (particularly Sao Paulo
municipal holidays, since B3 is domiciled there), and occasional
extraordinary closures. The calendar is updated annually and sometimes
receives mid-year revisions (e.g., when the government moves a holiday).

Implications:

- A DI-future curve bootstrapped using last year's calendar may assign wrong
  business-day counts to future periods if new holidays have been declared.
- Two counterparties using different holiday calendar versions will compute
  different year fractions for the same swap, leading to different PVs and
  potentially disputed settlements.

### End-of-month conventions

BRL swaps typically use **modified following** with the B3 calendar: if a
payment date falls on a weekend or holiday, it rolls forward to the next
business day, unless that would cross into the next calendar month, in which
case it rolls backward. This is captured in the `BusinessDayConvention` enum
as `MODIFIED_FOLLOWING`.

---

## 2. Inflation-Linked Bonds

### CPI reference lag

Inflation-linked bonds do not use today's CPI for today's accrual. Instead,
each market applies a lag between the CPI publication month and the
settlement date:

| Bond type | CPI index | Lag | Example |
|-----------|-----------|-----|---------|
| US TIPS | CPI-U (non-seasonally adjusted) | 3 months | July 15 settlement uses April CPI |
| UK linkers | UK RPI (legacy) / CPIH (new) | 3 months (was 8 months before 2005) | Same 3-month mapping |
| Brazil NTN-B | IPCA (IBGE) | ~1 month | Accrual on the 15th uses the prior month's published IPCA |
| Eurozone (OATi, BTPi) | EU HICP ex-tobacco | 3 months | Similar to TIPS |

**What goes wrong:** Using the wrong lag shifts which CPI observation
applies to a given settlement date. For a TIPS with 2.5% inflation and $10M
face, a one-month lag error changes the index ratio by roughly 0.2%, which
is ~$20,000 on the PV. For NTN-Bs with IPCA running at 5%, the error is
proportionally larger.

In fi-claude, the lag is stored as `InflationLagConvention` on the
`InflationLinkedBond` model. The pricer reads it to determine which CPI
observation to pull from the inflation curve.

### Interpolation of CPI levels

CPI is published monthly, but bonds settle on arbitrary dates. For
mid-month settlement, TIPS use **linear interpolation** between two monthly
CPI prints to compute the reference CPI:

$$\text{CPI}_{\text{ref}}(d) = \text{CPI}_{m-3} + \frac{d - 1}{D}
  \bigl(\text{CPI}_{m-2} - \text{CPI}_{m-3}\bigr)$$

where $d$ is the day of the month (1-based), $D$ is the number of days in
the month, and $m$ is the settlement month. The 3-month lag means a
settlement on July 15 interpolates between April CPI and May CPI.

The exact interpolation method matters for daily accrued interest
calculations. Using step-function CPI (no interpolation) instead of linear
interpolation will produce different accrued interest for every day that
is not the 1st of the month. On a $100M TIPS position, the accrued
difference for a mid-month settlement can be tens of thousands of dollars.

### Index ratio computation

The index ratio scales both coupons and principal:

$$I(t) = \frac{\text{CPI}(t)}{\text{CPI}_{\text{base}}}$$

where $\text{CPI}_{\text{base}}$ is the CPI level at the bond's original
issue date (specifically, the reference CPI for the dated date of the first
coupon period). This base CPI is fixed for the life of the bond and is
stored as `base_cpi` on the `InflationLinkedBond` model.

**What goes wrong:** Using the wrong base CPI (e.g., the CPI at auction
date instead of the dated date) produces a systematically wrong index ratio
for every cashflow. This error does not cancel -- it scales linearly with
the CPI drift since issuance.

### Deflation floor mechanics

US TIPS protect principal at par: at maturity, the investor receives the
greater of the inflation-adjusted principal and the original face value.

$$R = \max\bigl(F \times I(T),\; F\bigr)$$

This is a **principal floor**, not a coupon floor. Individual coupon
payments can be reduced by deflation (the index ratio can dip below 1.0
for coupon purposes), but the redemption amount cannot. Some other
sovereign linkers (e.g., older UK issues, some Canadian real-return bonds)
do **not** have this floor, meaning the investor bears full deflation risk.

In fi-claude, the floor is controlled by the `deflation_floor` flag
(default `True`). Setting it to `False` for a TIPS is a pricing error;
leaving it `True` for a non-floor linker overstates the bond's value in
deflationary scenarios.

### Coupon frequency

Most inflation-linked bonds pay semi-annually:

- **US TIPS:** semi-annual (January/July or April/October cycles)
- **Brazil NTN-B:** semi-annual (typically May 15 / November 15)
- **UK linkers:** semi-annual (March/September cycles common)
- **Some eurozone linkers (OATi):** annual

The `coupon_frequency_months` field on `InflationLinkedBond` defaults to 6.
Annual-coupon linkers need this set to 12.

### Day count

- **US TIPS:** ACT/ACT (ICMA) for accrued interest, which counts actual
  calendar days divided by the actual number of days in the coupon period
  times the coupon frequency.
- **Brazil NTN-B:** BUS/252 -- the same business-day convention as all
  other BRL fixed-income instruments. This means NTN-B accrued interest
  depends on the ANBIMA calendar, with all the same implications described
  in Section 1.
- **UK linkers:** ACT/ACT (ICMA).

Using the wrong day count on accrued interest changes the dirty price. For
TIPS, the difference between ACT/ACT and ACT/365 is small (at most a few
days of coupon per year), but for NTN-B the difference between BUS/252 and
any calendar-day convention can be significant around holidays.

### Settlement

- **US TIPS:** T+1 (standardized since 2017; was informally T+1 before).
- **Brazil NTN-B:** T+1 (via SELIC/B3).
- **UK linkers:** T+1.

### Ex-dividend periods

UK index-linked gilts have a **7-business-day ex-dividend period** before
each coupon payment date. During this window, the bond trades "ex-dividend"
-- the buyer does not receive the upcoming coupon. This affects accrued
interest: during the ex-dividend period, the accrued interest is
**negative** (the buyer pays less than the clean price because they forfeit
the coupon).

US TIPS have **no ex-dividend period**. The buyer on the day before a coupon
payment receives the full coupon.

**What goes wrong:** Pricing a UK linker without accounting for the
ex-dividend period overstates the dirty price by roughly one full coupon
during that 7-day window, typically several thousand pounds per GBP 1M face.

---

## 3. Cross-Currency Basis Swaps

### The "basis" convention

In a cross-currency basis swap, two floating-rate legs in different
currencies are exchanged. The **basis spread** is quoted on the **non-USD
leg**. For example:

> EUR 3M EURIBOR - 15bps vs USD SOFR flat

means the EUR leg pays EURIBOR minus 15 basis points, and the USD leg pays
SOFR with no spread. A negative basis (e.g., -15bps on EUR) means there is
excess demand to borrow USD against EUR collateral, reflecting USD funding
scarcity.

In fi-claude, the `XccyLeg.spread_bps` field carries this basis. By
convention, the near leg's spread is 0 and the far leg carries the quoted
basis.

**What goes wrong:** Putting the basis on the wrong leg flips the sign of
the swap's NPV. On a 5-year, EUR 100M xccy swap, 15bps of basis is worth
roughly EUR 750K in PV -- getting the leg assignment wrong doubles the error.

### Payment frequency mismatch

Different currency markets have different standard floating-rate payment
frequencies:

| Currency | Standard index | Typical frequency |
|----------|---------------|-------------------|
| USD | SOFR | Quarterly |
| EUR | EURIBOR 3M | Quarterly |
| GBP | SONIA | Quarterly (was semi-annual for LIBOR) |
| JPY | TONA | Semi-annual (was semi-annual for LIBOR) |

When the two legs of an xccy swap have different payment frequencies (e.g.,
USD quarterly vs JPY semi-annual), the non-matching periods create **stubs**
-- short or long first/last periods where cashflows from the two legs do not
align. Correct stub handling requires:

1. Computing the stub period's year fraction using the right day count.
2. Interpolating the correct forward rate for the stub tenor (not just
   using the standard 3M or 6M rate).
3. Deciding whether the stub is a short first, long first, short last, or
   long last period.

**What goes wrong:** Ignoring stubs on a 5-year USD/JPY swap can
misallocate roughly half a coupon period's worth of interest to the wrong
period, which on JPY 10B notional is tens of millions of yen.

### Notional exchange

Cross-currency basis swaps include **both initial and final notional
exchanges** as standard. This is unlike single-currency swaps, where
notional is not exchanged.

- **Initial exchange:** At inception, each counterparty delivers its
  notional to the other at the prevailing FX spot rate.
- **Final exchange:** At maturity, the notionals are returned at the
  **original** FX rate (not the then-prevailing spot).

The initial exchange means there **is** principal risk -- if one counterparty
defaults before the final exchange, the other has delivered real currency.
This is the primary reason xccy swaps have significant counterparty credit
exposure, unlike single-currency swaps.

In fi-claude, `XccyBasisSwap.initial_exchange` and `final_exchange` both
default to `True`.

### Mark-to-market (MtM) resets

To reduce counterparty credit exposure, the standard post-2008 xccy swap
uses **mark-to-market resets**: at each fixing date, the near-leg notional
is adjusted to reflect the current FX spot rate, and a compensating cashflow
is exchanged.

Concretely: if USD/JPY has moved from 110 to 115 since the last reset, the
USD notional on the near leg is adjusted upward, and the difference in JPY
equivalent is settled. This keeps the MTM exposure roughly flat rather than
letting it accumulate over years.

The MtM reset dates generate **additional cashflows** that must be discounted.
Ignoring them in a multi-year swap understates the true cashflow profile and
produces an incorrect PV.

In fi-claude, `mark_to_market_reset` defaults to `True` on `XccyBasisSwap`.

### Day counts by currency

Each leg uses the standard day-count convention for its currency:

| Currency | Day count |
|----------|-----------|
| USD | ACT/360 |
| EUR | ACT/360 |
| GBP | ACT/365 Fixed |
| JPY | ACT/360 |
| BRL | BUS/252 |

**What goes wrong:** Using ACT/360 for a GBP leg instead of ACT/365
produces a year fraction that is too large by a factor of 365/360 = 1.014.
On GBP 50M with SONIA at 5%, this is approximately GBP 34,700 per year of
overcounted interest.

### Fixing conventions

The reference rate on each leg determines the fixing lag -- how far in
advance of the accrual period the rate is observed:

| Rate | Fixing | Publication |
|------|--------|-------------|
| SOFR | T-1 (backward-looking overnight) | Published next business day by NY Fed |
| EURIBOR | T-2 (forward-looking term rate) | Published at 11:00 CET, two days before period start |
| ESTR | T-1 (backward-looking overnight) | Published next business day by ECB |
| TONA | T-1 (backward-looking overnight) | Published by BOJ |
| CDI | T-0 (same-day) | Published by B3 after market close |

For compounded-in-arrears rates (SOFR, ESTR, TONA), the full rate for a
period is only known at the end of the period plus the publication lag. This
means the final period cashflow is not fully determined until very close to
the payment date.

### Discounting

Post-2008, OIS discounting is the market standard for collateralized swaps.
The discount curve must match the collateral currency:

- **USD collateral:** Discount on SOFR (previously Fed Funds).
- **EUR collateral:** Discount on ESTR (previously EONIA).

The basis spread itself partly reflects the difference between the OIS rates
and the quoted floating indices. If you discount a USD/EUR xccy swap on
EURIBOR instead of ESTR, you conflate the projection curve with the discount
curve, producing an NPV error that grows with tenor and with the EURIBOR-ESTR
spread (typically 5-15bps but volatile in stress periods).

---

## 4. TBAs (To-Be-Announced)

### Settlement months and the 48-hour rule

TBAs trade for forward settlement in specific months. SIFMA publishes a
monthly settlement calendar. The **48-hour rule** requires the seller to
notify the buyer of the specific pools being delivered at least 48 hours
(two business days) before settlement.

Until notification, the buyer does not know which pools they will receive.
This is fundamental to TBA pricing: the contract is on a *generic* agency
MBS coupon, not a specific pool.

### Good delivery guidelines

SIFMA defines what pools can be delivered against a TBA contract:

- **FNMA/FHLMC 30-year:** Maximum 3 pools per $1M face value (i.e., a $10M
  trade can be delivered with up to 30 pools).
- **GNMA:** Different pool limits (generally more permissive due to smaller
  average pool sizes).
- **Variance:** The delivered face amount must be within 0.01% of the trade
  amount (the "par amount variance").

These constraints create **cheapest-to-deliver (CTD) optionality**: the
seller will deliver the least valuable eligible pools, which means the TBA
buyer is implicitly short a delivery option.

### Pool factor and dated date

- **Pool factor:** The fraction of original principal still outstanding,
  updated monthly by the agencies (Fannie Mae, Freddie Mac, Ginnie Mae).
  A pool with a factor of 0.85 has 85% of its original face remaining.
  fi-claude stores this as `pool_factor` on `TbaContract` (default 1.0 for
  new pools).

- **Dated date:** The date from which interest begins accruing. For a new
  TBA, this is the first day of the settlement month.

**What goes wrong:** Using a stale pool factor overstates or understates
the remaining balance. Since all cashflows scale with the balance, a 1%
error in pool factor is a 1% error in PV -- $100K on a $10M position.

### Day count for MBS accrued interest

- **FNMA/FHLMC:** 30/360 for accrued interest on the underlying MBS.
- **GNMA:** Also 30/360 for most products.
- **TBA pricing/discounting:** fi-claude discounts projected cashflows using
  the USD discount curve, which implicitly uses the curve's day-count
  convention (typically ACT/360 or ACT/365 depending on curve construction).

Note: the math.md reference says "ACT/360 for accrued interest" for MBS,
but the standard agency passthrough convention is 30/360. The distinction
matters for end-of-month periods where the 30/360 convention treats every
month as having 30 days.

### Delay days

Between a mortgage pool's stated payment date and when the investor
actually receives the cashflow, there is a fixed delay:

| Agency | Delay |
|--------|-------|
| FNMA | 55 calendar days (14th + 55 = ~24th of the following month for a "25-day" security) |
| FHLMC | 55 calendar days (Gold PCs pay on the 15th, 75 days for old FHLMC PCs) |
| GNMA | 45 calendar days (GNMA I pays on the 15th; GNMA II pays on the 20th) |

The delay means that even though the borrower's payment is due on the 1st,
the investor receives principal and interest weeks later. This delay affects
the present value because cashflows are pushed further out on the discount
curve.

**What goes wrong:** Ignoring the 55-day delay on a FNMA TBA understates
the discount applied to each cashflow. On a $100M position at 5% rates,
55 days of discounting error is roughly:

$$100{,}000{,}000 \times 0.05 \times \frac{55}{360} \approx \$764{,}000$$

in annual terms, or roughly $64K per monthly payment.

### Prepayment timing (CPR/SMM conversion)

The PSA prepayment model assumes prepayments occur on the **first of each
month**. The constant prepayment rate (CPR) is an annualized rate. The
single monthly mortality (SMM) is:

$$\text{SMM} = 1 - (1 - \text{CPR})^{1/12}$$

This conversion assumes prepayments are evenly distributed across months.
In reality, prepayments are seasonal (higher in summer, lower in winter)
and path-dependent (sensitive to the difference between the pool's coupon
and prevailing rates -- the "refinancing incentive").

fi-claude uses the constant-CPR model, which is sufficient for relative
value analysis but will misprice positions in environments with rapidly
changing rates. Production TBA pricing uses multi-factor prepayment models
(e.g., Andrew Davidson, Bloomberg BDT) that capture turnover, refinancing
incentive, burnout, and seasonality.

### Dollar rolls

A dollar roll is a paired TBA trade: sell the front-month TBA and buy the
back-month TBA. The price difference (the "drop") reflects:

1. **Carry:** Interest earned on the underlying MBS during the roll period.
2. **Financing:** The implicit repo rate of using the TBA market for
   financing instead of the repo market.
3. **CTD optionality:** The seller benefits from delivering the least
   valuable pools; rolling extends this advantage.

Dollar rolls are not directly modeled in fi-claude, but the building blocks
(TBA pricing at different settlement dates) are available. The roll drop can
be computed as the difference between two `price_tba` calls with different
settlement dates.

### Specified pools vs TBA

Once the 48-hour notification occurs, the TBA becomes a **specified pool
trade** with known characteristics:

- **WAC** (weighted average coupon): The actual average mortgage rate in the
  pool.
- **WAM** (weighted average maturity): The actual average remaining term.
- **WALA** (weighted average loan age): How seasoned the loans are.
- **Geography, loan size, FICO distribution:** All known, all affect
  prepayment behavior.

Specified pools with desirable characteristics (low loan balance, high LTV,
New York geography -- all of which suppress prepayments) trade at a premium
to TBA, called the "pay-up." This premium is not captured in the generic TBA
pricer.

---

## 5. Cross-Cutting Concerns

### Business day calendars

Every currency has its own holiday calendar:

| Currency | Calendar source | Typical holidays/year |
|----------|----------------|-----------------------|
| BRL | ANBIMA (B3 calendar) | ~12-15 |
| USD | Federal Reserve | ~10-11 |
| EUR | TARGET2 | ~10 |
| GBP | Bank of England | ~8 |
| JPY | Bank of Japan | ~15-16 |

Cross-currency products need **both** calendars. For a USD/JPY xccy swap, a
date that is a US holiday but not a Japanese holiday (or vice versa) may
shift payment dates on one leg but not the other, creating unintended
payment mismatches.

**What goes wrong:** If you use only the USD calendar for both legs of a
USD/JPY swap, you will miss Japanese holidays. Over a 5-year swap with
quarterly payments, this can shift 2-3 payment dates, each changing the
accrual period by 1-2 days.

### Modified following vs following

- **Modified following** (the default for most swaps): If a payment date
  falls on a holiday, move to the next business day, but if that crosses a
  month boundary, move to the preceding business day instead. This prevents
  a payment that belongs to January from landing in February.

- **Following:** Simply move to the next business day, even if it crosses a
  month boundary.

- **Preceding:** Move to the previous business day.

Most swap markets use modified following. Using plain following can push
payments across month boundaries, which changes both the accrual period
length (affecting the interest amount) and potentially the reference-rate
fixing date (affecting which rate applies).

### Stub periods

When a swap's trade date does not coincide with a standard payment date,
the first or last period is shorter or longer than normal. This is a
**stub period**.

- **Short first stub:** The first period starts on the trade date and ends
  on the first regular payment date. It is shorter than a standard period.
- **Long first stub:** The first period starts on the trade date and
  extends to the second regular payment date, spanning more than one
  standard period.
- **Short/long last stub:** Same concept at the end of the swap.

Stub periods require:

1. A pro-rated year fraction (straightforward with any day-count convention).
2. A forward rate for the non-standard tenor. For a 2-month stub on a
   quarterly swap, you need the 2-month forward rate, not the 3-month rate.
   Interpolating this wrong can move the stub cashflow by several basis
   points times notional.

### Settlement lag

The number of business days between trade date and settlement date varies
by market:

| Product | Settlement |
|---------|-----------|
| B3 DI futures | T+0 |
| BRL OTC swaps | T+1 |
| US Treasuries / TIPS | T+1 |
| US agency MBS / TBA | Monthly (per SIFMA calendar) |
| Most EUR, GBP, JPY swaps | T+2 |

Settlement lag affects accrued interest: the buyer pays accrued up to the
settlement date, not the trade date. Using the wrong lag shifts the accrued
interest by one or two days of coupon, which matters for large positions
and for reconciliation.

### Roll conventions

Standard dates for swap payment schedules include:

- **IMM dates:** The third Wednesday of March, June, September, and December.
  CDS and some swap markets reference these.
- **End-of-month (EOM):** If the start date is the last business day of a
  month, all subsequent payment dates are also the last business day of
  their respective months.
- **Fixed day-of-month:** e.g., always the 15th (common for NTN-B coupons).

The EOM convention is particularly subtle: a swap starting on February 28
(non-leap year) with EOM convention will have subsequent payment dates on
March 31, June 30, September 30, December 31, etc. Without EOM, it would
pay on March 28, June 28, etc. The difference in accrual periods changes
every cashflow.

---

## Summary of "What Goes Wrong" by Error Type

| Error | Affected instrument(s) | Approximate impact |
|-------|----------------------|-------------------|
| Wrong holiday calendar (BUS/252) | BRL Pre-CDI | ~5K BRL per day per 10M notional |
| Continuous instead of discrete compounding | BRL Pre-CDI | ~2% of notional on a 2-year swap |
| Wrong CPI lag | Inflation bonds | ~0.2% of face per month of lag error |
| No CPI interpolation (step function) | TIPS | Tens of thousands USD on $100M mid-month |
| Wrong deflation floor flag | Inflation bonds | Full CPI decline since issuance at maturity |
| Basis spread on wrong leg | Xccy basis swap | 2x the basis PV (sign flip) |
| ACT/360 instead of ACT/365 for GBP | Xccy basis swap | ~1.4% of annual interest |
| Ignoring delay days | TBA | ~$64K per monthly payment per $100M |
| Stale pool factor | TBA | Linear in error: 1% factor error = 1% PV error |
| Wrong settlement lag | All | 1-2 days of accrued interest |
