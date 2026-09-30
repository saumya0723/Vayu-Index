#!/usr/bin/env python3
"""
VAYU INDEX - Phase 8 Verification
=================================

Independent acceptance checks run against the Phase 8 outputs ON DISK.
This script is read-only: it never rewrites an output.

It verifies the locked Phase 8 methodology end to end:

  * canonicalize REPRESENTATION, never economic content
  * every Phase 7 column carried through byte-identically (two-tier model)
  * Decimal monetary path, 2dp representation, no float, no value change
  * explicit price_state
  * round_sort_key with recorded provenance
  * explicit currency INR as a declared prototype constant, no FX
  * fare_class_tier_rank as derived metadata only
  * empty alias maps by approval
  * unknown values FLAGGED AND CARRIED, never silently rewritten
  * no imputation, no reconstruction of missing fare components
  * report grain (entity_id, field, action) is unique
  * idempotent and deterministic behaviour
  * Phase 1-7 artefacts byte-identical to the locked baseline

Usage:
    python scripts/verify_phase8.py
"""

from __future__ import annotations

import collections
import hashlib
import os
import re
import sys
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.consolidation import rules as consolidation_rules  # noqa: E402
from src.normalization import normalization_engine as E  # noqa: E402
from src.normalization import rules as R  # noqa: E402


VALIDATED_CSV = os.path.join("outputs", "validated_airfare_observations.csv")
DEDUPLICATED_CSV = os.path.join("outputs", "deduplicated_airfare_observations.csv")
CANONICAL_CSV = os.path.join("outputs", "canonical_airfare_observations.csv")
PHASE6_AUDIT_CSV = os.path.join("outputs", "phase6_duplicate_audit_report.csv")
BASKET_CSV = os.path.join(
    "data", "official", "dgca", "processed", "vayu_route_basket_2024_25.csv"
)
CONSOLIDATED_CSV = os.path.join("outputs", "consolidated_airfare_observations.csv")
FLIGHT_REPORT_CSV = os.path.join("outputs", "phase7_flight_cell_report.csv")
OBSERVATION_MAP_CSV = os.path.join("outputs", "phase7_observation_map.csv")

NORMALIZED_CSV = os.path.join("outputs", "normalized_airfare_observations.csv")
NORMALIZED_MAP_CSV = os.path.join("outputs", "normalized_observation_map.csv")
NORMALIZED_FLIGHT_CSV = os.path.join("outputs", "phase8_flight_cell_normalized.csv")
NORMALIZATION_REPORT_CSV = os.path.join("outputs", "phase8_normalization_report.csv")

PHASE8_SOURCES = (
    os.path.join("src", "normalization", "rules.py"),
    os.path.join("src", "normalization", "normalization_engine.py"),
    os.path.join("scripts", "run_normalization.py"),
)

EXPECTED_CELL_ROWS = 393
EXPECTED_FLIGHT_CELL_ROWS = 571
EXPECTED_OBSERVATION_ROWS = 778
EXPECTED_REPORT_ROWS = 777

PASSED = []
FAILED = []

LOCKED_SHA256 = {
    VALIDATED_CSV: "f1220617f380f645b8cb21dc4e8e93a069d17a5b8333835558df33e0b43cf45b",
    DEDUPLICATED_CSV: "6c51ea30d1728d959afdd91c1fea3fc6f2524c8b49875ecfea7791cf79a0a7d9",
    CANONICAL_CSV: "1223c7b15e7a2eec4798565f9d5013085e8cb3c64b82c17dca9f5375178c488c",
    PHASE6_AUDIT_CSV: "86afc9b8378ddd127d10002537669ae263da5f7dca86548aaca84a32f8d14030",
    BASKET_CSV: "dc57e6d470a2ed9061dd82a92c84943749c3c648cef00b85b3f250df2f87c181",
    CONSOLIDATED_CSV: "792be83e1a36165388e397dcf8b1ee27f82a665276c7b2a1cf167b80cc108e80",
    FLIGHT_REPORT_CSV: "fa7569ecd9463c15e41e4ba13db8e14e1198c34ccaf0b8366730115b7f67447f",
    OBSERVATION_MAP_CSV: "e4717e8f16d1b68ef8119e7708f1af7f6134ef2b3cf13c5185b74a04a93350c8",
}

LOCKED_SOURCE_SHA256 = {
    os.path.join("src", "validation", "rules.py"):
        "71c848d77f0df5aa6efd7bafb6f11af630359e4877b7dcea41920325fdacc12d",
    os.path.join("src", "validation", "validator.py"):
        "f5a0eba23437fb1753589cdd53f1e2336c1b2e9a1781f469b20bcbf89fd04a5b",
    os.path.join("src", "deduplication", "rules.py"):
        "98b9d027b48e9f4487905b8d0224d77d4014b9bb780a9ad4ec5915378220695a",
    os.path.join("src", "deduplication", "dedup_engine.py"):
        "e3d80ad76bbd76fa5f8a47f922146386fb4677adce826b5080ff1265b2f0431a",
    os.path.join("src", "deduplication", "__init__.py"):
        "da370da9aaafda07ab9f5321314f499bfe1f55530fedfc2a935051b727d69171",
    os.path.join("src", "consolidation", "rules.py"):
        "6ce73b315a18b9c371e3a5896d980f9ba19a0dd6455eba33cb384b3fc687e0a2",
    os.path.join("src", "consolidation", "consolidation_engine.py"):
        "14b9b8460214120d71f660baf1200b5c2dc120b585a3a951c7a42ec58174731a",
    os.path.join("src", "consolidation", "__init__.py"):
        "82028b82dce631d2d180070dc58f011d2c6f289a392294ff771089b05c532420",
    os.path.join("scripts", "run_deduplication.py"):
        "630e51e8c8755ac14d756fcc8fb717c292b5220b41f6b3709092ebf6b5aac6e5",
    os.path.join("scripts", "run_consolidation.py"):
        "ada1abb8a8e5e67d68b477154861f3b11cc611e6f79c4f8ed8737529782ef85c",
    os.path.join("scripts", "build_vayu_route_basket.py"):
        "015f7368550bfc4ecbd5aa5fbc79629cc56da18c5398fd0d1b892b4b5c838ece",
    os.path.join("scripts", "process_dgca_city_pair.py"):
        "333ed6d2b8d05d00f00507048a369e6a4af7e65db3ec201b92ce72608256fb79",
    os.path.join("tests", "test_deduplication.py"):
        "c9836526104327ffefd8537ce432a06fc6ab9cc379f573cd2b33f2384850046d",
    os.path.join("tests", "test_consolidation.py"):
        "c0c57404fa52e7497791549a421de7c3f1f95f4d74f13f63532f7219e3775026",
}


def check(label, condition, detail=""):
    if condition:
        PASSED.append(label)
        print("  PASS  %s%s" % (label, ("  - " + detail) if detail else ""))
    else:
        FAILED.append(label)
        print("  FAIL  %s%s" % (label, ("  - " + detail) if detail else ""))


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def as_money(value):
    text = (value or "").strip()
    if text == "":
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError, ArithmeticError):
        return None

def main():
    print("=" * 70)
    print("VAYU INDEX - Phase 8 Verification")
    print("=" * 70)

    print("\n[1] Locked Phase 1-7 artefacts are byte-identical")
    for path, expected in sorted(LOCKED_SHA256.items()):
        actual = sha256(path) if os.path.exists(path) else "MISSING"
        check("locked output unchanged: %s" % path, actual == expected, actual[:16])
    for path, expected in sorted(LOCKED_SOURCE_SHA256.items()):
        actual = sha256(path) if os.path.exists(path) else "MISSING"
        check("locked source unchanged: %s" % path, actual == expected, actual[:16])

    print("\n[2] Phase 8 outputs exist with the expected shape")
    for path in (
        NORMALIZED_CSV,
        NORMALIZED_MAP_CSV,
        NORMALIZED_FLIGHT_CSV,
        NORMALIZATION_REPORT_CSV,
    ):
        check("output exists: %s" % path, os.path.exists(path))

    cells = E.read_phase7_csv(NORMALIZED_CSV)
    flights = E.read_phase7_csv(NORMALIZED_FLIGHT_CSV)
    observations = E.read_phase7_csv(NORMALIZED_MAP_CSV)
    report = E.read_phase7_csv(NORMALIZATION_REPORT_CSV)

    phase7_cells = E.read_phase7_csv(CONSOLIDATED_CSV)
    phase7_flights = E.read_phase7_csv(FLIGHT_REPORT_CSV)
    phase7_observations = E.read_phase7_csv(OBSERVATION_MAP_CSV)
    canonical = E.read_phase7_csv(CANONICAL_CSV)

    check(
        "normalized cells row count is %d" % EXPECTED_CELL_ROWS,
        len(cells) == EXPECTED_CELL_ROWS,
        str(len(cells)),
    )
    check(
        "normalized flight cells row count is %d" % EXPECTED_FLIGHT_CELL_ROWS,
        len(flights) == EXPECTED_FLIGHT_CELL_ROWS,
        str(len(flights)),
    )
    check(
        "normalized observations row count is %d" % EXPECTED_OBSERVATION_ROWS,
        len(observations) == EXPECTED_OBSERVATION_ROWS,
        str(len(observations)),
    )
    check(
        "normalization report row count is %d" % EXPECTED_REPORT_ROWS,
        len(report) == EXPECTED_REPORT_ROWS,
        str(len(report)),
    )

    print("\n[3] Output schemas match the declared column contracts")
    check(
        "cell columns match NORMALIZED_CELL_COLUMNS",
        list(cells.columns) == list(E.NORMALIZED_CELL_COLUMNS),
        "%d columns" % len(cells.columns),
    )
    check(
        "flight cell columns match NORMALIZED_FLIGHT_CELL_COLUMNS",
        list(flights.columns) == list(E.NORMALIZED_FLIGHT_CELL_COLUMNS),
        "%d columns" % len(flights.columns),
    )
    check(
        "observation columns match NORMALIZED_OBSERVATION_COLUMNS",
        list(observations.columns) == list(E.NORMALIZED_OBSERVATION_COLUMNS),
        "%d columns" % len(observations.columns),
    )
    check(
        "report columns match NORMALIZATION_REPORT_COLUMNS",
        list(report.columns) == list(E.NORMALIZATION_REPORT_COLUMNS),
        "%d columns" % len(report.columns),
    )
    check(
        "every Phase 7 consolidated column is preserved in order",
        list(cells.columns)[: len(E.PHASE7_CONSOLIDATED_COLUMNS)]
        == list(E.PHASE7_CONSOLIDATED_COLUMNS),
    )
    check(
        "every Phase 7 flight cell column is preserved in order",
        list(flights.columns)[: len(E.PHASE7_FLIGHT_CELL_COLUMNS)]
        == list(E.PHASE7_FLIGHT_CELL_COLUMNS),
    )
    check(
        "every Phase 7 observation column is preserved in order",
        list(observations.columns)[: len(E.PHASE7_OBSERVATION_MAP_COLUMNS)]
        == list(E.PHASE7_OBSERVATION_MAP_COLUMNS),
    )

    print("\n[4] Row-count and identity invariants versus Phase 7")
    check(
        "cell count unchanged from Phase 7",
        len(cells) == len(phase7_cells),
        "%d -> %d" % (len(phase7_cells), len(cells)),
    )
    check(
        "flight cell count unchanged from Phase 7",
        len(flights) == len(phase7_flights),
        "%d -> %d" % (len(phase7_flights), len(flights)),
    )
    check(
        "observation count unchanged from Phase 7",
        len(observations) == len(phase7_observations),
        "%d -> %d" % (len(phase7_observations), len(observations)),
    )
    check(
        "consolidation_cell_id set is identical to Phase 7",
        set(cells["consolidation_cell_id"]) == set(phase7_cells["consolidation_cell_id"]),
    )
    check(
        "flight_cell_id set is identical to Phase 7",
        set(flights["flight_cell_id"]) == set(phase7_flights["flight_cell_id"]),
    )
    check(
        "observation_id set is identical to Phase 7",
        set(observations["observation_id"]) == set(phase7_observations["observation_id"]),
    )
    check(
        "no row was added, merged or deleted",
        len(cells) == len(phase7_cells)
        and len(flights) == len(phase7_flights)
        and len(observations) == len(phase7_observations),
    )
    print("\n[5] Every Phase 7 column is carried through unchanged")

    def _aligned(new_df, old_df, key):
        left = new_df.sort_values(key).reset_index(drop=True)
        right = old_df.sort_values(key).reset_index(drop=True)
        return left, right

    def _carry_through(new_df, old_df, key, columns, label):
        left, right = _aligned(new_df, old_df, key)
        mismatched = [
            name
            for name in columns
            if list(left[name]) != list(right[name])
        ]
        check(
            "%s: all %d Phase 7 columns identical" % (label, len(columns)),
            not mismatched,
            "mismatched: %s" % ", ".join(mismatched[:5]) if mismatched else "",
        )

    _carry_through(
        cells,
        phase7_cells,
        "consolidation_cell_id",
        E.PHASE7_CONSOLIDATED_COLUMNS,
        "consolidated cells",
    )
    _carry_through(
        flights,
        phase7_flights,
        "flight_cell_id",
        E.PHASE7_FLIGHT_CELL_COLUMNS,
        "flight cells",
    )
    _carry_through(
        observations,
        phase7_observations,
        "observation_id",
        E.PHASE7_OBSERVATION_MAP_COLUMNS,
        "observations",
    )

    print("\n[6] Monetary normalization changed representation, never value")
    cell_pairs = [
        (row["consolidated_fare"], row["consolidated_fare_normalized"])
        for _, row in cells.iterrows()
    ]
    value_changes = [
        (raw, norm)
        for raw, norm in cell_pairs
        if as_money(raw) is not None
        and as_money(norm) is not None
        and as_money(raw) != as_money(norm)
    ]
    check(
        "consolidated_fare value never changed",
        not value_changes,
        "%d change(s)" % len(value_changes),
    )
    quantized = [
        norm
        for raw, norm in cell_pairs
        if as_money(norm) is not None
    ]
    check(
        "every normalized cell fare carries exactly 2 decimal places",
        all("." in value and len(value.split(".")[1]) == 2 for value in quantized),
    )
    obs_pairs = [
        (row["total_fare"], row["total_fare_normalized"])
        for _, row in observations.iterrows()
    ]
    obs_changes = [
        (raw, norm)
        for raw, norm in obs_pairs
        if as_money(raw) is not None
        and as_money(norm) is not None
        and as_money(raw) != as_money(norm)
    ]
    check(
        "total_fare value never changed",
        not obs_changes,
        "%d change(s)" % len(obs_changes),
    )
    check(
        "money quantum is a Decimal of 0.01",
        isinstance(R.MONEY_QUANTUM, Decimal) and R.MONEY_QUANTUM == Decimal("0.01"),
    )

    print("\n[7] price_state is explicit and correct")
    cell_states = collections.Counter(cells["price_state"])
    check(
        "every cell price_state is a declared state",
        set(cell_states) <= set(R.PRICE_STATES),
        str(dict(cell_states)),
    )
    check(
        "cell price_state distribution is PRICED 392 / NO_PRICE_CELL 1",
        cell_states.get(R.PRICE_STATE_PRICED) == 392
        and cell_states.get(R.PRICE_STATE_NO_PRICE_CELL) == 1,
        str(dict(cell_states)),
    )
    recomputed = [
        R.derive_cell_price_state(row["consolidation_status"], row["consolidated_fare"])
        for _, row in cells.iterrows()
    ]
    check(
        "cell price_state is reproducible from the rule function",
        recomputed == list(cells["price_state"]),
    )
    check(
        "a NO_PRICE_CELL row never carries a normalized fare",
        all(
            row["consolidated_fare_normalized"] == ""
            for _, row in cells.iterrows()
            if row["price_state"] == R.PRICE_STATE_NO_PRICE_CELL
        ),
    )
    obs_states = collections.Counter(observations["price_state"])
    check(
        "every observation price_state is a declared state",
        set(obs_states) <= set(R.PRICE_STATES),
        str(dict(obs_states)),
    )

    print("\n[8] round_sort_key is derived, provenance-tagged and monotonic")
    check(
        "round_sort_key column is present on cells",
        "round_sort_key" in cells.columns,
    )
    rebuilt = [
        R.derive_round_sort_key(
            row["round_anchor_timestamp"], row["collection_round_id"]
        )
        for _, row in cells.iterrows()
    ]
    check(
        "round_sort_key is reproducible from the rule function",
        [item[0] for item in rebuilt] == list(cells["round_sort_key"]),
    )
    check(
        "round_sort_key_source is reproducible from the rule function",
        [item[1] for item in rebuilt] == list(cells["round_sort_key_source"]),
    )
    provenance = collections.Counter(cells["round_sort_key_source"])
    check(
        "every round_sort_key_source is a declared provenance value",
        set(provenance)
        <= {
            R.ROUND_SORT_KEY_SOURCE_ANCHOR,
            R.ROUND_SORT_KEY_SOURCE_ROUND_ID,
            R.ROUND_SORT_KEY_SOURCE_UNRESOLVED,
        },
        str(dict(provenance)),
    )
    check(
        "every anchored cell resolves a non-blank round_sort_key",
        all(
            row["round_sort_key"] != ""
            for _, row in cells.iterrows()
            if R.is_anchored(row["round_alignment"])
        ),
    )

    print("\n[9] Two-tier canonicalisation: verify-and-flag, never rewrite in place")
    for name in (
        "origin_canonical",
        "destination_canonical",
        "travel_date_canonical",
        "fare_class_canonical",
        "fare_class_is_known",
        "advance_purchase_window_is_known",
    ):
        check("cell carries %s" % name, name in cells.columns)
    check(
        "origin_canonical is reproducible from the rule function",
        [R.canonicalize_airport(row["origin"])[0] for _, row in cells.iterrows()]
        == list(cells["origin_canonical"]),
    )
    check(
        "destination_canonical is reproducible from the rule function",
        [R.canonicalize_airport(row["destination"])[0] for _, row in cells.iterrows()]
        == list(cells["destination_canonical"]),
    )
    check(
        "fare_class_canonical is reproducible from the rule function",
        [
            R.canonicalize_categorical(row["fare_class"], R.KNOWN_FARE_CLASSES)[0]
            for _, row in cells.iterrows()
        ]
        == list(cells["fare_class_canonical"]),
    )
    left_cells, right_cells = _aligned(cells, phase7_cells, "consolidation_cell_id")
    identity_rewrites = [
        name
        for name in consolidation_rules.CONSOLIDATION_CELL_FIELDS
        if list(left_cells[name]) != list(right_cells[name])
    ]
    check(
        "no cell identity field was rewritten in place",
        not identity_rewrites,
        ", ".join(identity_rewrites) if identity_rewrites else "",
    )
    unknown_fare_class = [
        row for _, row in cells.iterrows() if row["fare_class_is_known"] != "True"
    ]
    check(
        "every fare class in the real corpus is known",
        not unknown_fare_class,
        "%d unknown" % len(unknown_fare_class),
    )
    unknown_apw = [
        row
        for _, row in cells.iterrows()
        if row["advance_purchase_window_is_known"] != "True"
    ]
    check(
        "every advance purchase window in the real corpus is known",
        not unknown_apw,
        "%d unknown" % len(unknown_apw),
    )

    print("\n[10] Currency is an explicit declared prototype constant")
    check("currency constant is INR", R.CURRENCY_CODE == "INR")
    check(
        "currency source is DECLARED_PROTOTYPE_CONSTANT",
        R.CURRENCY_SOURCE == "DECLARED_PROTOTYPE_CONSTANT",
    )
    check("FX conversion is not supported", R.FX_CONVERSION_SUPPORTED is False)
    check(
        "every cell declares currency INR",
        set(cells["currency"]) == {"INR"},
    )
    check(
        "every observation declares currency INR",
        set(observations["currency"]) == {"INR"},
    )
    check(
        "every cell declares the currency source",
        set(cells["currency_source"]) == {R.CURRENCY_SOURCE},
    )

    print("\n[11] fare_class_tier_rank is derived metadata only")
    check(
        "tier rank is not an identity field",
        R.FARE_CLASS_TIER_RANK_IS_IDENTITY_FIELD is False,
    )
    check(
        "tier rank mapping is Saver 1 / Standard 2 / Flexi 3",
        R.fare_class_tier_rank("Economy Saver") == "1"
        and R.fare_class_tier_rank("Economy Standard") == "2"
        and R.fare_class_tier_rank("Economy Flexi") == "3",
    )
    check(
        "tier rank is blank for an unknown fare class",
        R.fare_class_tier_rank("Premium Economy") == "",
    )
    check(
        "tier rank is absent from the Phase 7 economic identity",
        "fare_class_tier_rank" not in consolidation_rules.ECONOMIC_IDENTITY_FIELDS,
    )
    check(
        "tier rank is absent from the Phase 7 consolidation cell key",
        "fare_class_tier_rank" not in consolidation_rules.CONSOLIDATION_CELL_FIELDS,
    )
    check(
        "tier rank never appears inside a consolidation_cell_id",
        not any(
            "fare_class_tier_rank" in value for value in cells["consolidation_cell_id"]
        ),
    )

    print("\n[12] Alias maps are empty by approval")
    check("alias maps are declared empty", R.ALIAS_MAPS_EMPTY_BY_APPROVAL is True)
    check("fare class alias map is empty", R.FARE_CLASS_ALIASES == {})
    check("source alias map is empty", R.SOURCE_ALIASES == {})
    check("carrier alias map is empty", R.CARRIER_ALIASES == {})
    check(
        "no ALIAS_APPLIED action was ever emitted",
        R.ACTION_ALIAS_APPLIED not in set(report["action"]),
    )

    print("\n[13] No imputation and no reconstruction of missing components")
    lookup = E.build_canonical_lookup(canonical)
    blank_base_before = sum(
        1 for value in lookup.values() if str(value.get("base_fare", "")).strip() == ""
    )
    blank_base_after = sum(
        1 for value in observations["base_fare"] if str(value).strip() == ""
    )
    check(
        "blank base_fare count is unchanged (no imputation)",
        blank_base_before == blank_base_after,
        "%d -> %d" % (blank_base_before, blank_base_after),
    )
    check(
        "a missing fare component is never reconstructed",
        all(
            row["fare_decomposition_complete"] == "False"
            for _, row in observations.iterrows()
            if str(row["base_fare"]).strip() == ""
        ),
    )
    check(
        "no cell fare was invented for the no-price cell",
        all(
            row["consolidated_fare_normalized"] == ""
            for _, row in cells.iterrows()
            if str(row["consolidated_fare"]).strip() == ""
        ),
    )

    print("\n[14] Normalization report grain and content")
    grain = [
        (row["entity_id"], row["field"], row["action"]) for _, row in report.iterrows()
    ]
    check(
        "report grain (entity_id, field, action) is unique",
        len(set(grain)) == len(grain),
        "%d rows / %d distinct" % (len(grain), len(set(grain))),
    )
    sort_grain = [
        (row["entity_type"], row["entity_id"], row["field"], row["action"])
        for _, row in report.iterrows()
    ]
    check(
        "report is deterministically sorted",
        sort_grain == sorted(sort_grain),
    )
    actions = collections.Counter(report["action"])
    check(
        "every report row is a MONEY_QUANTIZED representation change",
        set(actions) == {R.ACTION_MONEY_QUANTIZED},
        str(dict(actions)),
    )
    check(
        "every report row targets an observation total_fare",
        set(report["entity_type"]) == {E.ENTITY_OBSERVATION}
        and set(report["field"]) == {"total_fare"},
    )
    economic_drift = [
        (row["original_value"], row["normalized_value"])
        for _, row in report.iterrows()
        if as_money(row["original_value"]) is None
        or as_money(row["normalized_value"]) is None
        or as_money(row["original_value"]) != as_money(row["normalized_value"])
    ]
    check(
        "zero economic-value changes across the whole report",
        not economic_drift,
        "%d drift row(s)" % len(economic_drift),
    )

    print("\n[15] Normalization flags")
    cell_flags = collections.Counter()
    for value in cells["normalization_flags"]:
        for flag in str(value).split("|"):
            if flag:
                cell_flags[flag] += 1
    check(
        "cell flags are exactly MISSING_PRICE x1",
        dict(cell_flags) == {R.FLAG_MISSING_PRICE: 1},
        str(dict(cell_flags)),
    )
    obs_flags = collections.Counter()
    for value in observations["normalization_flags"]:
        for flag in str(value).split("|"):
            if flag:
                obs_flags[flag] += 1
    check(
        "observation flags are exactly FARE_DECOMPOSITION_INCOMPLETE x2",
        dict(obs_flags) == {R.FLAG_FARE_DECOMPOSITION_INCOMPLETE: 2},
        str(dict(obs_flags)),
    )
    flight_flags = collections.Counter()
    for value in flights["normalization_flags"]:
        for flag in str(value).split("|"):
            if flag:
                flight_flags[flag] += 1
    check(
        "flight cells carry no flags",
        not flight_flags,
        str(dict(flight_flags)),
    )

    print("\n[16] Determinism and idempotence")
    rerun = E.run_normalization(
        phase7_cells, phase7_flights, phase7_observations, canonical
    )
    check(
        "rerun reproduces the normalized cell file",
        rerun.normalized.to_csv(index=False).replace("\r\n", "\n")
        == read_text(NORMALIZED_CSV).replace("\r\n", "\n"),
    )
    check(
        "rerun reproduces the flight cell file",
        rerun.flight_cells.to_csv(index=False).replace("\r\n", "\n")
        == read_text(NORMALIZED_FLIGHT_CSV).replace("\r\n", "\n"),
    )
    check(
        "rerun reproduces the observation map",
        rerun.observation_map.to_csv(index=False).replace("\r\n", "\n")
        == read_text(NORMALIZED_MAP_CSV).replace("\r\n", "\n"),
    )
    check(
        "rerun reproduces the normalization report",
        rerun.report.to_csv(index=False).replace("\r\n", "\n")
        == read_text(NORMALIZATION_REPORT_CSV).replace("\r\n", "\n"),
    )
    shuffled = E.run_normalization(
        phase7_cells.sample(frac=1, random_state=20260910).reset_index(drop=True),
        phase7_flights.sample(frac=1, random_state=20260910).reset_index(drop=True),
        phase7_observations.sample(frac=1, random_state=20260910).reset_index(drop=True),
        canonical,
    )
    check(
        "shuffled input produces an identical cell output",
        shuffled.normalized.to_csv(index=False) == rerun.normalized.to_csv(index=False),
    )
    check(
        "shuffled input produces an identical report",
        shuffled.report.to_csv(index=False) == rerun.report.to_csv(index=False),
    )
    cell_rows = [dict(row) for _, row in cells.iterrows()]
    flight_rows = [dict(row) for _, row in flights.iterrows()]
    check(
        "cells follow the declared chronological sort contract",
        [item["consolidation_cell_id"] for item in cell_rows]
        == [
            item["consolidation_cell_id"]
            for item in sorted(
                cell_rows,
                key=lambda entry: E._sort_key(entry, "consolidation_cell_id"),
            )
        ],
    )
    check(
        "flight cells follow the declared chronological sort contract",
        [item["flight_cell_id"] for item in flight_rows]
        == [
            item["flight_cell_id"]
            for item in sorted(
                flight_rows, key=lambda entry: E._sort_key(entry, "flight_cell_id")
            )
        ],
    )
    check(
        "observations are sorted by observation_id",
        list(observations["observation_id"]) == sorted(observations["observation_id"]),
    )
    check(
        "inputs were not mutated by the engine",
        sha256(CONSOLIDATED_CSV) == LOCKED_SHA256[CONSOLIDATED_CSV]
        and sha256(OBSERVATION_MAP_CSV) == LOCKED_SHA256[OBSERVATION_MAP_CSV],
    )

    print("\n[17] Scope boundaries are respected")
    banned = [
        "float(",
        "TIME_TOLERANCE" + "_MINUTES",
        "ROUND_TOLERANCE" + "_MINUTES",
        "sklearn",
        "Isolation" + "Forest",
        "import random",
        "numpy.random",
        "index_" + "value",
        "route_" + "aggregate",
        "basket_" + "weight",
        "source_" + "weight",
    ]
    for path in PHASE8_SOURCES:
        text = read_text(path)
        hits = [token for token in banned if token in text]
        check(
            "no out-of-scope construct in %s" % path,
            not hits,
            "found: %s" % ", ".join(hits) if hits else "",
        )
        matches = re.findall(r"\b" + "row" + r"\.[A-Za-z_]", text)
        check(
            "no attribute-style row access in %s" % path,
            not matches,
            "%d hit(s)" % len(matches) if matches else "",
        )

    forbidden_columns = [
        "anomaly",
        "severity",
        "index_eligible",
        "basket_member",
        "weight",
        "route_index",
    ]
    for frame_name, frame in (
        ("cells", cells),
        ("flight cells", flights),
        ("observations", observations),
    ):
        offenders = [
            name
            for name in frame.columns
            for token in forbidden_columns
            if token in name.lower()
        ]
        check(
            "%s carry no Phase 9 or Phase 10 columns" % frame_name,
            not offenders,
            ", ".join(offenders) if offenders else "",
        )

    check(
        "timezone inference was never performed",
        R.TIMEZONE_INFERENCE_PERFORMED is False
        and R.COLLECTION_TIMESTAMP_IS_NAIVE_LOCAL is True,
    )
    check(
        "no route direction was reversed",
        all(
            row["origin"] == row["origin_canonical"]
            and row["destination"] == row["destination_canonical"]
            for _, row in cells.iterrows()
        ),
    )

    print("\n[18] Lineage and schema versioning")
    check(
        "every cell records the Phase 8 schema version",
        set(cells["phase8_schema_version"]) == {R.PHASE8_SCHEMA_VERSION},
    )
    check(
        "every flight cell records the Phase 8 schema version",
        set(flights["phase8_schema_version"]) == {R.PHASE8_SCHEMA_VERSION},
    )
    check(
        "every observation records the Phase 8 schema version",
        set(observations["phase8_schema_version"]) == {R.PHASE8_SCHEMA_VERSION},
    )
    check(
        "every observation retains its Phase 7 flight cell lineage",
        all(str(value).strip() != "" for value in observations["flight_cell_id"]),
    )
    check(
        "every flight cell retains its consolidation cell lineage",
        set(flights["consolidation_cell_id"]) <= set(cells["consolidation_cell_id"]),
    )

    _summary(cells, flights, observations, report)


def _summary(cells=None, flights=None, observations=None, report=None):
    print("\n" + "=" * 70)
    if cells is not None:
        print("Normalized cells      : %d" % len(cells))
        print("Normalized flight cells: %d" % len(flights))
        print("Normalized observations: %d" % len(observations))
        print("Normalization report   : %d" % len(report))
        print("price_state            : %s"
              % dict(sorted(collections.Counter(cells["price_state"]).items())))
        print("round_sort_key_source  : %s"
              % dict(sorted(collections.Counter(cells["round_sort_key_source"]).items())))
        print("Currency               : %s (%s)" % (R.CURRENCY_CODE, R.CURRENCY_SOURCE))
        print("-" * 70)
    print("PASSED: %d   FAILED: %d" % (len(PASSED), len(FAILED)))
    if FAILED:
        print("\nFailed checks:")
        for label in FAILED:
            print("  - %s" % label)
    print("=" * 70)
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
