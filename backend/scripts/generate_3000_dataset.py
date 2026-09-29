"""Generate 3,000 synthetic observations across all 15 basket routes for full-scale Vayu training."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import hashlib
import os
import random
from pathlib import Path

random.seed(42)

ROUTES = [
    ("BOM", "DEL"), ("BLR", "DEL"), ("BLR", "BOM"), ("DEL", "HYD"),
    ("DEL", "PNQ"), ("CCU", "DEL"), ("AMD", "DEL"), ("DEL", "MAA"),
    ("BOM", "HYD"), ("BLR", "CCU"), ("DEL", "SXR"), ("DEL", "GOI"),
    ("DEL", "GAU"), ("BLR", "COK"), ("DEL", "IDR")
]

CARRIERS = {
    ("BOM", "DEL"): [("6E", "6E-2341"), ("AI", "AI-865"), ("QP", "QP-1123")],
    ("BLR", "DEL"): [("6E", "6E-5011"), ("AI", "AI-503"), ("IX", "IX-782")],
    ("BLR", "BOM"): [("6E", "6E-442"), ("AI", "AI-610"), ("QP", "QP-1304")],
    ("DEL", "HYD"): [("6E", "6E-773"), ("AI", "AI-540"), ("SG", "SG-451")],
    ("DEL", "PNQ"): [("6E", "6E-381"), ("AI", "AI-851"), ("QP", "QP-1201")],
    ("CCU", "DEL"): [("6E", "6E-6120"), ("AI", "AI-701"), ("SG", "SG-988")],
    ("AMD", "DEL"): [("6E", "6E-205"), ("AI", "AI-18"), ("IX", "IX-340")],
    ("DEL", "MAA"): [("6E", "6E-843"), ("AI", "AI-542"), ("IX", "IX-621")],
    ("BOM", "HYD"): [("6E", "6E-631"), ("AI", "AI-619"), ("QP", "QP-1402")],
    ("BLR", "CCU"): [("6E", "6E-904"), ("AI", "AI-772"), ("SG", "SG-321")],
    ("DEL", "SXR"): [("6E", "6E-212"), ("AI", "AI-825"), ("SG", "SG-101")],
    ("DEL", "GOI"): [("6E", "6E-334"), ("AI", "AI-861"), ("QP", "QP-1510")],
    ("DEL", "GAU"): [("6E", "6E-415"), ("AI", "AI-791"), ("SG", "SG-601")],
    ("BLR", "COK"): [("6E", "6E-521"), ("AI", "AI-512"), ("IX", "IX-431")],
    ("DEL", "IDR"): [("6E", "6E-284"), ("AI", "AI-635"), ("IX", "IX-221")]
}

COLLECTION_DAYS = [
    datetime(2026, 9, 5),
    datetime(2026, 9, 6),
    datetime(2026, 9, 7),
    datetime(2026, 9, 8),
    datetime(2026, 9, 9),
]
COLLECTION_TIMES = [(9, 0), (14, 30), (20, 15)]

FARE_CLASSES = ["Economy Saver", "Economy Standard", "Economy Flexi"]
BASE_FARE_BY_CLASS = {
    "Economy Saver": 4200,
    "Economy Standard": 5400,
    "Economy Flexi": 6600,
}

SOURCES = ["AirlineSite", "MMT", "Cleartrip", "Goibibo", "EaseMyTrip"]

WINDOW_BANDS = [
    ("T1", 0, 2),
    ("T7", 5, 9),
    ("T15", 12, 18),
    ("T30", 25, 35),
    ("T45", 40, 50),
]

TRAVEL_DATES = [
    datetime(2026, 9, 7),
    datetime(2026, 9, 13),
    datetime(2026, 9, 21),
    datetime(2026, 10, 6),
    datetime(2026, 10, 22),
]

FEES_CHOICES = [100, 120, 150, 180, 200]

FIELDNAMES = [
    "observation_id", "capture_signature", "economic_signature",
    "origin", "destination", "carrier", "flight_number",
    "travel_date", "departure_time",
    "collection_timestamp", "advance_purchase_days", "advance_purchase_window",
    "fare_class", "base_fare", "taxes", "fees", "total_fare",
    "source", "availability_status",
]


def make_hash(*parts: object) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def window_for(adv_days: int) -> str:
    for label, lo, hi in WINDOW_BANDS:
        if lo <= adv_days <= hi:
            return f"{label}({lo}-{hi})"
    return "OUT_OF_BAND"


def price_curve(fare_class: str, adv_days: int) -> tuple[int, int, int, int]:
    base = BASE_FARE_BY_CLASS[fare_class]
    curve_factor = 1 + max(0, (20 - adv_days)) * 0.025
    price = base * curve_factor * random.uniform(0.96, 1.06)
    base_fare = round(price)
    taxes = round(price * 0.18)
    fees = random.choice(FEES_CHOICES)
    total_fare = base_fare + taxes + fees
    return base_fare, taxes, fees, total_fare


def generate_dataset(target_count: int = 3000) -> list[dict]:
    rows: list[dict] = []
    obs_counter = 1

    departure_times = {}

    # 1. Systematically generate observations across rounds, routes, flights, classes, dates
    while len(rows) < target_count - 25:
        for collection_day in COLLECTION_DAYS:
            if len(rows) >= target_count - 25:
                break
            for (hh, mm) in COLLECTION_TIMES:
                if len(rows) >= target_count - 25:
                    break
                collection_dt = collection_day.replace(hour=hh, minute=mm)
                for route in ROUTES:
                    if len(rows) >= target_count - 25:
                        break
                    origin, destination = route
                    for carrier, flight_number in CARRIERS[route]:
                        if len(rows) >= target_count - 25:
                            break
                        if flight_number not in departure_times:
                            departure_times[flight_number] = f"{random.randint(5, 21):02d}:{random.choice(['00', '15', '30', '45'])}"
                        dep_time = departure_times[flight_number]

                        for travel_date in TRAVEL_DATES:
                            if len(rows) >= target_count - 25:
                                break
                            adv_days = (travel_date.date() - collection_dt.date()).days
                            if adv_days < 0:
                                continue

                            selected_classes = random.sample(FARE_CLASSES, k=random.choice([1, 2]))
                            for fare_class in selected_classes:
                                if len(rows) >= target_count - 25:
                                    break
                                selected_sources = random.sample(SOURCES, k=random.choice([1, 2]))
                                for source in selected_sources:
                                    if len(rows) >= target_count - 25:
                                        break
                                    base_fare, taxes, fees, total_fare = price_curve(fare_class, adv_days)
                                    oid = f"OBS{obs_counter:05d}"
                                    obs_counter += 1
                                    window = window_for(adv_days)
                                    cap_sig = make_hash(flight_number, fare_class, travel_date.date(), source, collection_dt.strftime("%Y-%m-%d %H:%M"))
                                    econ_sig = make_hash(origin, destination, fare_class, travel_date.date(), window)

                                    rows.append({
                                        "observation_id": oid,
                                        "capture_signature": cap_sig,
                                        "economic_signature": econ_sig,
                                        "origin": origin,
                                        "destination": destination,
                                        "carrier": carrier,
                                        "flight_number": flight_number,
                                        "travel_date": travel_date.strftime("%Y-%m-%d"),
                                        "departure_time": dep_time,
                                        "collection_timestamp": collection_dt.strftime("%Y-%m-%d %H:%M"),
                                        "advance_purchase_days": adv_days,
                                        "advance_purchase_window": window,
                                        "fare_class": fare_class,
                                        "base_fare": base_fare,
                                        "taxes": taxes,
                                        "fees": fees,
                                        "total_fare": total_fare,
                                        "source": source,
                                        "availability_status": "Available",
                                    })

    # 2. Add realistic ground-truth edge cases to complete to exact target_count
    anchor_col = COLLECTION_DAYS[0].replace(hour=9, minute=0)
    anchor_travel = TRAVEL_DATES[2]

    # Technical duplicate
    oid_dup1 = f"OBS{obs_counter:05d}"; obs_counter += 1
    oid_dup2 = f"OBS{obs_counter:05d}"; obs_counter += 1
    adv_d = (anchor_travel.date() - anchor_col.date()).days
    w = window_for(adv_d)
    rows.append({
        "observation_id": oid_dup1,
        "capture_signature": make_hash("6E-2341", "Economy Saver", anchor_travel.date(), "AirlineSite", anchor_col.strftime("%Y-%m-%d %H:%M")),
        "economic_signature": make_hash("BOM", "DEL", "Economy Saver", anchor_travel.date(), w),
        "origin": "BOM", "destination": "DEL", "carrier": "6E", "flight_number": "6E-2341",
        "travel_date": anchor_travel.strftime("%Y-%m-%d"), "departure_time": "08:10",
        "collection_timestamp": anchor_col.strftime("%Y-%m-%d %H:%M"),
        "advance_purchase_days": adv_d, "advance_purchase_window": w,
        "fare_class": "Economy Saver", "base_fare": 4200, "taxes": 756, "fees": 150, "total_fare": 5106,
        "source": "AirlineSite", "availability_status": "Available",
    })
    rows.append({
        "observation_id": oid_dup2,
        "capture_signature": make_hash("6E-2341", "Economy Saver", anchor_travel.date(), "AirlineSite", anchor_col.strftime("%Y-%m-%d %H:%M")),
        "economic_signature": make_hash("BOM", "DEL", "Economy Saver", anchor_travel.date(), w),
        "origin": "BOM", "destination": "DEL", "carrier": "6E", "flight_number": "6E-2341",
        "travel_date": anchor_travel.strftime("%Y-%m-%d"), "departure_time": "08:10",
        "collection_timestamp": (anchor_col + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M"),
        "advance_purchase_days": adv_d, "advance_purchase_window": w,
        "fare_class": "Economy Saver", "base_fare": 4200, "taxes": 756, "fees": 150, "total_fare": 5106,
        "source": "AirlineSite", "availability_status": "Available",
    })

    # Sold out flight
    oid_sold = f"OBS{obs_counter:05d}"; obs_counter += 1
    rows.append({
        "observation_id": oid_sold,
        "capture_signature": make_hash("AI-865", "Economy Saver", anchor_travel.date(), "AirlineSite", anchor_col.strftime("%Y-%m-%d %H:%M")),
        "economic_signature": make_hash("BOM", "DEL", "Economy Saver", anchor_travel.date(), w),
        "origin": "BOM", "destination": "DEL", "carrier": "AI", "flight_number": "AI-865",
        "travel_date": anchor_travel.strftime("%Y-%m-%d"), "departure_time": "10:30",
        "collection_timestamp": anchor_col.strftime("%Y-%m-%d %H:%M"),
        "advance_purchase_days": adv_d, "advance_purchase_window": w,
        "fare_class": "Economy Saver", "base_fare": "", "taxes": "", "fees": "", "total_fare": "",
        "source": "AirlineSite", "availability_status": "Sold Out",
    })

    # Fill remaining rows up to exact target_count
    while len(rows) < target_count:
        route = random.choice(ROUTES)
        carrier, flight = random.choice(CARRIERS[route])
        t_date = random.choice(TRAVEL_DATES)
        c_day = random.choice(COLLECTION_DAYS)
        hh, mm = random.choice(COLLECTION_TIMES)
        c_dt = c_day.replace(hour=hh, minute=mm)
        adv = (t_date.date() - c_dt.date()).days
        if adv < 0:
            continue
        fc = random.choice(FARE_CLASSES)
        src = random.choice(SOURCES)
        bf, tx, fee, tot = price_curve(fc, adv)
        oid = f"OBS{obs_counter:05d}"; obs_counter += 1
        win = window_for(adv)
        rows.append({
            "observation_id": oid,
            "capture_signature": make_hash(flight, fc, t_date.date(), src, c_dt.strftime("%Y-%m-%d %H:%M")),
            "economic_signature": make_hash(route[0], route[1], fc, t_date.date(), win),
            "origin": route[0], "destination": route[1], "carrier": carrier, "flight_number": flight,
            "travel_date": t_date.strftime("%Y-%m-%d"), "departure_time": "12:00",
            "collection_timestamp": c_dt.strftime("%Y-%m-%d %H:%M"),
            "advance_purchase_days": adv, "advance_purchase_window": win,
            "fare_class": fc, "base_fare": bf, "taxes": tx, "fees": fee, "total_fare": tot,
            "source": src, "availability_status": "Available",
        })

    return rows[:target_count]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate 3,000 synthetic observations for Vayu training.")
    parser.add_argument("--count", type=int, default=3000, help="Target count of observations (default: 3000)")
    parser.add_argument("--output", default="data/synthetic/vayu_synthetic_3000_observations.csv", help="Output CSV path")
    args = parser.parse_args()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Generating {args.count} synthetic airfare observations across all 15 basket routes...")
    rows = generate_dataset(args.count)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Successfully generated {len(rows)} observations at: {out_path}")


if __name__ == "__main__":
    main()
