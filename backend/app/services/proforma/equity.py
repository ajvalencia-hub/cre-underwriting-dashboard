"""LP/GP equity waterfall: European (whole-fund), IRR-hurdle based.

Structure (see DECISIONS.md for the convention and rejected alternatives):
- LP and GP contribute capital pari passu at lpSplitPct / gpSplitPct.
- Distributions fill sequential bands. Toward each band's target the split is
  the band's (lp, gp) pair; a band is full when the LP's periodic IRR reaches
  the band's annual hurdle:
    band 0: pro-rata (capital shares) until LP IRR = preferred return
    band 1: pro-rata until LP IRR = first tier hurdle (no promote below the
            first hurdle — pref then promote is the standard structure)
    band k: tier (k-1)'s above-hurdle splits until LP IRR = tier k's hurdle
    final:  last tier's above-hurdle splits, uncapped
- "Fill to hurdle" uses the exact closed form: the amount that brings the
  LP's NPV at the hurdle rate to zero is -NPV * (1+r)^m — no root-finding
  inside the waterfall.
- Hurdles are annual; they convert to monthly as (1+h)^(1/12)-1, matching
  the engine's periodic-monthly IRR convention.
"""

from app.services.proforma.returns import equity_multiple, periodic_irr


def _npv_at(rate_monthly: float, flows: list[float]) -> float:
    return sum(cf / (1 + rate_monthly) ** t for t, cf in enumerate(flows))


def _monthly_hurdle(annual: float) -> float:
    return (1 + annual) ** (1 / 12) - 1


def run_waterfall(
    equity_flows: list[float],
    lp_share: float,
    gp_share: float,
    preferred_return: float,
    tiers: list[dict],
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

    valid_tiers = sorted(
        (
            t for t in tiers
            if isinstance(t, dict) and isinstance(t.get("irrHurdle"), (int, float))
        ),
        key=lambda t: t["irrHurdle"],
    )

    # (annual hurdle or None for the uncapped residual band, lp split, gp split)
    bands: list[tuple[float | None, float, float]] = [
        (preferred_return, lp_share, gp_share),
    ]
    if valid_tiers:
        bands.append((valid_tiers[0]["irrHurdle"], lp_share, gp_share))
        for i, tier in enumerate(valid_tiers):
            lp_split = float(tier.get("lpSplitAboveHurdle") or 0.0)
            gp_split = float(tier.get("gpSplitAboveHurdle") or 0.0)
            split_total = lp_split + gp_split
            if split_total <= 0:
                warnings.append(
                    f"Waterfall tier {i + 1} has zero splits — treated as pro-rata."
                )
                lp_split, gp_split = lp_share, gp_share
            elif abs(split_total - 1) > 1e-6:
                warnings.append(
                    f"Waterfall tier {i + 1} splits sum to {split_total:.4f}, not 1 — normalized."
                )
                lp_split, gp_split = lp_split / split_total, gp_split / split_total
            next_hurdle = (
                valid_tiers[i + 1]["irrHurdle"] if i + 1 < len(valid_tiers) else None
            )
            bands.append((next_hurdle, lp_split, gp_split))
    else:
        bands.append((None, lp_share, gp_share))

    promote_paid = 0.0

    for month, cash in enumerate(equity_flows):
        if cash < 0:
            lp_flows[month] += cash * lp_share
            gp_flows[month] += cash * gp_share
            continue
        if cash == 0:
            continue

        remaining = cash
        for annual_hurdle, lp_split, gp_split in bands:
            if remaining <= 1e-9:
                break
            if annual_hurdle is None or lp_split <= 0:
                # Residual band (or a band the LP can never fill) takes the rest.
                lp_flows[month] += remaining * lp_split
                gp_flows[month] += remaining * gp_split
                promote_paid += remaining * max(0.0, gp_split - gp_share)
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
            promote_paid += take * max(0.0, gp_split - gp_share)
            remaining -= take

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
