"""
VAYU INDEX — Phase 6: Deduplication Engine
=============================================

Pipeline implemented here:

    VALIDATED CSV (Phase 2 output, 783 rows, is_valid flag present)
        -> DEDUPLICATION ENGINE
        -> FULL AUDITED OUTPUT (783 rows, all Phase 2 columns preserved,
           plus Phase 6 audit columns appended)
        -> derived CANONICAL VIEW (is_duplicate == False AND is_valid == True)

This module never modifies or drops raw fields, and never drops the 4
Phase 2 INVALID rows either — they pass straight through with their
Phase 2 verdict columns intact and a single Phase 6 reason code
(SKIPPED_INVALID_BY_PHASE2). Duplicate grouping runs ONLY among rows
where is_valid == True.

Determinism / order-independence: the entire algorithm is a pure function
of the input rows' field values (grouping by identity, then sorting each
group deterministically to pick the canonical record). Nothing depends on
the order rows appear in the input DataFrame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from . import rules as R


# Parsed as a NAIVE LOCAL datetime, exactly as represented in the Phase 2
# input. Phase 6 never infers, assigns, converts, or fabricates a timezone.
# See rules.COLLECTION_TIMESTAMP_IS_NAIVE_LOCAL for the approved rationale
# and its explicitly stated consequence.
COLLECTION_TS_FORMAT = R.COLLECTION_TIMESTAMP_FORMAT


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _parse_ts(value: Any) -> Optional[datetime]:
    if _is_missing(value):
        return None
    try:
        return datetime.strptime(str(value).strip(), COLLECTION_TS_FORMAT)
    except ValueError:
        return None


def _clean_str(value: Any) -> Optional[str]:
    if _is_missing(value):
        return None
    return str(value).strip()


# ---------------------------------------------------------------------------
# Identity key construction
# ---------------------------------------------------------------------------

@dataclass
class RowIdentity:
    """Everything needed to decide grouping for one row."""
    observation_id: str
    economic_key: Optional[Tuple] = None
    product_instance_key: Optional[Tuple] = None
    source: Optional[str] = None
    total_fare: Optional[str] = None  # canonical string form; see rules.normalize_total_fare
    availability_status: Optional[str] = None
    collection_ts: Optional[datetime] = None
    collection_ts_present_but_unparseable: bool = False
    missing_identity_fields: List[str] = field(default_factory=list)


def build_row_identity(row: Dict[str, Any]) -> RowIdentity:
    """
    Build the identity fields for one VALID row.

    Any missing economic/product-instance identity field is recorded in
    `missing_identity_fields`; the caller is responsible for excluding
    such rows from grouping (per the approved "missing identity" rule)
    rather than this function silently guessing a value.
    """
    observation_id = _clean_str(row.get("observation_id")) or ""

    econ_values = []
    missing = []
    for field_name in R.ECONOMIC_IDENTITY_FIELDS:
        v = _clean_str(row.get(field_name))
        if v is None:
            missing.append(field_name)
        econ_values.append(v)

    carrier = _clean_str(row.get("carrier"))
    flight_number = _clean_str(row.get("flight_number"))
    dep_time_norm = R.normalize_departure_time(row.get("departure_time"))

    if carrier is None:
        missing.append("carrier")
    if flight_number is None:
        missing.append("flight_number")
    if dep_time_norm is None:
        missing.append("departure_time")

    economic_key = tuple(econ_values) if not missing_overlaps(missing, R.ECONOMIC_IDENTITY_FIELDS) else None
    product_instance_key = (
        tuple(econ_values) + (carrier, flight_number, dep_time_norm)
        if not missing
        else None
    )

    source = _clean_str(row.get("source"))
    if source is None:
        missing.append("source")

    total_fare_raw = row.get("total_fare")
    total_fare = None
    if not _is_missing(total_fare_raw):
        # APPROVED: compare fares through a canonical STRING form so the
        # input's integer formatting is preserved ("5400", never "5400.0")
        # wherever the value is surfaced in an audit field, while 5400,
        # "5400" and "5400.00" still compare equal.
        total_fare = R.normalize_total_fare(total_fare_raw)

    availability_status = _clean_str(row.get("availability_status"))

    ts_raw = row.get("collection_timestamp")
    ts_present_but_bad = False
    collection_ts = None
    if not _is_missing(ts_raw):
        collection_ts = _parse_ts(ts_raw)
        if collection_ts is None:
            ts_present_but_bad = True
    # Note: a fully MISSING collection_timestamp is not added to
    # `missing` here for economic/product-instance purposes (timestamp is
    # not part of either identity key) — it is handled separately as a
    # grouping-eligibility concern in group_and_mark(), consistent with
    # the approved rule that a missing timestamp must never be assumed
    # "within tolerance."

    return RowIdentity(
        observation_id=observation_id,
        economic_key=economic_key,
        product_instance_key=product_instance_key,
        source=source,
        total_fare=total_fare,
        availability_status=availability_status,
        collection_ts=collection_ts,
        collection_ts_present_but_unparseable=ts_present_but_bad,
        missing_identity_fields=missing,
    )


def missing_overlaps(missing: List[str], field_set: Tuple[str, ...]) -> bool:
    return any(f in field_set for f in missing)


# ---------------------------------------------------------------------------
# Duplicate grouping
# ---------------------------------------------------------------------------

@dataclass
class DedupResult:
    duplicate_group_id: str
    is_duplicate: bool
    duplicate_of: Optional[str]
    duplicate_reason: str
    retained: bool
    # AUDIT-ONLY. Whether every member of a CONFIRMED duplicate group carries
    # the same capture_signature. This is never one of the five conditions
    # that decide duplicate status — it is recorded so a reviewer can see
    # where the pre-existing signature agrees or disagrees with the decision
    # the locked rule reached. None where there is no confirmed group, or
    # where any member's capture_signature is missing.
    capture_signature_agreement: Optional[bool] = None


def _grouping_bucket_key(identity: RowIdentity) -> Optional[Tuple]:
    """
    The key used to bucket rows into duplicate-CANDIDATE groups before
    the pairwise time-tolerance + price checks decide actual duplicate
    status within the bucket.

    Bucket = product_instance_key + source + (price OR sold-out marker).
    Rows with any missing identity field, or an unparseable/missing
    timestamp, are never placed in a bucket — they are handled
    individually (see group_and_mark()).
    """
    if identity.product_instance_key is None:
        return None
    if identity.source is None:
        return None

    if identity.availability_status == R.SOLD_OUT_STATUS:
        price_component = ("SOLD_OUT",)
    elif identity.total_fare is not None:
        price_component = ("PRICE", identity.total_fare)
    else:
        # Priced-expected row with no usable price and not sold-out —
        # cannot be safely bucketed; treated as its own singleton below.
        return None

    return identity.product_instance_key + (identity.source,) + price_component


def _canonical_sort_key(row: Dict[str, Any], identity: RowIdentity) -> Tuple:
    """
    Deterministic total order for picking the canonical record within a
    duplicate group: earliest valid collection_timestamp first, then
    lowest observation_id lexicographically. Rows without a parseable
    timestamp sort last (they should not normally appear in a bucket at
    all, since a bucket requires timestamp comparison to have happened,
    but this keeps the ordering total and safe regardless).
    """
    ts = identity.collection_ts
    ts_sort = (0, ts) if ts is not None else (1, datetime.max)
    return (ts_sort[0], ts_sort[1], identity.observation_id)


def group_and_mark(valid_rows: List[Dict[str, Any]]) -> Dict[str, DedupResult]:
    """
    Core deterministic, order-independent grouping algorithm.

    Input: list of row dicts (already confirmed is_valid == True by the
    caller). Order of this list must NOT affect the result — verified by
    sorting every bucket internally before any decision is made.

    Returns: dict of observation_id -> DedupResult, one entry per input row.
    """
    identities: Dict[str, RowIdentity] = {}
    rows_by_id: Dict[str, Dict[str, Any]] = {}
    for row in valid_rows:
        ident = build_row_identity(row)
        identities[ident.observation_id] = ident
        rows_by_id[ident.observation_id] = row

    # Bucket candidate rows by (product_instance + source + price-or-soldout).
    # Rows with a missing/unparseable collection_timestamp are deliberately
    # NOT placed into the normal clustering buckets — time-tolerance
    # clustering is meaningless without a timestamp, and letting such a row
    # enter the normal flow would incorrectly resolve it as an ordinary
    # singleton (RETAINED_UNIQUE) instead of routing it through the
    # dedicated ambiguous-timestamp path below.
    buckets: Dict[Tuple, List[str]] = {}
    unbucketed: List[str] = []
    missing_timestamp_rows: List[str] = []

    for obs_id, ident in identities.items():
        if ident.missing_identity_fields:
            unbucketed.append(obs_id)
            continue
        bucket_key = _grouping_bucket_key(ident)
        if bucket_key is None:
            unbucketed.append(obs_id)
            continue
        if ident.collection_ts is None:
            missing_timestamp_rows.append(obs_id)
            continue
        buckets.setdefault(bucket_key, []).append(obs_id)

    results: Dict[str, DedupResult] = {}

    # --- Rows excluded from grouping entirely (missing identity fields, or
    #     a priced-expected row with no usable price and not sold-out) -----
    for obs_id in unbucketed:
        ident = identities[obs_id]
        if ident.missing_identity_fields:
            reason = R.REASON_EXCLUDED_MISSING_IDENTITY
        else:
            # Defensive branch: under current Phase 2 rules, any is_valid
            # row with availability_status != "Sold Out" is guaranteed to
            # have a usable total_fare (MISSING_TOTAL_FARE would otherwise
            # make it INVALID) — so this path is not expected to fire on
            # real Phase-2-validated data today. Kept for robustness.
            reason = R.REASON_EXCLUDED_UNUSABLE_PRICE
        results[obs_id] = DedupResult(
            duplicate_group_id=f"{R.UNGROUPED_GROUP_ID_PREFIX}{obs_id}",
            is_duplicate=False,
            duplicate_of=None,
            duplicate_reason=reason,
            retained=True,
            capture_signature_agreement=None,
        )

    # --- Process each bucket independently, sorted deterministically ------
    for bucket_key, obs_ids in buckets.items():
        # Deterministic internal order regardless of input order.
        ordered = sorted(obs_ids, key=lambda oid: _canonical_sort_key(None, identities[oid]))

        # Partition this bucket into time-tolerance clusters. Within a
        # bucket, ALL rows already share identical product-instance
        # identity + source + total_fare (or sold-out status) — the only
        # remaining question is whether they're close enough in time to
        # count as the SAME capture event, or independent (but numerically
        # coincidental) same-priced observations far apart in time.
        # APPROVED anchored-sweep rule — explicitly NOT transitive chaining.
        # Walk the bucket in deterministic timestamp order. The earliest
        # record is the ANCHOR of the currently open group. A following
        # record joins that group only if it is within tolerance OF THE
        # ANCHOR — never merely of its nearest neighbour. The first record
        # that exceeds the anchor's window closes the group and becomes the
        # anchor of a new one. This is what prevents a slow drift of
        # observations, each 15 minutes after the last, from chaining into
        # one unbounded group spanning hours.
        clusters: List[List[str]] = []
        anchor_ts: Optional[datetime] = None
        for obs_id in ordered:
            ident = identities[obs_id]
            within_anchor = (
                bool(clusters)
                and anchor_ts is not None
                and ident.collection_ts is not None
                and abs(ident.collection_ts - anchor_ts)
                <= timedelta(minutes=R.TIME_TOLERANCE_MINUTES)
            )
            if within_anchor:
                clusters[-1].append(obs_id)
            else:
                clusters.append([obs_id])
                anchor_ts = ident.collection_ts

        sold_out_bucket = bucket_key[-1] == "SOLD_OUT"

        for cluster in clusters:
            cluster_sorted = sorted(cluster, key=lambda oid: _canonical_sort_key(None, identities[oid]))
            canonical_id = cluster_sorted[0]

            if len(cluster_sorted) == 1:
                results[canonical_id] = DedupResult(
                    duplicate_group_id=f"{R.SINGLETON_GROUP_ID_PREFIX}{canonical_id}",
                    is_duplicate=False,
                    duplicate_of=None,
                    duplicate_reason=R.REASON_RETAINED_UNIQUE,
                    retained=True,
                    capture_signature_agreement=None,
                )
                continue

            # Confirmed duplicate group. The identifier is derived from the
            # canonical observation_id alone — it deliberately does not embed
            # the bucket key, which would put a formatted fare inside an
            # audit field.
            group_id = f"{R.DUPLICATE_GROUP_ID_PREFIX}{canonical_id}"

            reason = (
                R.REASON_SOLD_OUT_TECHNICAL_DUPLICATE
                if sold_out_bucket
                else R.REASON_TECHNICAL_DUPLICATE
            )

            # AUDIT-ONLY, computed once per confirmed group and recorded on
            # every member (canonical included) so the audit trail reads the
            # same from any row of the group.
            agreement = group_capture_signature_agreement(
                [rows_by_id[oid] for oid in cluster_sorted]
            )

            results[canonical_id] = DedupResult(
                duplicate_group_id=group_id,
                is_duplicate=False,
                duplicate_of=None,
                duplicate_reason=R.REASON_RETAINED_CANONICAL_OF_DUPLICATE_GROUP,
                retained=True,
                capture_signature_agreement=agreement,
            )
            for dup_id in cluster_sorted[1:]:
                results[dup_id] = DedupResult(
                    duplicate_group_id=group_id,
                    is_duplicate=True,
                    duplicate_of=canonical_id,
                    duplicate_reason=reason,
                    retained=False,
                    capture_signature_agreement=agreement,
                )

    # --- Ambiguous missing-timestamp defensive path ------------------------
    # Defensive / future-proofing only: under the CURRENT Phase 2 rules a
    # missing collection_timestamp always yields is_valid=False
    # (MISSING_COLLECTION_TIMESTAMP), so no row reaching this function
    # (which only receives is_valid==True rows) can have a missing
    # timestamp today. This branch exists so that if a future Phase 2
    # revision ever lets such a row through as valid, it is handled
    # explicitly rather than crashing or silently mis-grouping. See
    # test_ambiguous_missing_timestamp_defensive_path for a direct,
    # synthetic exercise of this code path.
    for obs_id in missing_timestamp_rows:
        ident = identities[obs_id]
        bucket_key = _grouping_bucket_key(ident)
        has_candidate = bucket_key is not None and bucket_key in buckets and len(buckets[bucket_key]) >= 1
        reason = (
            R.REASON_AMBIGUOUS_MISSING_TIMESTAMP
            if has_candidate
            else R.REASON_RETAINED_UNIQUE
        )
        results[obs_id] = DedupResult(
            duplicate_group_id=f"{R.UNGROUPED_GROUP_ID_PREFIX}{obs_id}",
            is_duplicate=False,
            duplicate_of=None,
            duplicate_reason=reason,
            retained=True,
            capture_signature_agreement=None,
        )

    return results


# ---------------------------------------------------------------------------
# capture_signature cross-check (informational only, never authoritative)
# ---------------------------------------------------------------------------

def capture_signature_agreement(row_a: Dict[str, Any], row_b: Dict[str, Any]) -> Optional[bool]:
    """
    Informational cross-check only: do two rows' pre-existing
    capture_signature values agree (equal) or disagree? Returns None if
    either is missing. NEVER used to decide duplicate status — see
    module docstring and rules.py header.
    """
    a = _clean_str(row_a.get("capture_signature"))
    b = _clean_str(row_b.get("capture_signature"))
    if a is None or b is None:
        return None
    return a == b


def group_capture_signature_agreement(rows: List[Dict[str, Any]]) -> Optional[bool]:
    """
    AUDIT-ONLY. Do ALL members of a confirmed duplicate group carry the same
    capture_signature?

    Returns True when every member's signature is present and identical,
    False when present signatures disagree, and None when the question cannot
    be answered (fewer than two members, or any member's signature missing).

    This is recorded on every member of the group, canonical included, so the
    audit trail reads identically from any row. It is NEVER an additional
    condition for duplicate status: the locked rule remains exactly the five
    approved conditions. On the one real duplicate pair in the dataset
    (OBS00769/OBS00770) this evaluates to False, which is precisely why the
    field is informational — the signature disagrees with a decision the
    locked rule reaches correctly.
    """
    if len(rows) < 2:
        return None
    signatures = [_clean_str(row.get("capture_signature")) for row in rows]
    if any(sig is None for sig in signatures):
        return None
    return len(set(signatures)) == 1


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_deduplication(validated_df: pd.DataFrame) -> pd.DataFrame:
    """
    Run Phase 6 deduplication against a Phase 2 VALIDATED DataFrame
    (must already contain is_valid / validation_status / validation_reason
    / validation_errors columns).

    Returns a NEW DataFrame: every input row preserved (no deletions),
    with the following columns appended:
        duplicate_group_id, is_duplicate, duplicate_of, duplicate_reason,
        retained, capture_signature_agreement

    Order-independence: rows are processed via a dict keyed by
    observation_id internally; the returned DataFrame preserves the
    ORIGINAL input row order (for output stability/readability), but the
    grouping decisions themselves do not depend on that order — see
    test_shuffled_input_produces_identical_grouping.
    """
    if "is_valid" not in validated_df.columns:
        raise ValueError(
            "run_deduplication() requires a Phase-2-validated DataFrame "
            "with an 'is_valid' column. Got columns: "
            f"{list(validated_df.columns)}"
        )

    records = validated_df.to_dict(orient="records")

    # APPROVED: strict literal parsing of the Phase 2 verdict. bool("False")
    # is True in Python, so any truthiness-based read would silently pull the
    # four INVALID rows into the grouping population. An unrecognized value
    # raises rather than being quietly downgraded to False, because a
    # silently shrunk grouping population would change the deduplication
    # result without anyone noticing.
    validity: Dict[str, bool] = {}
    for r in records:
        obs_id = r.get("observation_id")
        try:
            validity[obs_id] = R.parse_is_valid(r.get("is_valid"))
        except R.IsValidParseError as exc:
            raise R.IsValidParseError("Row %s: %s" % (obs_id, exc)) from exc

    valid_records = [r for r in records if validity[r.get("observation_id")]]

    dedup_results = group_and_mark(valid_records)

    # capture_signature_agreement: for duplicate rows, compare against the
    # canonical record they were matched to.
    by_id = {r["observation_id"]: r for r in valid_records}

    out_rows = []
    for r in records:
        obs_id = r["observation_id"]
        row_out = dict(r)  # preserve every original + Phase 2 column

        is_valid_flag = validity[obs_id]

        if not is_valid_flag:
            row_out["duplicate_group_id"] = f"{R.SKIPPED_GROUP_ID_PREFIX}{obs_id}"
            row_out["is_duplicate"] = False
            row_out["duplicate_of"] = None
            row_out["duplicate_reason"] = R.REASON_SKIPPED_INVALID_BY_PHASE2
            row_out["retained"] = True
            row_out["capture_signature_agreement"] = None
        else:
            res = dedup_results[obs_id]
            row_out["duplicate_group_id"] = res.duplicate_group_id
            row_out["is_duplicate"] = res.is_duplicate
            row_out["duplicate_of"] = res.duplicate_of
            row_out["duplicate_reason"] = res.duplicate_reason
            row_out["retained"] = res.retained
            # Group-level audit value: identical on every member of a
            # confirmed duplicate group, None where there is no group.
            row_out["capture_signature_agreement"] = res.capture_signature_agreement

        out_rows.append(row_out)

    return pd.DataFrame(out_rows)


def build_canonical_view(deduped_df: pd.DataFrame) -> pd.DataFrame:
    """
    Derived view: only rows that are both Phase-2-valid and Phase-6-retained
    (i.e. not marked as a duplicate). This is a FILTER, not a deletion of
    anything from the full audited output — the full table remains the
    source of truth and is never discarded.
    """
    is_valid_mask = deduped_df["is_valid"].apply(R.parse_is_valid)
    return deduped_df[is_valid_mask & (deduped_df["retained"] == True)].reset_index(drop=True)  # noqa: E712


# ---------------------------------------------------------------------------
# Duplicate audit report (third approved Phase 6 output)
# ---------------------------------------------------------------------------

AUDIT_REPORT_COLUMNS = [
    "duplicate_group_id",
    "group_size",
    "canonical_observation_id",
    "canonical_collection_timestamp",
    "duplicate_observation_ids",
    "max_timestamp_delta_minutes",
    "capture_signature_agreement",
    "origin",
    "destination",
    "carrier",
    "flight_number",
    "travel_date",
    "departure_time",
    "fare_class",
    "advance_purchase_window",
    "source",
    "total_fare",
    "availability_status",
    "duplicate_reason",
]


def build_duplicate_audit_report(deduped_df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per CONFIRMED duplicate group — the reviewable summary of every
    collapse decision the engine made.

    Only groups that actually contain a duplicate appear here. Singletons,
    excluded rows and Phase 2 invalid rows are absent by design: they are
    already fully accounted for in the audited dataset, and listing them here
    would bury the handful of real decisions in 700+ non-events.

    Returns an empty (correctly-columned) frame when no duplicates exist, so
    downstream readers never have to special-case a missing file.
    """
    duplicates = deduped_df[deduped_df["is_duplicate"] == True]  # noqa: E712
    group_ids = sorted(set(duplicates["duplicate_group_id"].tolist()))

    rows = []
    for group_id in group_ids:
        members = deduped_df[deduped_df["duplicate_group_id"] == group_id]
        canonical_rows = members[members["is_duplicate"] == False]  # noqa: E712
        if len(canonical_rows) != 1:
            raise ValueError(
                "Duplicate group %s has %d canonical records; exactly one is "
                "required." % (group_id, len(canonical_rows))
            )
        canonical = canonical_rows.iloc[0]
        dup_ids = sorted(members[members["is_duplicate"] == True]["observation_id"].tolist())  # noqa: E712

        timestamps = [
            ts for ts in (_parse_ts(v) for v in members["collection_timestamp"].tolist())
            if ts is not None
        ]
        delta_minutes = (
            int((max(timestamps) - min(timestamps)).total_seconds() // 60)
            if len(timestamps) >= 2
            else 0
        )

        rows.append({
            "duplicate_group_id": group_id,
            "group_size": len(members),
            "canonical_observation_id": canonical["observation_id"],
            "canonical_collection_timestamp": canonical["collection_timestamp"],
            "duplicate_observation_ids": ";".join(dup_ids),
            "max_timestamp_delta_minutes": delta_minutes,
            "capture_signature_agreement": canonical["capture_signature_agreement"],
            "origin": canonical["origin"],
            "destination": canonical["destination"],
            "carrier": canonical["carrier"],
            "flight_number": canonical["flight_number"],
            "travel_date": canonical["travel_date"],
            "departure_time": canonical["departure_time"],
            "fare_class": canonical["fare_class"],
            "advance_purchase_window": canonical["advance_purchase_window"],
            "source": canonical["source"],
            "total_fare": canonical["total_fare"],
            "availability_status": canonical["availability_status"],
            "duplicate_reason": members[members["is_duplicate"] == True].iloc[0]["duplicate_reason"],  # noqa: E712
        })

    return pd.DataFrame(rows, columns=AUDIT_REPORT_COLUMNS)
