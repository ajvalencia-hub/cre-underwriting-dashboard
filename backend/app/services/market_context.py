"""Market context: comps, pricing trends, rent trends, demographics, labor
market, housing, macro financing environment, and site risk for a given
market / submarket / asset class.

Two tiers of data here, and they're kept structurally distinct:

1. Comps and cap-rate/price trends — no free public source exists for these
   (real comps data is Crexi/Reonomy/CompStak/RCA territory, all paid or
   partnership-gated). `_mock_pricing_and_comps` generates deterministic,
   clearly-labeled placeholder numbers (seeded from market/submarket/asset
   class so the same query always returns the same "snapshot"). Swap it for
   a real provider once you have credentials for one — same interface.

2. Demographics, labor market, housing, macro rates, and site risk — these
   ARE available from real, free, public government APIs (Census, BLS, BEA,
   FRED, HUD, FHFA, FEMA), wired up in app/services/data_sources/. Each
   degrades gracefully to `dataSource: "unavailable"` with an explanatory
   note when its API key isn't configured (see backend/.env.example) or the
   market couldn't be geocoded — never fabricated numbers.
"""

import hashlib
import random
from datetime import date, timedelta
from typing import Callable

from app.services.data_sources import bea, bls, census_acs, fema, fhfa, fred, geocode, hud

# Rough, illustrative ranges per asset class — NOT sourced from real market
# data. Used only to make placeholder comps/pricing land somewhere plausible.
_ASSET_CLASS_RANGES = {
    "multifamily": {
        "cap_rate": (0.045, 0.065),
        "price_per_unit": (150_000, 300_000),
        "rent_growth": (0.02, 0.05),
        "vacancy": (0.04, 0.08),
    },
    "office": {
        "cap_rate": (0.06, 0.085),
        "price_per_unit": (150, 400),  # $/SF
        "rent_growth": (-0.01, 0.03),
        "vacancy": (0.12, 0.20),
    },
    "retail": {
        "cap_rate": (0.06, 0.075),
        "price_per_unit": (150, 350),  # $/SF
        "rent_growth": (0.01, 0.03),
        "vacancy": (0.05, 0.10),
    },
    "industrial": {
        "cap_rate": (0.05, 0.065),
        "price_per_unit": (80, 180),  # $/SF
        "rent_growth": (0.03, 0.07),
        "vacancy": (0.03, 0.06),
    },
    "hotel": {
        "cap_rate": (0.07, 0.09),
        "price_per_unit": (80_000, 250_000),  # $/key
        "rent_growth": (0.02, 0.06),  # RevPAR growth
        "vacancy": (0.25, 0.40),  # modeled as (1 - occupancy)
    },
}
_DEFAULT_RANGE = _ASSET_CLASS_RANGES["multifamily"]

_PRICE_UNIT_LABEL = {
    "multifamily": "$/unit",
    "office": "$/SF",
    "retail": "$/SF",
    "industrial": "$/SF",
    "hotel": "$/key",
}


def _seeded_random(*parts: str) -> random.Random:
    key = "|".join(p.strip().lower() for p in parts)
    seed = int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**32)
    return random.Random(seed)


def _mock_pricing_and_comps(market: str, submarket: str, asset_class: str) -> dict:
    rng = _seeded_random(market, submarket, asset_class)
    ranges = _ASSET_CLASS_RANGES.get(asset_class, _DEFAULT_RANGE)
    price_label = _PRICE_UNIT_LABEL.get(asset_class, "$/unit")

    cap_low, cap_high = sorted(rng.uniform(*ranges["cap_rate"]) for _ in range(2))
    price_low, price_high = sorted(rng.uniform(*ranges["price_per_unit"]) for _ in range(2))
    rent_growth = rng.uniform(*ranges["rent_growth"])
    vacancy = rng.uniform(*ranges["vacancy"])

    comps = []
    for i in range(4):
        sale_price = rng.uniform(price_low, price_high)
        comps.append(
            {
                "name": f"{submarket or market} {asset_class.title()} Comp {i + 1}",
                "submarket": submarket or market,
                "type": "sale" if i % 2 == 0 else "lease",
                "date": (date.today() - timedelta(days=rng.randint(15, 400))).isoformat(),
                "pricePerUnit": round(sale_price, 2),
                "priceUnitLabel": price_label,
                "capRate": round(rng.uniform(cap_low, cap_high), 4),
            }
        )

    return {
        "comps": comps,
        "pricingTrends": {
            "capRateLow": round(cap_low, 4),
            "capRateHigh": round(cap_high, 4),
            "priceLow": round(price_low, 2),
            "priceHigh": round(price_high, 2),
            "priceUnitLabel": price_label,
        },
        "rentTrends": {
            "rentGrowthYoY": round(rent_growth, 4),
            "vacancyPct": round(vacancy, 4),
        },
    }


ProviderFn = Callable[[str, str, str], dict]

# Swap this to point at a real comps/pricing provider (Crexi Partner API,
# Reonomy, ATTOM Data, CompStak, RentCast, etc.) once credentials are
# available. Everything else in this file (real government data sources)
# is unaffected by this swap.
_active_pricing_provider: ProviderFn = _mock_pricing_and_comps


def get_market_context(market: str, submarket: str, asset_class: str) -> dict:
    location = geocode.geocode(market, submarket)
    state_fips = location.get("stateFips")
    county_fips = location.get("countyFips")
    cbsa_code = location.get("cbsaCode")
    lat, lon = location.get("lat"), location.get("lon")

    pricing_and_comps = _active_pricing_provider(market, submarket, asset_class)

    demographics = census_acs.get_demographics(state_fips, county_fips)

    labor_market = bls.get_unemployment_rate(state_fips, county_fips)
    income = bea.get_income_growth(state_fips, county_fips)
    if income.get("dataSource") == "bea":
        labor_market = {**labor_market, **income}
    elif labor_market.get("dataSource") == "unavailable" and income.get("dataSource") != "unavailable":
        labor_market = income

    housing = fhfa.get_home_price_appreciation(cbsa_code)
    fmr = hud.get_fair_market_rents(state_fips, county_fips)
    if fmr.get("dataSource") == "hud":
        housing = {**housing, **fmr} if housing.get("dataSource") == "fhfa" else fmr

    macro = fred.get_macro_rates()
    site_risk = fema.get_flood_zone(lat, lon)

    return {
        "market": market,
        "submarket": submarket,
        "assetClass": asset_class,
        "location": location,
        **pricing_and_comps,
        "demographics": demographics,
        "laborMarket": labor_market,
        "housing": housing,
        "macro": macro,
        "siteRisk": site_risk,
        "meta": {
            "dataSource": "mixed",
            "note": (
                "Comps and cap-rate/price trends are illustrative placeholder data "
                "(no free public source exists for those — wire up Crexi Partner API, "
                "Reonomy, ATTOM Data, CompStak, or RentCast in "
                "app/services/market_context.py to replace them). Demographics, labor "
                "market, housing, macro rates, and site risk are real data from free "
                "public sources (Census, BLS, BEA, FRED, HUD, FHFA, FEMA) where the "
                "relevant API key is configured — see backend/.env.example."
            ),
        },
    }
