"""VAYU INDEX — Phase 1: Synthetic Airfare Observation Dataset Generator
=======================================================================

PURPOSE
-------
Generates a SYNTHETIC dataset of airfare observations that follows the
finalized schema and methodological rules agreed on before implementation
began (observation definition, comparability hierarchy, duplicate rules,
advance-purchase banding, missing-data handling, and anomaly categories).

This is NOT real airfare data. Every price, route pattern, and edge case
here is invented purely so the downstream pipeline stages (validation,
deduplication, source consolidation, normalization, anomaly detection,
aggregation, index calculation) have something realistic — with KNOWN
ground truth — to be built and tested against.

DESIGN NOTES (matches the agreed methodology)
----------------------------------------------
- Product identity for comparison purposes = route + fare_class +
  travel_date + advance_purchase_window. flight_number, departure_time,
  and source are stored as attributes, not identity fields.
- Advance-purchase windows are BANDED (not exact-day), per the prototype
  recommendation, because banding tolerates realistic, imperfect
  scraping schedules.
- A deliberate set of edge cases is injected on top of the "normal"
  simulated data, each one tagged in edge_case_log.csv with the category
  it's meant to test (invalid / duplicate / missing / anomaly / etc.),
  so Phase 2+ engines can be checked against a known answer key.
- Prices are generated from a simple synthetic curve (fares rise as the
  advance-purchase window shrinks) plus random jitter — this is NOT a
  real fare model, just enough structure to make the dataset behave like
  airfares behave, for testing purposes.

OUTPUT FILES
------------
1. vayu_synthetic_observations.csv  — the raw observation dataset
2. edge_case_log.csv                — ground-truth log of injected edge cases
3. data_dictionary.md               — field-by-field schema documentation
"""

import csv
import os
import random
import hashlib
from datetime import datetime, timedelta

random.seed(42)  # reproducibility

# ---------------------------------------------------------------------------
# CONFIGURATION (all SYNTHETIC)
# ---------------------------------------------------------------------------

COLLECTION_DAYS = [
    datetime(2026, 9, 5),
    datetime(2026, 9, 6),
    datetime(2026, 9, 7),
]
COLLECTION_TIMES = [(9, 0), (14, 30), (20, 15)]  # 3 collection rounds/day

ROUTES = [("DEL", "BOM"), ("BLR", "HYD"), ("DEL", "BLR"), ("MAA", "CCU")]

# carrier code -> flight number, per route
CARRIERS = {
    ("DEL", "BOM"): [("6E", "6E-2341"), ("AI", "AI-865"), ("QP", "QP-1123")],
    ("BLR", "HYD"): [("SG", "SG-451"), ("6E", "6E-773")],
    ("DEL", "BLR"): [("6E", "6E-5011"), ("AI", "AI-503"), ("UK", "UK-822")],
    ("MAA", "CCU"): [("6E", "6E-6120"), ("SG", "SG-988")],
}

FARE_CLASSES = ["Economy Saver", "Economy Standard", "Economy Flexi"]
BASE_FARE_BY_CLASS = {
    "Economy Saver": 4000,
    "Economy Standard": 5200,
    "Economy Flexi": 6300,
}

SOURCES = ["AirlineSite", "MMT", "Cleartrip", "Goibibo"]

# Advance-purchase bands: (label, low_days, high_days) — SYNTHETIC, illustrative
WINDOW_BANDS = [
    ("T1", 0, 2),
    ("T7", 5, 9),
    ("T15", 12, 18),
    ("T30", 25, 35),
    ("T45", 40, 50),
]

# Departure dates we will actually generate observations for (fixed set,
# chosen so each falls inside exactly one band relative to each collection day)
TRAVEL_DATES = [
    datetime(2026, 9, 6),   # ~T1 from Sep 5
    datetime(2026, 9, 12),  # ~T7 from Sep 5
    datetime(2026, 9, 20),  # ~T15 from Sep 5
    datetime(2026, 10, 5),  # ~T30 from Sep 5
    datetime(2026, 10, 20), # ~T45 from Sep 5
]

FEES_CHOICES = [100, 120, 150, 180]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

_obs_counter = 1
def new_id():
    global _obs_counter
    oid = f"OBS{_obs_counter:05d}"
    _obs_counter += 1
    return oid

def make_hash(*parts):
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:12]

def window_for(adv_days):
    for label, lo, hi in WINDOW_BANDS:
        if lo <= adv_days <= hi:
            return f"{label}({lo}-{hi})"
    return "OUT_OF_BAND"

def price_curve(fare_class, adv_days, jitter=True):
    """SYNTHETIC price curve: fares rise as the booking window shrinks."""
    base = BASE_FARE_BY_CLASS[fare_class]
    curve_factor = 1 + max(0, (20 - adv_days)) * 0.03
    price = base * curve_factor
    if jitter:
        price *= random.uniform(0.95, 1.08)
    base_fare = round(price)
    taxes = round(price * 0.19)
    fees = random.choice(FEES_CHOICES)
    total_fare = base_fare + taxes + fees
    return base_fare, taxes, fees, total_fare

FIELDNAMES = [
    "observation_id", "capture_signature", "economic_signature",
    "origin", "destination", "carrier", "flight_number",
    "travel_date", "departure_time",
    "collection_timestamp", "advance_purchase_days", "advance_purchase_window",
    "fare_class", "base_fare", "taxes", "fees", "total_fare",
    "source", "availability_status",
]

rows = []
edge_cases = []  # ground-truth log: (observation_id, category, expected_handling, note)

def add_row(origin, destination, carrier, flight_number, travel_date, departure_time,
            collection_dt, fare_class, base_fare, taxes, fees, total_fare,
            source, availability="Available", obs_id=None):
    if obs_id is None:
        obs_id = new_id()
    # Use calendar-date subtraction (date() on both sides) so the result
    # matches the validator's Rule 11 recomputation exactly — a full-datetime
    # subtraction is off by one whenever collection_dt has a non-zero time.
    adv_days = (travel_date.date() - collection_dt.date()).days
    window = window_for(adv_days) if 0 <= adv_days <= 50 else "OUT_OF_BAND"
    capture_sig = make_hash(flight_number, fare_class, travel_date.date(), source,
                             collection_dt.strftime("%Y-%m-%d %H:%M"))
    economic_sig = make_hash(origin, destination, fare_class, travel_date.date(), window)
    row = {
        "observation_id": obs_id,
        "capture_signature": capture_sig,
        "economic_signature": economic_sig,
        "origin": origin,
        "destination": destination,
        "carrier": carrier,
        "flight_number": flight_number,
        "travel_date": travel_date.strftime("%Y-%m-%d"),
        "departure_time": departure_time,
        "collection_timestamp": collection_dt.strftime("%Y-%m-%d %H:%M"),
        "advance_purchase_days": adv_days,
        "advance_purchase_window": window,
        "fare_class": fare_class,
        "base_fare": base_fare,
        "taxes": taxes,
        "fees": fees,
        "total_fare": total_fare,
        "source": source,
        "availability_status": availability,
    }
    rows.append(row)
    return obs_id, row

# ---------------------------------------------------------------------------
# 1. "NORMAL" SIMULATED COLLECTION ROUNDS
# ---------------------------------------------------------------------------
# For each route, each collection day/time, sample a realistic subset of
# (carrier, fare_class, source, travel_date) combinations rather than a full
# cross product — real scraping runs don't hit every possible combination
# every single round.

DEPARTURE_TIME_BY_FLIGHT = {}  # cache a fixed departure time per flight number

for collection_day in COLLECTION_DAYS:
    for (hh, mm) in COLLECTION_TIMES:
        collection_dt = collection_day.replace(hour=hh, minute=mm)
        for route in ROUTES:
            origin, destination = route
            for carrier, flight_number in CARRIERS[route]:
                if flight_number not in DEPARTURE_TIME_BY_FLIGHT:
                    DEPARTURE_TIME_BY_FLIGHT[flight_number] = f"{random.randint(5,21):02d}:{random.choice(['00','15','30','45'])}"
                departure_time = DEPARTURE_TIME_BY_FLIGHT[flight_number]

                for travel_date in TRAVEL_DATES:
                    adv_days = (travel_date.date() - collection_dt.date()).days
                    if adv_days < 0:
                        continue  # can't observe a fare for a date already past
                    # Not every fare class is scraped every round (realistic sparsity)
                    classes_this_round = random.sample(
                        FARE_CLASSES, k=random.choice([1, 1, 2])
                    )
                    for fare_class in classes_this_round:
                        # Not every source is checked every round either
                        sources_this_round = random.sample(
                            SOURCES, k=random.choice([1, 1, 2])
                        )
                        for source in sources_this_round:
                            base_fare, taxes, fees, total_fare = price_curve(fare_class, adv_days)
                            add_row(origin, destination, carrier, flight_number,
                                    travel_date, departure_time, collection_dt,
                                    fare_class, base_fare, taxes, fees, total_fare,
                                    source)

print(f"Generated {len(rows)} 'normal' simulated rows before edge-case injection.")

# ---------------------------------------------------------------------------
# 2. DELIBERATE EDGE CASES (each logged with its intended category)
# ---------------------------------------------------------------------------
# These are injected on top of the normal data so every category discussed
# in Parts 12/13 of the methodology has at least one concrete, findable
# example with a known correct answer.

anchor_collection = COLLECTION_DAYS[0].replace(hour=10, minute=32)
anchor_travel = TRAVEL_DATES[2]  # 20-Sep-2026, the T15 anchor used throughout our discussion

# --- 2a. TECHNICAL DUPLICATE (same capture identity, ~1 min apart, identical price) ---
oid_a, _ = add_row("DEL", "BOM", "6E", "6E-2341", anchor_travel, "08:10",
                    anchor_collection, "Economy Saver", 4200, 1050, 150, 5400, "AirlineSite")
oid_b, _ = add_row("DEL", "BOM", "6E", "6E-2341", anchor_travel, "08:10",
                    anchor_collection + timedelta(minutes=1), "Economy Saver", 4200, 1050, 150, 5400, "AirlineSite")
edge_cases.append((oid_a, "BASELINE", "keep", "Anchor observation for duplicate/repricing test cluster"))
edge_cases.append((oid_b, "DUPLICATE", "collapse_into_" + oid_a,
                    "Same capture-identity as " + oid_a + ", 1 min apart, identical total_fare -> technical duplicate"))

# --- 2b. GENUINE REPRICING (same identity, later same day, DIFFERENT price -> NOT a duplicate) ---
oid_c, _ = add_row("DEL", "BOM", "6E", "6E-2341", anchor_travel, "08:10",
                    anchor_collection + timedelta(hours=8, minutes=15), "Economy Saver",
                    4600, 1050, 150, 5800, "AirlineSite")
edge_cases.append((oid_c, "GENUINE_REPRICE", "keep_as_new_observation",
                    "Same identity as " + oid_a + " but price changed (5400->5800) -> real repricing, not a duplicate"))

# --- 2c. SAME PRODUCT, DIFFERENT SOURCE (should NOT be a duplicate; feeds source consolidation) ---
oid_d, _ = add_row("DEL", "BOM", "6E", "6E-2341", anchor_travel, "08:10",
                    anchor_collection + timedelta(minutes=8), "Economy Saver",
                    4300, 1050, 200, 5550, "MMT")
oid_e, _ = add_row("DEL", "BOM", "6E", "6E-2341", anchor_travel, "08:10",
                    anchor_collection + timedelta(minutes=9), "Economy Saver",
                    4280, 1050, 180, 5510, "Goibibo")
edge_cases.append((oid_d, "DIFFERENT_SOURCE_SAME_PRODUCT", "keep_separate_then_consolidate",
                    "Same product as " + oid_a + ", different source (MMT) -> consolidate via median at aggregation, not a duplicate"))
edge_cases.append((oid_e, "DIFFERENT_SOURCE_SAME_PRODUCT", "keep_separate_then_consolidate",
                    "Same product as " + oid_a + ", different source (Goibibo)"))

# --- 2d. DIFFERENT FARE CLASS ON SAME FLIGHT (different product, not comparable to Saver) ---
oid_f, _ = add_row("DEL", "BOM", "6E", "6E-2341", anchor_travel, "08:10",
                    anchor_collection, "Economy Flexi", 5600, 1150, 150, 6900, "AirlineSite")
edge_cases.append((oid_f, "DIFFERENT_PRODUCT", "keep_as_separate_series",
                    "Same flight as " + oid_a + " but Economy Flexi -> different product, never pooled with Saver"))

# --- 2e. INVALID RECORD: negative base_fare ---
oid_g, _ = add_row("DEL", "BOM", "6E", "6E-2341", anchor_travel, "08:10",
                    anchor_collection, "Economy Saver", -500, 1050, 150, 700, "MMT")
edge_cases.append((oid_g, "INVALID_NEGATIVE_FARE", "exclude_flag_is_valid_false",
                    "base_fare is negative -> physically impossible, invalid record"))

# --- 2f. STATISTICAL OUTLIER / candidate market shock (no supporting context in this synthetic set) ---
oid_h, _ = add_row("DEL", "BOM", "6E", "6E-2341", anchor_travel, "08:10",
                    anchor_collection + timedelta(hours=13, minutes=27), "Economy Saver",
                    12000, 1900, 150, 14050, "AirlineSite")
edge_cases.append((oid_h, "STATISTICAL_OUTLIER", "hold_for_review",
                    "~2.5x the price of peer observations for the same product/day with no documented cause -> hold, do not auto-delete or auto-include"))

# --- 2g. MISSING BASE FARE / TAXES (only total disclosed) ---
oid_i, _ = add_row("BLR", "HYD", "SG", "SG-451", TRAVEL_DATES[2], "06:15",
                    COLLECTION_DAYS[0].replace(hour=20, minute=0),
                    "Economy Saver", None, None, None, 3600, "Goibibo")
edge_cases.append((oid_i, "MISSING_SUBFIELDS", "keep_use_total_only",
                    "base_fare/taxes/fees undisclosed by source, total_fare present -> keep, use total only"))

# --- 2h. SOLD OUT FLIGHT (no price, but real availability information) ---
oid_j, _ = add_row("BLR", "HYD", "SG", "SG-451", TRAVEL_DATES[2] + timedelta(days=1), "06:15",
                    COLLECTION_DAYS[0].replace(hour=9, minute=20),
                    "Economy Saver", None, None, None, None, "AirlineSite",
                    availability="Sold Out")
edge_cases.append((oid_j, "SOLD_OUT", "keep_flag_exclude_price_from_averaging",
                    "Flight sold out -> keep row (availability signal), exclude from price averaging"))

# --- 2i. MISSING SOURCE (excluded from index, retained for audit) ---
oid_k, _ = add_row("DEL", "BOM", "6E", "6E-2341", anchor_travel, "08:10",
                    anchor_collection + timedelta(minutes=18), "Economy Saver",
                    4200, 1050, 150, 5400, None)
edge_cases.append((oid_k, "MISSING_SOURCE", "exclude_from_index_retain_row",
                    "source field missing -> cannot apply source-consolidation logic, exclude from index but keep raw row"))

# --- 2j. REJECTED: missing route entirely ---
oid_l, _ = add_row(None, None, "AirlineSite-parse-error", "UNKNOWN", anchor_travel, "08:10",
                    anchor_collection, "Economy Saver", 4000, 1000, 150, 5150, "AirlineSite")
edge_cases.append((oid_l, "MISSING_ROUTE", "reject_outright",
                    "origin/destination missing -> not a usable observation at all, reject"))

# --- 2k. REJECTED: missing collection timestamp (represented with a placeholder marker) ---
oid_m, _ = add_row("DEL", "BOM", "6E", "6E-2341", anchor_travel, "08:10",
                    anchor_collection, "Economy Saver", 4200, 1050, 150, 5400, "AirlineSite")
rows[-1]["collection_timestamp"] = ""  # simulate missing timestamp after generation
edge_cases.append((oid_m, "MISSING_TIMESTAMP", "reject_outright",
                    "collection_timestamp missing -> cannot place in time or window, reject"))

# --- 2l. Multiple sources for a DIFFERENT flight on same route (for source-consolidation testing at route level) ---
oid_n, _ = add_row("DEL", "BOM", "QP", "QP-1123", anchor_travel, "07:30",
                    anchor_collection + timedelta(minutes=4), "Economy Saver",
                    4500, 1050, 150, 5700, "AirlineSite")
oid_o, _ = add_row("DEL", "BOM", "QP", "QP-1123", anchor_travel, "07:30",
                    anchor_collection + timedelta(minutes=12), "Economy Saver",
                    4500, 1050, 150, 5700, "Cleartrip")
edge_cases.append((oid_n, "DIFFERENT_FLIGHT_SAME_ROUTE_CLASS", "poolable_level_a",
                    "Different flight (QP-1123) than the 6E-2341 cluster, but same route+class+date+window -> Level A comparable, poolable at route aggregation"))
edge_cases.append((oid_o, "DIFFERENT_SOURCE_SAME_PRODUCT", "keep_separate_then_consolidate",
                    "Same product as " + oid_n + ", different source"))

# --- 2m. Fare class disappearance across collection rounds (Economy Saver missing on day 3 for one flight) ---
# We simulate this by NOT generating any Economy Saver row for 6E-2341 / anchor_travel
# on COLLECTION_DAYS[2] at all (handled naturally by the sampling above being random;
# we log it explicitly here as a case to check for in the output).
edge_cases.append(("N/A", "FARE_CLASS_AVAILABILITY_GAP", "no_row_expected_do_not_impute",
                    "By design, not every fare class is scraped/available every round; verify the pipeline treats any resulting gaps as genuinely missing, never imputed"))

print(f"Injected {len(edge_cases)} logged edge cases (some are baseline/reference rows).")
print(f"Total rows after injection: {len(rows)}")

# ---------------------------------------------------------------------------
# 3. WRITE OUTPUT FILES
# ---------------------------------------------------------------------------
# Always write to the canonical data/synthetic/ directory so the validator
# (which reads from data/synthetic/vayu_synthetic_observations.csv) is
# always working against the freshly generated file.

OUTPUT_DIR = os.path.join("data", "synthetic")
os.makedirs(OUTPUT_DIR, exist_ok=True)

OBS_PATH = os.path.join(OUTPUT_DIR, "vayu_synthetic_observations.csv")
EDGE_PATH = os.path.join(OUTPUT_DIR, "edge_case_log.csv")

with open(OBS_PATH, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

with open(EDGE_PATH, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["observation_id", "category", "expected_handling", "note"])
    for case in edge_cases:
        writer.writerow(case)

print("Wrote %s and %s" % (OBS_PATH, EDGE_PATH))
