"""Address-driven underwriting benchmarks: deal address -> geography ->
per-metric flags comparing the deal's assumptions to public data.

Each flag: {metric, subjectValue, benchmarkValue, source, asOf, verdict,
explanation, relatedFieldIds}. Verdicts: ok | caution | warning. A source
that fails or isn't configured contributes an "unavailable" note instead of
a flag — one failed source never blocks the rest. Context only: nothing here
ever mutates deal inputs.

Rent percentile (see DECISIONS.md): HUD publishes FMR as the 40th percentile
of market rents and ACS gives the median (50th). Two quantile points pin a
log-normal fit, from which the subject rent's percentile is estimated —
warn above the 85th, caution above the 70th.
"""

import math
import re

from app.services.data_sources import bls, census_acs, fema, fhfa, geocode, hud
from app.services.data_sources.source_cache import cached_fetch

RENT_PERCENTILE_WARNING = 0.85
RENT_PERCENTILE_CAUTION = 0.70
RENT_GROWTH_CAUTION_SPREAD = 0.02  # subject growth vs benchmark, absolute
RENT_GROWTH_WARNING_SPREAD = 0.04
EXPENSE_RATIO_BAND = (0.30, 0.55)
EMPLOYMENT_DECLINE_WARNING = -0.01
_Z_40TH = -0.2533471  # standard normal quantile at p = 0.40

# HUD FMR field per bedroom count.
_FMR_FIELDS = {0: "fmrStudio", 1: "fmr1BR", 2: "fmr2BR", 3: "fmr3BR"}

HIGH_RISK_FLOOD_ZONES = {"A", "AE", "AH", "AO", "V", "VE"}


def _normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def estimate_rent_percentile(
    subject_rent: float, fmr_40th: float | None, acs_median_50th: float | None
) -> float | None:
    """Log-normal fit through (40th = FMR, 50th = ACS median). Falls back to
    a single-point comparison when only one quantile is available; returns
    None when neither is usable."""
    if subject_rent <= 0:
        return None
    if fmr_40th and acs_median_50th and 0 < fmr_40th < acs_median_50th:
        mu = math.log(acs_median_50th)
        sigma = (math.log(acs_median_50th) - math.log(fmr_40th)) / -_Z_40TH
        return _normal_cdf((math.log(subject_rent) - mu) / sigma)
    anchor = acs_median_50th or fmr_40th
    if not anchor or anchor <= 0:
        return None
    # One quantile point: assume a typical rent-distribution spread
    # (sigma ~ 0.35 in log space) around it.
    anchor_p = 0.50 if acs_median_50th else 0.40
    mu = math.log(anchor) - 0.35 * _z_for(anchor_p)
    return _normal_cdf((math.log(subject_rent) - mu) / 0.35)


def _z_for(p: float) -> float:
    return 0.0 if p == 0.50 else _Z_40TH


def _flag(metric, subject, benchmark, source, as_of, verdict, explanation, related=None) -> dict:
    return {
        "metric": metric,
        "subjectValue": subject,
        "benchmarkValue": benchmark,
        "source": source,
        "asOf": as_of,
        "verdict": verdict,
        "explanation": explanation,
        "relatedFieldIds": related or [],
    }


def _weighted_fmr(fmr: dict, bedroom_mix: list[dict] | None) -> tuple[float | None, str]:
    """FMR for the deal's bedroom mix (unit-count weighted); 2BR when no mix."""
    if bedroom_mix:
        total_weight, total = 0.0, 0.0
        for row in bedroom_mix:
            count = row.get("count") or 0
            fmr_value = fmr.get(_FMR_FIELDS.get(row.get("bedrooms"), "fmr2BR"))
            if count and fmr_value:
                total += count * float(fmr_value)
                total_weight += count
        if total_weight > 0:
            return total / total_weight, "bedroom-mix weighted"
    two_br = fmr.get("fmr2BR")
    return (float(two_br) if two_br else None), "2BR"


_EXPENSE_DOLLAR_FIELDS = [
    "realEstateTaxes", "insurance", "utilities", "repairsMaintenance",
    "payroll", "generalAdmin", "replacementReserves",
]
_BEDROOM_RE = re.compile(r"(\d)\s*(bd|br|bed)", re.IGNORECASE)


def derive_subject_from_inputs(inputs: dict) -> dict:
    """Backend twin of the frontend's deriveBenchmarkSubject — used by the IC
    memo route, which only has the scenario's stored inputs."""
    subject: dict = {}

    unit_mix = inputs.get("unitMix")
    if isinstance(unit_mix, list):
        total_rent, total_units = 0.0, 0
        mix: dict[int, int] = {}
        for row in unit_mix:
            if not isinstance(row, dict):
                continue
            count = row.get("unitCount") or 0
            rent = row.get("inPlaceRent") or row.get("marketRent") or 0
            if count and rent:
                total_rent += count * float(rent)
                total_units += int(count)
            unit_type = str(row.get("unitType") or "")
            match = _BEDROOM_RE.search(unit_type)
            bedrooms = (
                min(3, int(match.group(1))) if match
                else 0 if re.search(r"studio|eff", unit_type, re.IGNORECASE)
                else None
            )
            if count and bedrooms is not None:
                mix[bedrooms] = mix.get(bedrooms, 0) + int(count)
        if total_units:
            subject["avgRentMonthly"] = total_rent / total_units
        if mix:
            subject["bedroomMix"] = [{"bedrooms": b, "count": c} for b, c in mix.items()]

    growth = inputs.get("rentGrowthPct")
    if isinstance(growth, (int, float)) and inputs.get("rentGrowthMode") != "flat":
        subject["rentGrowthPct"] = float(growth)

    gpr = inputs.get("grossPotentialRent")
    if isinstance(gpr, (int, float)) and gpr > 0:
        vacancy = inputs.get("vacancyPct") or 0
        credit = inputs.get("creditLossPct") or 0
        other = inputs.get("otherIncome") or 0
        egi = gpr * (1 - float(vacancy)) * (1 - float(credit)) + float(other)
        if egi > 0:
            fixed = sum(
                float(inputs.get(f) or 0)
                for f in _EXPENSE_DOLLAR_FIELDS
                if isinstance(inputs.get(f), (int, float))
            )
            fee = float(inputs.get("managementFeePct") or 0) * egi
            if fixed + fee > 0:
                subject["expenseRatioPct"] = (fixed + fee) / egi

    exit_cap = inputs.get("exitCapRatePct")
    if isinstance(exit_cap, (int, float)) and exit_cap > 0:
        subject["exitCapRatePct"] = float(exit_cap)

    return subject


def build_benchmarks(
    address: str,
    market: str,
    submarket: str,
    asset_class: str,
    subject: dict,
) -> dict:
    """subject: {avgRentMonthly?, bedroomMix?: [{bedrooms, count}],
    rentGrowthPct?, expenseRatioPct?}. Returns {location, flags,
    unavailable}."""
    flags: list[dict] = []
    unavailable: list[dict] = []

    geo_key = f"geo_{address or submarket or market}"
    location = cached_fetch(
        geo_key,
        lambda: {**geocode.geocode(market, submarket, address), "dataSource": "geocode"},
    )
    state_fips = location.get("stateFips")
    county_fips = location.get("countyFips")
    cbsa_code = location.get("cbsaCode")
    county_key = f"{state_fips}{county_fips}"

    def load(name: str, fetch) -> dict:
        try:
            return cached_fetch(name, fetch)
        except Exception as exc:  # noqa: BLE001 - a source bug must not kill the panel
            return {"dataSource": "unavailable", "note": f"{name} failed unexpectedly: {exc}"}

    acs = load(f"acs_{county_key}", lambda: census_acs.get_demographics(state_fips, county_fips))
    fmr = load(f"hud_{county_key}", lambda: hud.get_fair_market_rents(state_fips, county_fips))
    hpa = load(f"fhfa_{cbsa_code}", lambda: fhfa.get_home_price_appreciation(cbsa_code))
    employment = load(
        f"bls_emp_{county_key}", lambda: bls.get_employment_trend(state_fips, county_fips)
    )
    flood = load(
        f"fema_{location.get('lat')}_{location.get('lon')}",
        lambda: fema.get_flood_zone(location.get("lat"), location.get("lon")),
    )

    for name, result in (
        ("census_acs", acs), ("hud", fmr), ("fhfa", hpa), ("bls", employment), ("fema", flood),
    ):
        if result.get("dataSource") == "unavailable":
            unavailable.append({"source": name, "note": result.get("note", "unavailable")})

    # ---- subject rent vs ACS median + HUD FMR ----------------------------
    subject_rent = subject.get("avgRentMonthly")
    acs_median = acs.get("medianGrossRent")
    fmr_value, fmr_basis = (
        _weighted_fmr(fmr, subject.get("bedroomMix")) if fmr.get("dataSource") == "hud" else (None, "")
    )
    if subject_rent and (acs_median or fmr_value):
        percentile = estimate_rent_percentile(subject_rent, fmr_value, acs_median)
        if percentile is not None:
            verdict = (
                "warning" if percentile > RENT_PERCENTILE_WARNING
                else "caution" if percentile > RENT_PERCENTILE_CAUTION
                else "ok"
            )
            benchmark_bits = []
            if acs_median:
                benchmark_bits.append(f"ACS median ${acs_median:,.0f}")
            if fmr_value:
                benchmark_bits.append(f"HUD FMR ({fmr_basis}) ${fmr_value:,.0f}")
            flags.append(
                _flag(
                    "rent_vs_market",
                    subject_rent,
                    acs_median or fmr_value,
                    "census_acs + hud",
                    str(acs.get("acsYear") or fmr.get("year") or ""),
                    verdict,
                    f"Subject rent ${subject_rent:,.0f}/mo sits at the ~{percentile * 100:.0f}th "
                    f"percentile of market rents ({', '.join(benchmark_bits)}).",
                    ["unitMix", "grossPotentialRent"],
                )
            )

    # ---- rent growth assumption vs FHFA HPA ------------------------------
    rent_growth = subject.get("rentGrowthPct")
    hpa_yoy = hpa.get("hpiYoYAppreciation")
    if rent_growth is not None and hpa_yoy is not None:
        spread = rent_growth - hpa_yoy
        verdict = (
            "warning" if spread > RENT_GROWTH_WARNING_SPREAD
            else "caution" if spread > RENT_GROWTH_CAUTION_SPREAD
            else "ok"
        )
        flags.append(
            _flag(
                "rent_growth_vs_hpa",
                rent_growth,
                hpa_yoy,
                "fhfa",
                str(hpa.get("asOf") or ""),
                verdict,
                f"Rent growth assumption {rent_growth * 100:.1f}%/yr vs metro home-price "
                f"appreciation {hpa_yoy * 100:.1f}% YoY ({hpa.get('metroName', 'metro')}).",
                ["rentGrowthPct"],
            )
        )

    # ---- expense ratio vs band -------------------------------------------
    expense_ratio = subject.get("expenseRatioPct")
    if expense_ratio is not None:
        low, high = EXPENSE_RATIO_BAND
        verdict = "ok" if low <= expense_ratio <= high else "caution"
        flags.append(
            _flag(
                "expense_ratio",
                expense_ratio,
                (low + high) / 2,
                "band",
                "",
                verdict,
                f"Expense ratio {expense_ratio * 100:.0f}% of EGI vs the typical "
                f"{low * 100:.0f}–{high * 100:.0f}% band.",
                ["realEstateTaxes", "managementFeePct"],
            )
        )

    # ---- flood zone -------------------------------------------------------
    if flood.get("dataSource") == "fema":
        zone = flood.get("floodZone", "")
        verdict = "warning" if zone in HIGH_RISK_FLOOD_ZONES else "caution" if zone == "D" else "ok"
        flags.append(
            _flag(
                "flood_zone", zone, "X", "fema", "",
                verdict,
                f"FEMA flood zone {zone or 'X'}: {flood.get('description', '')} "
                + ("Flood insurance will be required by lenders." if verdict == "warning" else ""),
                ["insurance", "address"],
            )
        )

    # ---- employment trend --------------------------------------------------
    emp_growth = employment.get("employmentYoYGrowth")
    if emp_growth is not None:
        verdict = (
            "warning" if emp_growth < EMPLOYMENT_DECLINE_WARNING
            else "caution" if emp_growth < 0
            else "ok"
        )
        flags.append(
            _flag(
                "employment_trend",
                emp_growth,
                0.0,
                "bls",
                str(employment.get("asOf") or ""),
                verdict,
                f"County employment {'grew' if emp_growth >= 0 else 'declined'} "
                f"{abs(emp_growth) * 100:.1f}% YoY.",
                ["market"],
            )
        )

    return {"location": location, "flags": flags, "unavailable": unavailable}
