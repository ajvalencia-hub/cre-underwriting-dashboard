"""LP/GP equity waterfall — two styles plus an optional GP catch-up.

Styles (see DECISIONS.md for conventions and rejected alternatives):

**european** (default, Run-1 behavior preserved exactly): whole-fund,
IRR-hurdle bands. Distributions fill sequential bands; a band is full when
the LP's periodic IRR reaches the band's annual hurdle, computed with the
exact closed form (the amount that brings the LP's NPV at the hurdle rate to
zero is -NPV * (1+r)^m). Band order: pro-rata to the pref, pro-rata to the
first tier hurdle, then each tier's above-hurdle splits (last tier uncapped).
Hurdles are annual, converted to monthly as (1+h)^(1/12)-1 — matching the
engine's periodic-monthly IRR convention.

**american** (deal-by-deal ledger): the preferred return accrues on a
capital-account ledger rather than through IRR lookback. Each month the
accrual base is (unreturned capital + accrued unpaid pref) — unpaid pref
compounds monthly at (1+pref)^(1/12)-1. Every distribution applies in strict
order: (1) accrued pref, pro rata by accrued balances; (2) return of
capital, pro rata by unreturned balances; (3) the promote stack, where the
FIRST tier's splits apply immediately (its schema hurdle is deemed satisfied
by pref + full capital return — the deal-by-deal convention that promote
crystallizes over the pref) and any HIGHER tier hurdles remain
LP-IRR-measured exactly as in european.

**GP catch-up** (both styles, replaces the band between pref and the first
promote tier): once aggregate capital is back, the GP receives catchUpPct of
each distribution dollar until the GP's cumulative PROFIT equals promotePct
(the first tier's GP split) of cumulative total profit — profit measured as
each partner's nominal net position (distributions received minus capital
contributed), so the LP's pref profit counts toward the target, the textbook
treatment. Full catch-up = catchUpPct 1.0. A catchUpPct <= the tier-1
promote can never reach the target and is skipped with a warning.
"""

from app.services.proforma.returns import equity_multiple, periodic_irr

_CATCH_UP = "catch_up"  # sentinel band kind


def _npv_at(rate_monthly: float, flows: list[float]) -> float:
    return sum(cf / (1 + rate_monthly) ** t for t, cf in enumerate(flows))


def _monthly_hurdle(annual: float) -> float:
    return (1 + annual) ** (1 / 12) - 1


def _normalize_tiers(tiers: list[dict], lp_share: float, gp_share: float, warnings: list[str]):
    valid = sorted(
        (
            t for t in tiers
            if isinstance(t, dict) and isinstance(t.get("irrHurdle"), (int, float))
        ),
        key=lambda t: t["irrHurdle"],
    )
    normalized = []
    for i, tier in enumerate(valid):
        lp_split = float(tier.get("lpSplitAboveHurdle") or 0.0)
        gp_split = float(tier.get("gpSplitAboveHurdle") or 0.0)
        split_total = lp_split + gp_split
        if split_total <= 0:
            warnings.append(f"Waterfall tier {i + 1} has zero splits — treated as pro-rata.")
            lp_split, gp_split = lp_share, gp_share
        elif abs(split_total - 1) > 1e-6:
            warnings.append(
                f"Waterfall tier {i + 1} splits sum to {split_total:.4f}, not 1 — normalized."
            )
            lp_split, gp_split = lp_split / split_total, gp_split / split_total
        normalized.append({"hurdle": float(tier["irrHurdle"]), "lp": lp_split, "gp": gp_split})
    return normalized


def run_waterfall(
    equity_flows: list[float],
    lp_share: float,
    gp_share: float,
    preferred_return: float,
    tiers: list[dict],
    style: str = "european",
    catch_up_pct: float | None = None,
) -> dict:
    """equity_flows: the levered monthly equity cash-flow vector (index 0 =
    close; negatives are contributions, positives are distributions).
    tiers: [{irrHurdle, lpSplitAboveHurdle, gpSplitAboveHurdle}, ...].

    Returns {"lpFlows", "gpFlows", "lpIrr", "gpIrr", "lpMultiple",
    "gpMultiple", "promotePaid", "warnings"}.
    """
    warnings: list[str] = []
    months = len(equity_flows)
    lp_flows = [0.0] * months
    gp_flows = [0.0] * months

    total = lp_share + gp_share
    if total <= 0:
        return {
            "lpFlows": lp_flows, "gpFlows": gp_flows, "lpIrr": None, "gpIrr": None,
            "lpMultiple": None, "gpMultiple": None, "promotePaid": 0.0,
            "warnings": ["LP + GP splits are zero — waterfall skipped."],
        }
    if abs(total - 1) > 1e-6:
        warnings.append(f"LP+GP capital splits sum to {total:.4f}, not 1 — normalized.")
        lp_share, gp_share = lp_share / total, gp_share / total

    normalized_tiers = _normalize_tiers(tiers, lp_share, gp_share, warnings)

    catch_up_active = False
    catch_up_c = 0.0
    promote_pct = normalized_tiers[0]["gp"] if normalized_tiers else 0.0
    if catch_up_pct is not None and catch_up_pct > 0:
        if not normalized_tiers:
            warnings.append(
                "GP catch-up configured but no promote tiers exist — catch-up ignored."
            )
        elif catch_up_pct <= promote_pct:
            warnings.append(
                f"Catch-up percentage ({catch_up_pct:.0%}) does not exceed the "
                f"tier-1 promote ({promote_pct:.0%}) — the catch-up target is "
                "unreachable, so the catch-up band is skipped."
            )
        else:
            catch_up_active = True
            catch_up_c = float(catch_up_pct)

    # Promote-stack bands: (hurdle_or_None, lp_split, gp_split) tuples or the
    # _CATCH_UP sentinel. A configured catch-up REPLACES the band that
    # otherwise runs from the pref to the first tier hurdle.
    promote_bands: list = []
    if normalized_tiers:
        if catch_up_active:
            promote_bands.append(_CATCH_UP)
        elif style != "american":
            # european: pro-rata continues to the first tier hurdle.
            promote_bands.append((normalized_tiers[0]["hurdle"], lp_share, gp_share))
        # american without catch-up: tier-1 splits start right after pref+ROC.
        for i, tier in enumerate(normalized_tiers):
            next_hurdle = (
                normalized_tiers[i + 1]["hurdle"] if i + 1 < len(normalized_tiers) else None
            )
            promote_bands.append((next_hurdle, tier["lp"], tier["gp"]))
    else:
        promote_bands.append((None, lp_share, gp_share))

    promote_paid = 0.0

    def catch_up_remaining() -> float:
        """Further distribution x (at the catch-up split) that reaches
        GP_profit + c*x = p * (total_profit + x), profits = nominal net
        positions. Waits (returns 0) while capital is still outstanding."""
        lp_net = sum(lp_flows)
        gp_net = sum(gp_flows)
        if lp_net + gp_net < 0:
            return 0.0
        x = (promote_pct * (lp_net + gp_net) - gp_net) / (catch_up_c - promote_pct)
        return max(0.0, x)

    def distribute_bands(month: int, remaining: float, bands: list) -> float:
        """Run `remaining` through hurdle/catch-up bands; returns undistributed."""
        nonlocal promote_paid
        for band in bands:
            if remaining <= 1e-9:
                break
            if band is _CATCH_UP:
                target = catch_up_remaining()
                if target <= 1e-9:
                    continue
                take = min(remaining, target)
                lp_flows[month] += take * (1 - catch_up_c)
                gp_flows[month] += take * catch_up_c
                promote_paid += max(0.0, take * (catch_up_c - gp_share))
                remaining -= take
                continue

            annual_hurdle, lp_split, gp_split = band
            if annual_hurdle is None or lp_split <= 0:
                lp_flows[month] += remaining * lp_split
                gp_flows[month] += remaining * gp_split
                promote_paid += max(0.0, remaining * (gp_split - gp_share))
                remaining = 0.0
                break

            hurdle_monthly = _monthly_hurdle(annual_hurdle)
            npv_now = _npv_at(hurdle_monthly, lp_flows)
            if npv_now >= 0:
                continue  # LP already at/above this hurdle — band is full
            lp_amount_to_fill = -npv_now * (1 + hurdle_monthly) ** month
            band_total_to_fill = lp_amount_to_fill / lp_split
            take = min(remaining, band_total_to_fill)
            lp_flows[month] += take * lp_split
            gp_flows[month] += take * gp_split
            promote_paid += max(0.0, take * (gp_split - gp_share))
            remaining -= take
        return remaining

    if style == "american":
        # Ledgers per partner: unreturned capital and accrued unpaid pref.
        pref_rate = _monthly_hurdle(preferred_return)
        capital = {"lp": 0.0, "gp": 0.0}
        pref_accrued = {"lp": 0.0, "gp": 0.0}
        shares = {"lp": lp_share, "gp": gp_share}
        flows = {"lp": lp_flows, "gp": gp_flows}

        for month, cash in enumerate(equity_flows):
            # Accrue pref monthly on (capital + accrued pref) — compounded.
            if month >= 1:
                for k in ("lp", "gp"):
                    pref_accrued[k] += (capital[k] + pref_accrued[k]) * pref_rate

            if cash < 0:
                for k in ("lp", "gp"):
                    amount = -cash * shares[k]
                    capital[k] += amount
                    flows[k][month] -= amount
                continue
            if cash == 0:
                continue

            remaining = cash
            # (1) accrued pref, pro rata by accrued balances.
            total_pref = pref_accrued["lp"] + pref_accrued["gp"]
            if total_pref > 1e-9 and remaining > 1e-9:
                pay = min(remaining, total_pref)
                for k in ("lp", "gp"):
                    piece = pay * (pref_accrued[k] / total_pref)
                    pref_accrued[k] -= piece
                    flows[k][month] += piece
                remaining -= pay
            # (2) return of capital, pro rata by unreturned balances.
            total_capital = capital["lp"] + capital["gp"]
            if total_capital > 1e-9 and remaining > 1e-9:
                pay = min(remaining, total_capital)
                for k in ("lp", "gp"):
                    piece = pay * (capital[k] / total_capital)
                    capital[k] -= piece
                    flows[k][month] += piece
                remaining -= pay
            # (3) promote stack.
            if remaining > 1e-9:
                distribute_bands(month, remaining, promote_bands)

    else:  # european — Run-1 band machinery, pref band first
        bands: list = [(preferred_return, lp_share, gp_share), *promote_bands]
        for month, cash in enumerate(equity_flows):
            if cash < 0:
                lp_flows[month] += cash * lp_share
                gp_flows[month] += cash * gp_share
                continue
            if cash == 0:
                continue
            distribute_bands(month, cash, bands)

    return {
        "lpFlows": lp_flows,
        "gpFlows": gp_flows,
        "lpIrr": periodic_irr(lp_flows),
        "gpIrr": periodic_irr(gp_flows),
        "lpMultiple": equity_multiple(lp_flows),
        "gpMultiple": equity_multiple(gp_flows),
        "promotePaid": promote_paid,
        "warnings": warnings,
    }
