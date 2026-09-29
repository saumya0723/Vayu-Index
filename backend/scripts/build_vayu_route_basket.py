"""
STEP 5 – VAYU Index Route Basket Construction
==============================================
Source : data/official/dgca/processed/dgca_city_pair_passenger_traffic_2024_25.csv
Outputs:
  outputs/dgca_route_traffic_ranking.csv
  data/official/dgca/processed/vayu_route_basket_2024_25.csv          (NOT produced until basket is approved)
  data/official/dgca/processed/route_basket_metadata.json             (NOT produced until basket is approved)
  docs/route_basket_methodology.md

Methodology:
  - All routes ranked by official DGCA 2024-25 bidirectional passenger traffic.
  - Two basket options evaluated (pure traffic-ranked vs. representative).
  - Recommended basket selected on coverage + geographic spread + transparency.
  - Traffic-proportional weights derived from selected basket only.

CHANGE LOG (Phase 5 data-integrity fixes — see accompanying report)
---------------------------------------------------------------------
TASK A — Removed the unsafe `city[:3].upper()` pseudo-IATA fallback.
         Unknown/ambiguous cities now resolve to mapping_status =
         "FLAG_FOR_REVIEW" and route_id = "FLAG_FOR_REVIEW" instead of a
         fabricated 3-letter code. Added five documented, verified aliases
         (GOA, MANGALORE, SIMLA, BHATINDA, TIRUCHIRAPALLY) for spelling
         variants of cities already present in CITY_TO_CODE.
TASK B — Self-pairs (city_1_standardized == city_2_standardized) are now
         explicitly detected, retained in the loaded dataset, and excluded
         from basket eligibility with an explicit exclusion_reason. They
         are never silently dropped.
TASK C — Ranking export no longer uses a global float_format. Passenger
         columns are written as exact integers (nullable Int64) and
         cumulative_coverage_pct retains 4 decimal places.
DASH TREATMENT (Option C — transparent dual treatment, per direction)
         Two totals are now computed and exported side by side:
           - conservative_total_bidirectional_passengers: NaN if either
             direction is DGCA_DASH/missing (used for ranking, unchanged
             default behaviour).
           - zero_treated_total_bidirectional_passengers: DGCA_DASH
             treated as 0, labelled as an analytical alternative only.
         Ranking/eligibility continues to use the conservative total.
"""

import os
import json
import math
import pandas as pd
from datetime import datetime, timezone

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DGCA_CSV   = os.path.join(BASE_DIR, "data", "official", "dgca", "processed",
                           "dgca_city_pair_passenger_traffic_2024_25.csv")
OUT_DIR    = os.path.join(BASE_DIR, "outputs")
PROC_DIR   = os.path.join(BASE_DIR, "data", "official", "dgca", "processed")
DOCS_DIR   = os.path.join(BASE_DIR, "docs")

os.makedirs(OUT_DIR,  exist_ok=True)
os.makedirs(PROC_DIR, exist_ok=True)
os.makedirs(DOCS_DIR, exist_ok=True)

RANKING_CSV = os.path.join(OUT_DIR,  "dgca_route_traffic_ranking.csv")
BASKET_CSV  = os.path.join(PROC_DIR, "vayu_route_basket_2024_25.csv")
BASKET_META = os.path.join(PROC_DIR, "route_basket_metadata.json")
METHODOLOGY = os.path.join(DOCS_DIR, "route_basket_methodology.md")

FINANCIAL_YEAR = "2024-25"

# Sentinel used whenever a city cannot be safely resolved to a verified
# IATA code. This is NEVER a real airport code and must never be treated
# as one downstream.
FLAG_FOR_REVIEW = "FLAG_FOR_REVIEW"

# ─── City → IATA / Short-code mapping ────────────────────────────────────────
# DOCUMENTED MAPPINGS only. Each entry is traceable to a public IATA or DGCA
# source. No ambiguous merges. Entries with notes explain the mapping.
#
# Rule: if a DGCA city name maps 1-to-1 to a single airport/IATA code in
# India (one dominant commercial airport serving that city), the mapping is
# applied. Ambiguous or multi-airport cities are NOT merged here.
#
CITY_TO_CODE = {
    # DGCA standardized name (UPPER)  : (IATA, short-label, region, notes)
    "DELHI"           : ("DEL", "DEL", "North",     "Indira Gandhi Intl – only major commercial airport"),
    "MUMBAI"          : ("BOM", "BOM", "West",      "Chhatrapati Shivaji Maharaj Intl – dominant hub"),
    "BENGALURU"       : ("BLR", "BLR", "South",     "Kempegowda Intl – only commercial airport since 2008"),
    "HYDERABAD"       : ("HYD", "HYD", "South",     "Rajiv Gandhi Intl – only commercial airport since 2008"),
    "CHENNAI"         : ("MAA", "MAA", "South",     "Chennai Intl – single primary hub"),
    "KOLKATA"         : ("CCU", "CCU", "East",      "Netaji Subhas Chandra Bose Intl"),
    "PUNE"            : ("PNQ", "PNQ", "West",      "Pune Airport – single airport"),
    "AHMEDABAD"       : ("AMD", "AMD", "West",      "Sardar Vallabhbhai Patel Intl"),
    "KOCHI"           : ("COK", "COK", "South",     "Cochin Intl"),
    "JAIPUR"          : ("JAI", "JAI", "North",     "Jaipur Intl"),
    "SRINAGAR"        : ("SXR", "SXR", "North",     "Sheikh ul-Alam Intl"),
    "GUWAHATI"        : ("GAU", "GAU", "Northeast", "Lokpriya Gopinath Bordoloi Intl"),
    "LUCKNOW"         : ("LKO", "LKO", "North",     "Chaudhary Charan Singh Intl"),
    "PATNA"           : ("PAT", "PAT", "East",      "Jay Prakash Narayan Intl"),
    "AMRITSAR"        : ("ATQ", "ATQ", "North",     "Sri Guru Ram Dass Jee Intl"),
    "DABOLIM"         : ("GOI", "GOI", "West",      "Goa Intl / Dabolim, South Goa – verified single airport"),
    # NOTE: "GOA" is deliberately NOT mapped here. Goa has had TWO separate,
    # currently-operating commercial airports since 5 Jan 2023: Dabolim
    # (IATA GOI, South Goa) and Manohar International Airport at Mopa
    # (IATA GOX, North Goa). DGCA's processed CSV uses "DABOLIM" and "GOA"
    # as two distinct standardized city names for the same 2024-25
    # reporting year, with materially different (non-identical) passenger
    # counts for the same city-pairs in each case (verified: e.g.
    # DELHI-DABOLIM = 1,561,827 vs DELHI-GOA = 1,005,576 bidirectional pax
    # — not duplicate/rounding-level differences). This is consistent with
    # "GOA" and "DABOLIM" referring to two genuinely different airports
    # (GOX and GOI respectively), but this has NOT been confirmed against
    # DGCA's own documentation, and the raw PDF text gives no further
    # disambiguating detail. Mapping "GOA" to either GOI or GOX here would
    # be an unverified guess, not a documented, unambiguous mapping.
    # Left as FLAG_FOR_REVIEW until DGCA methodology is confirmed.
    "BHUBANESWAR"     : ("BBI", "BBI", "East",      "Biju Patnaik Intl"),
    "VARANASI"        : ("VNS", "VNS", "North",     "Lal Bahadur Shastri Intl"),
    "INDORE"          : ("IDR", "IDR", "Central",   "Devi Ahilya Bai Holkar Airport"),
    "NAGPUR"          : ("NAG", "NAG", "Central",   "Dr. Babasaheb Ambedkar Intl"),
    "RAIPUR"          : ("RPR", "RPR", "Central",   "Swami Vivekananda Airport"),
    "COIMBATORE"      : ("CJB", "CJB", "South",     "Coimbatore Intl"),
    "VISAKHAPATNAM"   : ("VTZ", "VTZ", "South",     "Visakhapatnam Airport"),
    "RANCHI"          : ("IXR", "IXR", "East",      "Birsa Munda Airport"),
    "IMPHAL"          : ("IMF", "IMF", "Northeast", "Bir Tikendrajit Intl"),
    "TIRUPATI"        : ("TIR", "TIR", "South",     "Tirupati Airport"),
    "TRIVANDRUM"      : ("TRV", "TRV", "South",     "Trivandrum Intl"),
    "UDAIPUR"         : ("UDR", "UDR", "North",     "Maharana Pratap Airport"),
    "GWALIOR"         : ("GWL", "GWL", "North",     "Gwalior Airport"),
    "JAMMU"           : ("IXJ", "IXJ", "North",     "Satwari Airport"),
    "DIBRUGARH"       : ("DIB", "DIB", "Northeast", "Dibrugarh Airport"),
    "SILCHAR"         : ("IXS", "IXS", "Northeast", "Silchar Airport"),
    "AGARTALA"        : ("IXA", "IXA", "Northeast", "Maharaja Bir Bikram Airport"),
    "MANGALURU"       : ("IXE", "IXE", "South",     "Mangaluru Intl"),
    "MANGALORE"       : ("IXE", "IXE", "South",     "Older English spelling of Mangaluru — same airport, "
                                                     "verified against IATA/DGCA usage."),
    "THIRUVANANTHAPURAM" : ("TRV", "TRV", "South",  "Same as TRIVANDRUM – DGCA variant"),
    "PORT BLAIR"      : ("IXZ", "IXZ", "East",      "Veer Savarkar Intl"),
    "HUBLI"           : ("HBX", "HBX", "South",     "Hubballi Airport (DGCA uses HUBLI)"),
    "LEH"             : ("IXL", "IXL", "North",     "Kushok Bakula Rimpochhe Airport"),
    "SHIRDI"          : ("SAG", "SAG", "West",      "Shirdi Airport"),
    "GORAKHPUR"       : ("GOP", "GOP", "North",     "Gorakhpur Airport"),
    "CHANDIGARH"      : ("IXC", "IXC", "North",     "Chandigarh Airport / Shaheed Bhagat Singh Intl"),
    "DEHRADUN"        : ("DED", "DED", "North",     "Jolly Grant Airport"),
    "DEHRA DUN"       : ("DED", "DED", "North",     "DGCA variant spelling for Dehradun"),
    "DURGAPUR"        : ("RDP", "RDP", "East",      "Kazi Nazrul Islam Airport"),
    "AURANGABAD"      : ("IXU", "IXU", "West",      "Aurangabad Airport (also Chikkalthana)"),
    "KOLHAPUR"        : ("KLH", "KLH", "West",      "Kolhapur Airport"),
    "NANDED"          : ("NDC", "NDC", "West",      "Shri Guru Gobind Singh Ji Airport"),
    "SURAT"           : ("STV", "STV", "West",      "Surat Airport"),
    "VADODARA"        : ("BDQ", "BDQ", "West",      "Vadodara Airport"),
    "RAJKOT"          : ("RAJ", "RAJ", "West",      "Rajkot Airport"),
    "BHAVNAGAR"       : ("BHU", "BHU", "West",      "Bhavnagar Airport"),
    "JAMNAGAR"        : ("JGA", "JGA", "West",      "Jamnagar Airport"),
    "KANDLA"          : ("IXY", "IXY", "West",      "Kandla Airport"),
    "PORBANDAR"       : ("PBD", "PBD", "West",      "Porbandar Airport"),
    "NASHIK"          : ("ISK", "ISK", "West",      "Nashik Airport / Ozar Airport (DGCA uses NASIK)"),
    "NASIK"           : ("ISK", "ISK", "West",      "DGCA variant for Nashik"),
    "BELGAUM"         : ("IXG", "IXG", "South",     "Belgaum Airport (now Belagavi)"),
    "MYSORE"          : ("MYQ", "MYQ", "South",     "Mysore Airport"),
    "BAGDOGRA"        : ("IXB", "IXB", "East",      "Bagdogra Airport"),
    "AGRA"            : ("AGR", "AGR", "North",     "Agra Airport"),
    "BHUJ"            : ("BHJ", "BHJ", "West",      "Bhuj Airport"),
    "DIMAPUR"         : ("DMU", "DMU", "Northeast", "Dimapur Airport"),
    "AIZAWL"          : ("AJL", "AJL", "Northeast", "Lengpui Airport"),
    "SHILLONG"        : ("SHL", "SHL", "Northeast", "Umroi Airport"),
    "TEZPUR"          : ("TEZ", "TEZ", "Northeast", "Tezpur Airport"),
    "JORHAT"          : ("JRH", "JRH", "Northeast", "Jorhat Airport"),
    # NOTE: "ZERO" (below) was an incorrect guess in an earlier pass — the
    # DGCA standardized name is actually "ZIRO" (Ziro Airport, Arunachal
    # Pradesh), not "ZERO". Left deliberately unmapped pending IATA
    # verification (traffic is negligible: ~423 pax total).
    "LILABARI"        : ("IXI", "IXI", "Northeast", "Lilabari Airport"),
    "RUPSI"           : ("RUP", "RUP", "Northeast", "Rupsi Airport"),
    "PASIGHAT"        : ("IXT", "IXT", "Northeast", "Pasighat Airport"),
    "TEZU"            : ("TEI", "TEI", "Northeast", "Tezu Airport"),
    "ALONG"           : ("IXV", "IXV", "Northeast", "Along Airport"),
    "ITANAGAR"        : ("HGI", "HGI", "Northeast", "Itanagar / Donyi Polo Airport, opened 2023"),
    "COOCH BEHAR"     : ("COH", "COH", "East",      "Cooch Behar Airport"),
    "KESHOD"          : ("IXK", "IXK", "West",      "Keshod Airport"),
    "DIU"             : ("DIU", "DIU", "West",      "Diu Airport"),
    "GAYA"            : ("GAY", "GAY", "East",      "Gaya Airport"),
    "JABALPUR"        : ("JLR", "JLR", "Central",   "Jabalpur Airport"),
    "BHOPAL"          : ("BHO", "BHO", "Central",   "Raja Bhoj Airport"),
    "KHAJURAHO"       : ("HJR", "HJR", "Central",   "Khajuraho Airport"),
    "ALLAHABAD"       : ("IXD", "IXD", "North",     "Bamrauli Airport"),
    "PRAYAGRAJ"       : ("IXD", "IXD", "North",     "DGCA variant / Prayagraj = Allahabad"),
    "KULLU"           : ("KUU", "KUU", "North",     "Bhuntar Airport"),
    "SHIMLA"          : ("SLV", "SLV", "North",     "Shimla Airport"),
    "SIMLA"           : ("SLV", "SLV", "North",     "Older English spelling of Shimla — same airport, "
                                                     "verified against IATA/DGCA usage."),
    "BATHINDA"        : ("BUP", "BUP", "North",     "Bathinda Airport"),
    "BHATINDA"        : ("BUP", "BUP", "North",     "Alternate spelling of Bathinda — same airport, "
                                                     "verified against IATA/DGCA usage."),
    "LUDHIANA"        : ("LUH", "LUH", "North",     "Sahnewal Airport"),
    "HINDON AIRPORT"  : ("HDO", "HDO", "North",     "Hindon Civil Enclave, Ghaziabad"),
    "ADAMPUR"         : ("AIP", "AIP", "North",     "Adampur Airport"),
    "BIKANER"         : ("BKB", "BKB", "North",     "Nal Airport"),
    "JAISALMER"       : ("JSA", "JSA", "North",     "Jaisalmer Airport"),
    "JODHPUR"         : ("JDH", "JDH", "North",     "Jodhpur Airport"),
    "KOTA"            : ("KTU", "KTU", "North",     "Kota Airport"),
    "BAREILLY"        : ("BEK", "BEK", "North",     "Bareilly Airport"),
    "KANPUR"          : ("KNU", "KNU", "North",     "Kanpur Airport"),
    "PANTNAGAR"       : ("PGH", "PGH", "North",     "Pantnagar Airport"),
    "PITHORAGARH"     : ("PTB", "PTB", "North",     "Pithoragarh Airport"),
    "SALASAR"         : (None,  "SLS", "North",     "No IATA – regional airstrip"),
    "VIDYANAGAR"      : ("VDY", "VDY", "South",     "Vidyanagar Airport / Jindal Airport"),
    "VIJAYAWADA"      : ("VGA", "VGA", "South",     "Vijayawada Airport"),
    "RAJAHMUNDRY"     : ("RJA", "RJA", "South",     "Rajahmundry Airport"),
    "SALEM"           : ("SXV", "SXV", "South",     "Salem Airport"),
    "MADURAI"         : ("IXM", "IXM", "South",     "Madurai Airport"),
    "TUTICORIN"       : ("TCR", "TCR", "South",     "Thoothukudi Airport"),
    "TIRUCHIRAPPALLI" : ("TRZ", "TRZ", "South",     "Tiruchirappalli Intl"),
    "TIRUCHIRAPALLY"  : ("TRZ", "TRZ", "South",     "Alternate spelling of Tiruchirappalli (Trichy) — "
                                                     "same airport, verified against IATA/DGCA usage."),
    "CALICUT"         : ("CCJ", "CCJ", "South",     "Calicut Intl (Kozhikode)"),
    "KOZHIKODE"       : ("CCJ", "CCJ", "South",     "DGCA variant for Calicut"),
    "AYODHYA INTERNATIONAL AIRPORT": ("AYJ", "AYJ", "North", "Maharishi Valmiki Intl, opened 2023"),
    "RAJKOT INTERNATIONAL AIRPORT" : ("RAJ", "RAJ", "West",  "New Rajkot Intl (Hirasar), opened 2023 – DGCA uses full name"),

    # ── Added after Task 3 review of the 33 (now 31) unmapped city names ──────
    # Each verified against an independent public source (Wikipedia/AAI/
    # airline airport-directory pages) before being added. Category B
    # (valid distinct airport requiring explicit mapping) in all cases below
    # — none of these collapse a name into an existing, different airport.
    "AGATTI ISLAND"     : ("AGX", "AGX", "South",  "Agatti Airport, Lakshadweep — sole airstrip in the UT"),
    "BILASPUR"          : ("PAB", "PAB", "Central", "Bilasa Devi Kevat Airport, Chhattisgarh"),
    "CUDDAPAH"          : ("CDP", "CDP", "South",  "Kadapa Airport — DGCA uses older name 'Cuddapah'"),
    "DARBHANGA"         : ("DBR", "DBR", "East",   "Darbhanga Airport, Bihar"),
    "DEOGHAR"           : ("DGH", "DGH", "East",   "Deoghar Airport (Baba Baidyanath), Jharkhand"),
    "DHARAMSALA"        : ("DHM", "DHM", "North",  "Kangra Airport (Gaggal) — serves Dharamshala"),
    "JHARSUGUDA"        : ("JRG", "JRG", "East",   "Veer Surendra Sai Airport, Odisha"),
    "KANNUR"            : ("CNN", "CNN", "South",  "Kannur International Airport, Kerala"),
    "PONDICHERRY"       : ("PNY", "PNY", "South",  "Pondicherry Airport — DGCA uses 'Pondicherry' spelling"),
    "ROURKELA"          : ("RRK", "RRK", "East",   "Rourkela Airport, Odisha"),
    "SHIVAMOGGA AIRPORT": ("RQY", "RQY", "South",  "Shivamogga (Rashtrakavi Kuvempu) Airport, Karnataka"),
    "JALGAON"           : ("JLG", "JLG", "West",   "Jalgaon Airport, Maharashtra"),

    # ── Added after full Task 3 verification pass (this turn) ─────────────────
    # All confirmed via independent public sources (Wikipedia/AAI/airline
    # directories) before being added, per the "never invent a code" rule.
    "ALIGARH AIRPORT"      : ("HRH", "HRH", "North",  "Aligarh Airport, opened March 2024"),
    "AMBIKAPUR AIRPORT"    : ("AHA", "AHA", "Central", "Maa Mahamaya Airport (Ambikapur/Darima), Chhattisgarh"),
    "AZAMGARH AIRPORT"     : ("AZH", "AZH", "North",  "Azamgarh Airport, opened 2024"),
    "CHITRAKOOT AIRPORT"   : ("CWK", "CWK", "North",  "Chitrakoot Airport (Dewanga), Uttar Pradesh"),
    "GONDIA"               : ("GDB", "GDB", "Central", "Gondia (Birsi) Airport, Maharashtra"),
    "JAGDALPUR"            : ("JGB", "JGB", "Central", "Jagdalpur Airport, Chhattisgarh"),
    "JAMSHEDPUR"           : ("IXW", "IXW", "East",   "Sonari Airport, Jamshedpur"),
    "JEYPORE"              : ("PYB", "PYB", "East",   "Jeypore Airport (Sunabeda), Odisha"),
    "KALABURAGI"           : ("GBI", "GBI", "South",  "Kalaburagi (Gulbarga) Airport, Karnataka"),
    "KISHANGARH"           : ("KQH", "KQH", "North",  "Kishangarh Airport, Rajasthan (near Ajmer)"),
    "KURNOOL"              : ("KJB", "KJB", "South",  "Kurnool (Orvakal) Airport, Andhra Pradesh"),
    "MORADABAD AIRPORT"    : ("MZS", "MZS", "North",  "Moradabad Airport, opened August 2024"),
    "PAKYONG"              : ("PYG", "PYG", "Northeast", "Pakyong Airport, serves Gangtok, Sikkim"),
    "REWA"                 : ("REW", "REW", "Central", "Rewa Airport (Chorhata), Madhya Pradesh"),
    "SHRAVASTI AIRPORT"    : ("VSV", "VSV", "North",  "Shravasti Airport, opened March 2024"),
    "UTKELA"               : ("UKE", "UKE", "East",   "Utkela Airport, serves Bhawanipatna, Odisha"),
    "ZIRO"                 : ("ZER", "ZER", "Northeast", "Ziro Airport (officially 'Zero Airport'), "
                                                          "Arunachal Pradesh — DGCA table uses the town-name "
                                                          "spelling 'Ziro'; this was mistakenly keyed as 'ZERO' "
                                                          "(the airport's official name) in an earlier pass and "
                                                          "left unmapped as a result. Corrected here — same "
                                                          "airport, code ZER, verified against Wikipedia/AAI."),
    # MALVAN: Category B, but flagged here for extra scrutiny akin to the GOA
    # case before being added, since "Malvan" is a town name, not the
    # airport's own name (same class of naming gap as GOA/DABOLIM). Verified:
    # Malvan's only nearby commercial airport is Sindhudurg (Chipi) Airport,
    # IATA SDW, ~21km away, operated by Fly91. Cross-checked against the DGCA
    # rows themselves: the four "Malvan" pairs in this dataset (BENGALURU,
    # HYDERABAD, MUMBAI, PUNE) are EXACTLY Fly91's published Sindhudurg route
    # network — no other operational airport in India could produce this
    # specific route set. Unlike GOA, there is no second candidate airport
    # and no conflicting/duplicate DGCA entry under another name for the
    # same routes, so this is treated as an unambiguous match rather than a
    # guess.
    "MALVAN"               : ("SDW", "SDW", "West",  "Sindhudurg (Chipi) Airport — nearest/only commercial "
                                                       "airport to Malvan; route set cross-checked against "
                                                       "Fly91's published Sindhudurg network"),
}

# ─── Region assignment for cities not in CITY_TO_CODE ────────────────────────
REGION_FALLBACK = {
    "Northeast": ["AGARTALA","AIZAWL","DIMAPUR","DIBRUGARH","GUWAHATI","IMPHAL",
                  "JORHAT","LILABARI","PASIGHAT","RUPSI","SHILLONG","SILCHAR",
                  "TEZPUR","TEZU","ZIRO","ALONG","ITANAGAR","PAKYONG"],
    "North"    : ["DELHI","JAIPUR","SRINAGAR","LUCKNOW","AMRITSAR","VARANASI",
                  "CHANDIGARH","DEHRADUN","DEHRA DUN","AGRA","JAMMU","LEH",
                  "KULLU","SHIMLA","SIMLA","UDAIPUR","GWALIOR","GORAKHPUR","JODHPUR",
                  "JAISALMER","BIKANER","BAREILLY","KANPUR","PATNA","HINDON AIRPORT",
                  "ADAMPUR","PANTNAGAR","PITHORAGARH","ALLAHABAD","PRAYAGRAJ",
                  "BATHINDA","BHATINDA","LUDHIANA","KOTA","AYODHYA INTERNATIONAL AIRPORT",
                  "ALIGARH AIRPORT","AZAMGARH AIRPORT","CHITRAKOOT AIRPORT",
                  "MORADABAD AIRPORT","SHRAVASTI AIRPORT","KISHANGARH"],
    "West"     : ["MUMBAI","AHMEDABAD","PUNE","DABOLIM","GOA","SURAT","VADODARA",
                  "RAJKOT","AURANGABAD","SHIRDI","NASHIK","NASIK","NANDED",
                  "KOLHAPUR","BHAVNAGAR","JAMNAGAR","KANDLA","PORBANDAR","KESHOD",
                  "DIU","BHUJ","RAJKOT INTERNATIONAL AIRPORT","MALVAN"],
    "South"    : ["BENGALURU","HYDERABAD","CHENNAI","KOCHI","TRIVANDRUM",
                  "COIMBATORE","VISAKHAPATNAM","TIRUPATI","MANGALURU","MANGALORE","HUBLI",
                  "BELGAUM","MYSORE","CALICUT","KOZHIKODE","MADURAI","SALEM",
                  "TUTICORIN","TIRUCHIRAPPALLI","TIRUCHIRAPALLY","VIJAYAWADA","VIDYANAGAR",
                  "RAJAHMUNDRY","KALABURAGI","KURNOOL"],
    "East"     : ["KOLKATA","BHUBANESWAR","RANCHI","PATNA","BAGDOGRA","DURGAPUR",
                  "PORT BLAIR","GAYA","COOCH BEHAR","JAMSHEDPUR","JEYPORE","UTKELA"],
    "Central"  : ["NAGPUR","INDORE","RAIPUR","BHOPAL","JABALPUR","KHAJURAHO",
                  "AMBIKAPUR AIRPORT","GONDIA","JAGDALPUR","REWA"],
}


def get_region(city_std):
    """Return geographic region for a standardized city name, or 'Unknown'."""
    info = CITY_TO_CODE.get(city_std)
    if info:
        return info[2]
    for region, cities in REGION_FALLBACK.items():
        if city_std in cities:
            return region
    return "Unknown"


def get_iata_code(city_std):
    """
    Resolve a standardized city name to a verified IATA code.

    Returns (code, status):
      status == "MAPPED"           -> code is a verified, documented IATA code
      status == "FLAG_FOR_REVIEW"  -> code is None; city is unmapped or the
                                       mapped entry has no IATA code on file
                                       (e.g. a regional airstrip). Never
                                       fabricate a pseudo-code here.
    """
    info = CITY_TO_CODE.get(city_std)
    if info is None:
        return None, FLAG_FOR_REVIEW
    code = info[0]
    if not code:
        # Known city, but genuinely has no IATA code (e.g. SALASAR).
        return None, FLAG_FOR_REVIEW
    return code, "MAPPED"


def make_route_id(c1_std, c2_std):
    """
    Create canonical route_id using alphabetic ordering of verified IATA
    codes, e.g. BOM-DEL regardless of which city is city_1 in DGCA.

    If either city cannot be safely resolved to a verified IATA code,
    returns (FLAG_FOR_REVIEW, "FLAG_FOR_REVIEW") instead of guessing a
    pseudo-code from the city name. This must never silently enter the
    route basket.
    """
    code1, status1 = get_iata_code(c1_std)
    code2, status2 = get_iata_code(c2_std)

    if status1 == FLAG_FOR_REVIEW or status2 == FLAG_FOR_REVIEW:
        return FLAG_FOR_REVIEW, FLAG_FOR_REVIEW

    if code1 <= code2:
        return f"{code1}-{code2}", "MAPPED"
    else:
        return f"{code2}-{code1}", "MAPPED"


def classify_eligibility(df):
    """
    TASK B — Explicit, documented basket-eligibility rules.

    Adds two columns to df (does not drop or reorder any existing row):
      - basket_eligible   : bool
      - exclusion_reason  : "" if eligible, else a human-readable reason

    Rules applied, in order:
      1. SELF_PAIR            : city_1_standardized == city_2_standardized
      2. MISSING_DIRECTIONAL_DATA : conservative bidirectional total is NaN
         (i.e. at least one direction is DGCA_DASH / missing)
      3. UNMAPPED_CITY_CODE   : either city could not be resolved to a
         verified IATA code (route_id == FLAG_FOR_REVIEW)

    A row can have only one recorded reason (first applicable rule wins);
    this keeps the reason column simple while still being fully traceable.
    """
    reasons = []
    eligible = []

    for _, row in df.iterrows():
        c1 = row["city_1_standardized"]
        c2 = row["city_2_standardized"]

        if c1 == c2:
            reasons.append("SELF_PAIR: city_1_standardized == city_2_standardized")
            eligible.append(False)
            continue

        if pd.isna(row["conservative_total_bidirectional_passengers"]):
            reasons.append(
                "MISSING_DIRECTIONAL_DATA: at least one direction is "
                "DGCA_DASH/missing under the conservative treatment"
            )
            eligible.append(False)
            continue

        if row["route_id"] == FLAG_FOR_REVIEW:
            reasons.append(
                "UNMAPPED_CITY_CODE: one or both cities have no verified "
                "IATA mapping on file"
            )
            eligible.append(False)
            continue

        reasons.append("")
        eligible.append(True)

    df = df.copy()
    df["basket_eligible"]  = eligible
    df["exclusion_reason"] = reasons
    return df


def compute_totals(df):
    """
    DASH TREATMENT — Option C (transparent dual treatment).

    Adds two columns:
      - conservative_total_bidirectional_passengers:
          c1 + c2 if both directions present, else NaN.
          This is the ONLY total used for ranking/eligibility today.
      - zero_treated_total_bidirectional_passengers:
          DGCA_DASH/missing directions treated as 0.
          Exposed as a clearly-labelled analytical alternative only;
          NOT used for ranking or basket selection at this stage.
    """
    df = df.copy()
    c1 = df["passengers_city1_to_city2"]
    c2 = df["passengers_city2_to_city1"]

    df["conservative_total_bidirectional_passengers"] = df.apply(
        lambda r: r["passengers_city1_to_city2"] + r["passengers_city2_to_city1"]
        if pd.notna(r["passengers_city1_to_city2"]) and pd.notna(r["passengers_city2_to_city1"])
        else float("nan"),
        axis=1,
    )
    df["zero_treated_total_bidirectional_passengers"] = c1.fillna(0) + c2.fillna(0)

    return df


def load_and_rank():
    """
    Load DGCA CSV, compute dual totals, classify eligibility, resolve
    route_id/mapping_status, and rank by the conservative total.

    Returns:
        full_df : ALL 835 rows with totals/eligibility/mapping columns
                  (nothing dropped — self-pairs, DASH-affected, and
                  unmapped-city rows are retained and labelled).
        ranked  : eligible rows only, sorted by conservative total
                  descending, with rank + cumulative coverage columns.
        total_pax : sum of conservative totals across eligible rows.
    """
    df = pd.read_csv(DGCA_CSV)

    df = compute_totals(df)

    # Region + route_id/mapping_status computed for every row (not just
    # eligible ones) so the full dataset is fully labelled for review.
    df["region_city_1"] = df["city_1_standardized"].apply(get_region)
    df["region_city_2"] = df["city_2_standardized"].apply(get_region)

    route_ids = []
    mapping_statuses = []
    for _, row in df.iterrows():
        rid, status = make_route_id(row["city_1_standardized"], row["city_2_standardized"])
        route_ids.append(rid)
        mapping_statuses.append(status)
    df["route_id"] = route_ids
    df["mapping_status"] = mapping_statuses

    df = classify_eligibility(df)

    eligible = df[df["basket_eligible"]].copy()
    eligible = eligible.sort_values(
        "conservative_total_bidirectional_passengers", ascending=False
    ).reset_index(drop=True)
    eligible["rank"] = eligible.index + 1

    total_pax = eligible["conservative_total_bidirectional_passengers"].sum()
    eligible["cumulative_pax"] = eligible["conservative_total_bidirectional_passengers"].cumsum()
    eligible["cumulative_pct"] = eligible["cumulative_pax"] / total_pax * 100

    return df, eligible, total_pax


def save_ranking(ranked):
    """
    TASK C — Save the full route traffic ranking CSV WITHOUT a global
    float_format. Integer-valued passenger/pax columns are cast to
    pandas nullable Int64 so they render as exact integers; the
    cumulative coverage percentage retains 4 decimal places.
    """
    out = ranked[[
        "rank", "city_1_standardized", "city_2_standardized", "route_id",
        "mapping_status",
        "passengers_city1_to_city2", "passengers_city2_to_city1",
        "conservative_total_bidirectional_passengers",
        "zero_treated_total_bidirectional_passengers",
        "cumulative_pct",
        "region_city_1", "region_city_2",
        "original_city_1", "original_city_2",
    ]].copy()

    out.columns = [
        "rank", "city_1", "city_2", "route_id", "mapping_status",
        "passengers_city1_to_city2", "passengers_city2_to_city1",
        "conservative_total_bidirectional_passengers",
        "zero_treated_total_bidirectional_passengers",
        "cumulative_coverage_pct",
        "region_city_1", "region_city_2",
        "original_city_1_dgca", "original_city_2_dgca",
    ]

    # Exact integers for passenger/pax columns (nullable to tolerate any
    # residual NaN, though eligible rows should have none by construction).
    int_cols = [
        "passengers_city1_to_city2", "passengers_city2_to_city1",
        "conservative_total_bidirectional_passengers",
        "zero_treated_total_bidirectional_passengers",
    ]
    for col in int_cols:
        out[col] = out[col].round(0).astype("Int64")

    # Preserve decimal precision on the coverage percentage explicitly,
    # independent of any other column's formatting.
    out["cumulative_coverage_pct"] = out["cumulative_coverage_pct"].round(4)

    out.to_csv(RANKING_CSV, index=False)
    print(f"[OK] Ranking CSV saved -> {RANKING_CSV}")


def save_excluded_report(full_df):
    """
    Write a companion CSV listing every row excluded from basket
    eligibility, with its explicit exclusion reason. Nothing here is
    deleted from the source dataset — this is a transparency artifact.
    """
    excluded = full_df[~full_df["basket_eligible"]][[
        "record_id", "original_city_1", "original_city_2",
        "city_1_standardized", "city_2_standardized",
        "route_id", "mapping_status", "exclusion_reason",
    ]].copy()
    path = os.path.join(OUT_DIR, "dgca_route_exclusions.csv")
    excluded.to_csv(path, index=False)
    print(f"[OK] Exclusions report saved -> {path}")
    return excluded


def basket_size_analysis(ranked, total_pax):
    """Return comparison table for candidate basket sizes. (Diagnostic only —
    not basket selection.)"""
    rows = []
    for n in [5, 10, 15, 20]:
        top_n = ranked.head(n)
        cities = set(top_n["city_1_standardized"]) | set(top_n["city_2_standardized"])
        regions = set(top_n["region_city_1"]) | set(top_n["region_city_2"])
        cov = top_n["conservative_total_bidirectional_passengers"].sum() / total_pax * 100
        metros = {"DELHI","MUMBAI","BENGALURU","HYDERABAD","CHENNAI","KOLKATA"}
        metro_cities = cities & metros
        rows.append({
            "basket_size"       : n,
            "cumulative_pax_pct": round(cov, 2),
            "distinct_cities"   : len(cities),
            "regions_covered"   : len(regions),
            "metro_cities"      : len(metro_cities),
            "metro_city_names"  : ", ".join(sorted(metro_cities)),
            "regions"           : ", ".join(sorted(regions)),
        })
    return pd.DataFrame(rows)


# ─── Option A: Pure traffic-ranked top-15 ────────────────────────────────────
# NOT executed by default in this pass — see main(). Retained here so the
# basket-selection methodology from the prior version is preserved and can
# be re-run once explicitly approved.
OPTION_A_SIZE = 15
BASKET_TOP_K = 10
BASKET_TARGET_SIZE = 15
ALL_REGIONS = set(REGION_FALLBACK.keys())  # {"North","South","East","West","Central","Northeast"}


def select_diversified_basket(ranked, top_k=BASKET_TOP_K, target_size=BASKET_TARGET_SIZE):
    """
    VAYU-Basket-Rule-v1 — approved methodology, implemented exactly as
    specified (no manual route list, no hardcoded exceptions):

      1. Include the top `top_k` routes by conservative bidirectional
         passenger traffic unconditionally.
      2. STAGE 1 (region gap-filling): scan the remaining routes in
         descending traffic-rank order. Add a route if and only if it
         introduces at least one region not yet represented in the basket.
         Continue until all regions in ALL_REGIONS are represented.
      3. STAGE 2 (city gap-filling): continue scanning in descending
         traffic-rank order. Add a route if and only if it introduces at
         least one city not yet represented in the basket. Stop once the
         basket reaches `target_size`.

    Deterministic and reproducible: given the same ranked DGCA table, this
    always returns the same basket. No route is chosen by name — only by
    rank position and the region/city-novelty test above.

    Returns a DataFrame of the selected rows from `ranked`, in the order
    they were added (Top-K first, then Stage 1, then Stage 2), each
    annotated with a `selection_stage` and `selection_reason` column
    describing WHY it was picked (for transparency only — not used to
    influence selection).
    """
    selected_rows = []
    selected_ranks = set()
    cities_in_basket = set()
    regions_in_basket = set()

    top_k_df = ranked.head(top_k)
    for _, r in top_k_df.iterrows():
        selected_rows.append((r, "TOP_K", f"Rank {int(r['rank'])} — unconditional top-{top_k} by conservative traffic"))
        selected_ranks.add(int(r["rank"]))
        cities_in_basket.add(r["city_1_standardized"])
        cities_in_basket.add(r["city_2_standardized"])
        regions_in_basket.add(get_region(r["city_1_standardized"]))
        regions_in_basket.add(get_region(r["city_2_standardized"]))

    remaining = ranked.iloc[top_k:]
    missing_regions = ALL_REGIONS - regions_in_basket

    # STAGE 1: region gap-filling, descending rank order
    if missing_regions:
        for _, r in remaining.iterrows():
            if not missing_regions:
                break
            reg1 = get_region(r["city_1_standardized"])
            reg2 = get_region(r["city_2_standardized"])
            new_regions = {reg1, reg2} & missing_regions
            if new_regions:
                selected_rows.append((
                    r, "STAGE1_REGION",
                    f"Rank {int(r['rank'])} — introduces region(s) {sorted(new_regions)}, "
                    f"the highest-ranked route to do so"
                ))
                selected_ranks.add(int(r["rank"]))
                cities_in_basket.add(r["city_1_standardized"])
                cities_in_basket.add(r["city_2_standardized"])
                regions_in_basket.add(reg1)
                regions_in_basket.add(reg2)
                missing_regions -= new_regions

    # STAGE 2: city gap-filling, descending rank order, until target size
    for _, r in remaining.iterrows():
        if len(selected_rows) >= target_size:
            break
        if int(r["rank"]) in selected_ranks:
            continue
        c1, c2 = r["city_1_standardized"], r["city_2_standardized"]
        new_cities = {c1, c2} - cities_in_basket
        if new_cities:
            selected_rows.append((
                r, "STAGE2_CITY",
                f"Rank {int(r['rank'])} — introduces city(ies) {sorted(new_cities)}, "
                f"the highest-ranked remaining route to do so"
            ))
            selected_ranks.add(int(r["rank"]))
            cities_in_basket.update(new_cities)

    if len(selected_rows) != target_size:
        raise ValueError(
            f"VAYU-Basket-Rule-v1 produced {len(selected_rows)} routes, "
            f"expected exactly {target_size}. Refusing to proceed silently."
        )

    out_rows = []
    for basket_rank, (r, stage, reason) in enumerate(selected_rows, 1):
        out_rows.append({
            "basket_rank"                    : basket_rank,
            "traffic_rank"                   : int(r["rank"]),
            "route_id"                       : r["route_id"],
            "city_1"                         : r["city_1_standardized"],
            "city_2"                         : r["city_2_standardized"],
            "original_city_1_dgca"           : r["original_city_1"],
            "original_city_2_dgca"           : r["original_city_2"],
            "passengers_city1_to_city2"      : r["passengers_city1_to_city2"],
            "passengers_city2_to_city1"      : r["passengers_city2_to_city1"],
            "total_bidirectional_passengers" : r["conservative_total_bidirectional_passengers"],
            "zero_treated_total_bidirectional_passengers": r["zero_treated_total_bidirectional_passengers"],
            "region_city_1"                  : get_region(r["city_1_standardized"]),
            "region_city_2"                  : get_region(r["city_2_standardized"]),
            "selection_stage"                : stage,
            "selection_reason"               : reason,
        })
    basket_df = pd.DataFrame(out_rows).sort_values("traffic_rank").reset_index(drop=True)
    basket_df["basket_rank"] = range(1, len(basket_df) + 1)
    return basket_df


def build_option_a(ranked):
    """Build Option A basket – pure top-15 by traffic.
    NOT executed by default in this pass — see main()."""
    top15 = ranked.head(OPTION_A_SIZE).copy()
    top15 = top15.reset_index(drop=True)
    top15.insert(0, "basket_rank", top15.index + 1)
    top15["traffic_rank"] = top15["rank"]
    top15["selection_reason"] = "Pure traffic rank"
    top15["original_city_1_dgca"] = top15["original_city_1"]
    top15["original_city_2_dgca"] = top15["original_city_2"]
    top15["total_bidirectional_passengers"] = top15["conservative_total_bidirectional_passengers"]
    return top15[[
        "basket_rank","traffic_rank","route_id",
        "city_1_standardized","city_2_standardized",
        "original_city_1_dgca","original_city_2_dgca",
        "passengers_city1_to_city2","passengers_city2_to_city1",
        "total_bidirectional_passengers",
        "region_city_1","region_city_2",
        "selection_reason",
    ]].rename(columns={
        "city_1_standardized": "city_1",
        "city_2_standardized": "city_2",
    })


def compute_weights(basket_df):
    """Add traffic_weight column (full-precision, traffic-proportional,
    sums to 1.0 in floating point)."""
    total = basket_df["total_bidirectional_passengers"].sum()
    basket_df = basket_df.copy()
    basket_df["traffic_weight"] = basket_df["total_bidirectional_passengers"] / total
    return basket_df, total


PUBLICATION_PRECISION = 6  # decimal places for published traffic_weight


def apply_publication_rounding(basket_weighted, decimals=PUBLICATION_PRECISION):
    """
    Deterministic publication-rounding rule for exported weights.

    Problem: independently rounding each full-precision weight to
    `decimals` places does not generally sum to exactly 1.0 (observed:
    15 weights rounded to 6dp summed to 1.000001 for this basket).

    Rule (documented, not silently applied):
      1. Keep full-precision weights in `traffic_weight_full_precision`.
      2. Round every weight independently to `decimals` places ->
         `traffic_weight`.
      3. Compute the residual: 1.0 - sum(rounded weights), at `decimals`
         resolution (i.e. residual is an integer multiple of 10**-decimals
         once rounding error is accounted for).
      4. Add the entire residual to exactly ONE route: the route with the
         LARGEST full-precision weight (ties broken by lowest basket_rank,
         which does not occur in this basket since all traffic values are
         distinct). This route is chosen because it is the least visually
         or proportionally distorted by an adjustment of this magnitude
         (10^-6 scale) relative to its own weight.
      5. The adjusted route's published weight is the only one that does
         NOT equal its independently-rounded value; this is documented
         explicitly in the metadata and methodology doc, not hidden.

    Returns a copy of basket_weighted with:
      - traffic_weight_full_precision : the exact route_pax/basket_total value
      - traffic_weight                : the published, residual-adjusted value
      - weight_residual_applied       : the signed adjustment applied to this
                                         row (0.0 for all rows except the one
                                         adjusted)
    """
    df = basket_weighted.copy()
    df["traffic_weight_full_precision"] = df["traffic_weight"]

    rounded = df["traffic_weight_full_precision"].round(decimals)
    residual = round(1.0 - rounded.sum(), decimals + 6)  # guard against fp noise

    df["traffic_weight"] = rounded
    df["weight_residual_applied"] = 0.0

    if residual != 0:
        # Deterministic target: largest full-precision weight, tie-break by
        # lowest basket_rank (stable, reproducible, no randomness).
        target_idx = df.sort_values(
            ["traffic_weight_full_precision", "basket_rank"],
            ascending=[False, True],
        ).index[0]
        df.loc[target_idx, "traffic_weight"] = round(
            df.loc[target_idx, "traffic_weight"] + residual, decimals
        )
        df.loc[target_idx, "weight_residual_applied"] = residual

    published_sum = df["traffic_weight"].sum()
    if abs(published_sum - 1.0) > 1e-9:
        raise ValueError(
            f"Publication rounding failed to reach exact 1.0 (got {published_sum!r}). "
            f"Refusing to export."
        )

    return df


def save_basket(basket_weighted, total_pax):
    """Save the approved VAYU route basket CSV, with publication-rounded
    weights that sum to exactly 1.0 (see apply_publication_rounding)."""
    published = apply_publication_rounding(basket_weighted)

    out = published[[
        "basket_rank", "traffic_rank", "route_id", "city_1", "city_2",
        "passengers_city1_to_city2", "passengers_city2_to_city1",
        "total_bidirectional_passengers",
        "zero_treated_total_bidirectional_passengers",
        "traffic_weight", "traffic_weight_full_precision", "weight_residual_applied",
        "region_city_1", "region_city_2",
        "selection_stage", "selection_reason",
    ]].copy()
    out["selection_method"] = "VAYU-Basket-Rule-v1"
    out["dgca_financial_year"] = FINANCIAL_YEAR

    # Exact integers for passenger/pax columns; weights get full precision.
    for col in ["passengers_city1_to_city2", "passengers_city2_to_city1",
                "total_bidirectional_passengers",
                "zero_treated_total_bidirectional_passengers"]:
        out[col] = out[col].round(0).astype("Int64")
    out["traffic_weight"] = out["traffic_weight"].round(PUBLICATION_PRECISION)
    out["traffic_weight_full_precision"] = out["traffic_weight_full_precision"].round(10)
    out["weight_residual_applied"] = out["weight_residual_applied"].round(PUBLICATION_PRECISION)

    out.to_csv(BASKET_CSV, index=False)
    print(f"[OK] Basket CSV saved -> {BASKET_CSV}")

    # Verify the CSV as written (round-trip), not just the in-memory frame.
    reread = pd.read_csv(BASKET_CSV)
    reread_sum = reread["traffic_weight"].sum()
    print(f"[CHECK] traffic_weight sum after re-reading CSV: {reread_sum:.6f}")
    if abs(reread_sum - 1.0) > 1e-9:
        raise ValueError(
            f"Exported CSV weight sum is {reread_sum!r}, not 1.0 within tolerance. "
            f"Refusing to treat this as a valid export."
        )


def save_basket_metadata(basket_weighted, total_pax):
    """Save route_basket_metadata.json for the approved VAYU basket.
    Uses the same publication-rounded, residual-adjusted weights as the
    exported CSV so the two artifacts never disagree."""
    published = apply_publication_rounding(basket_weighted)

    routes = []
    for _, r in published.iterrows():
        routes.append({
            "basket_rank"                : int(r["basket_rank"]),
            "traffic_rank"               : int(r["traffic_rank"]),
            "route_id"                   : r["route_id"],
            "city_1"                     : r["city_1"],
            "city_2"                     : r["city_2"],
            "region_city_1"              : r["region_city_1"],
            "region_city_2"              : r["region_city_2"],
            "total_bidirectional_passengers": int(r["total_bidirectional_passengers"]),
            "traffic_weight"             : round(float(r["traffic_weight"]), PUBLICATION_PRECISION),
            "traffic_weight_full_precision": round(float(r["traffic_weight_full_precision"]), 10),
            "weight_residual_applied"    : round(float(r["weight_residual_applied"]), PUBLICATION_PRECISION),
            "selection_stage"            : r["selection_stage"],
            "selection_reason"           : r["selection_reason"],
        })

    basket_pax = int(published["total_bidirectional_passengers"].sum())
    cities = set(published["city_1"]) | set(published["city_2"])
    regions = set(published["region_city_1"]) | set(published["region_city_2"])
    delhi_routes = int(((published["city_1"] == "DELHI") | (published["city_2"] == "DELHI")).sum())
    mumbai_routes = int(((published["city_1"] == "MUMBAI") | (published["city_2"] == "MUMBAI")).sum())
    adjusted_route = published.loc[published["weight_residual_applied"] != 0, "route_id"]
    adjusted_route_id = adjusted_route.iloc[0] if len(adjusted_route) else None

    meta = {
        "source"                : "Directorate General of Civil Aviation (DGCA)",
        "dataset"               : "City Pair Wise Scheduled Domestic Passenger Traffic Statistics",
        "financial_year"        : FINANCIAL_YEAR,
        "basket_label"          : "VAYU prototype route basket derived from DGCA 2024-25 traffic data",
        "selection_method"      : "VAYU-Basket-Rule-v1",
        "selection_rule"        : (
            f"1) Top {BASKET_TOP_K} routes by conservative bidirectional passenger "
            f"traffic, unconditionally. 2) Scanning remaining routes in descending "
            f"traffic rank, add the first route introducing each missing region "
            f"until all 6 regions (North, South, East, West, Central, Northeast) "
            f"are represented. 3) Continue scanning in descending rank, adding "
            f"routes that introduce a previously-unseen city, until the basket "
            f"reaches {BASKET_TARGET_SIZE} routes. Deterministic and reproducible "
            f"given the same ranked DGCA table — no route was chosen manually."
        ),
        "basket_size"           : int(len(published)),
        "basket_pax"            : basket_pax,
        "basket_pax_coverage_pct": round(basket_pax / total_pax * 100, 4),
        "distinct_cities"       : len(cities),
        "distinct_regions"      : len(regions),
        "regions_represented"   : sorted(regions),
        "delhi_route_count"     : delhi_routes,
        "delhi_route_pct"       : round(delhi_routes / len(published) * 100, 2),
        "mumbai_route_count"    : mumbai_routes,
        "mumbai_route_pct"      : round(mumbai_routes / len(published) * 100, 2),
        "weight_formula"        : "route_conservative_total_bidir_pax / sum(all_basket_routes_conservative_bidir_pax)",
        "weight_publication_precision": PUBLICATION_PRECISION,
        "weight_rounding_rule" : (
            f"Each route's full-precision weight is rounded independently to "
            f"{PUBLICATION_PRECISION} decimal places for publication. Because "
            f"independent rounding of {len(published)} weights does not "
            f"generally sum to exactly 1.0, any residual (post-rounding sum "
            f"minus 1.0) is added to the single route with the largest "
            f"full-precision weight (ties broken by lowest basket_rank), so "
            f"published weights sum to exactly 1.0. Full-precision values are "
            f"preserved in traffic_weight_full_precision for anyone who needs "
            f"the unadjusted figure."
        ),
        "weight_residual_adjusted_route": adjusted_route_id,
        "weight_sum"            : round(float(published["traffic_weight"].sum()), 8),
        "routes"                : routes,
        "dash_treatment"        : (
            "Conservative treatment used for ranking, eligibility, and weighting: "
            "a route is only eligible if BOTH directional passenger values are "
            "present (no DGCA_DASH in either direction). The zero-treated "
            "alternative total (DGCA_DASH treated as 0) is preserved in the "
            "ranking export and in this basket's routes list purely as a "
            "documented analytical alternative — it was NOT used to select "
            "routes, rank routes, or compute traffic_weight."
        ),
        "goa_dabolim_note"      : (
            "The DGCA-standardized city name 'GOA' remains deliberately "
            "unmapped (FLAG_FOR_REVIEW) because Goa has had two separate, "
            "currently-operating airports since Jan 2023 (Dabolim/GOI and "
            "Manohar Intl-Mopa/GOX) and DGCA's 'GOA' vs 'DABOLIM' rows carry "
            "materially different passenger counts, consistent with them "
            "being genuinely different airports. This basket contains no "
            "route using the ambiguous 'GOA' entry."
        ),
        "what_this_is_not"      : [
            "NOT an official MoSPI basket",
            "NOT official CPI route weights",
            "NOT endorsed by DGCA or any government body",
            "NOT final - weights will update when newer DGCA traffic data is published",
        ],
        "created_timestamp"     : datetime.now(timezone.utc).isoformat(),
    }
    with open(BASKET_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"[OK] Basket metadata saved -> {BASKET_META}")


def save_methodology_doc(basket_weighted, total_pax):
    """Write docs/route_basket_methodology.md documenting VAYU-Basket-Rule-v1
    and the resulting approved basket, using the same publication-rounded
    weights as the exported CSV/metadata."""
    published = apply_publication_rounding(basket_weighted)
    cities = sorted(set(published["city_1"]) | set(published["city_2"]))
    regions = sorted(set(published["region_city_1"]) | set(published["region_city_2"]))
    basket_pax = int(published["total_bidirectional_passengers"].sum())
    coverage_pct = basket_pax / total_pax * 100
    delhi_routes = int(((published["city_1"] == "DELHI") | (published["city_2"] == "DELHI")).sum())
    mumbai_routes = int(((published["city_1"] == "MUMBAI") | (published["city_2"] == "MUMBAI")).sum())
    basket_weighted = published  # rest of function reads from `published` values below

    lines = []
    lines.append("# VAYU Route Basket Methodology\n")
    lines.append(f"**Financial year:** {FINANCIAL_YEAR}  ")
    lines.append(f"**Selection method:** VAYU-Basket-Rule-v1  ")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n")

    lines.append("## Provenance\n")
    lines.append("| Layer | Status |")
    lines.append("|---|---|")
    lines.append("| DGCA passenger counts, route ranks | Official DGCA 2024-25 data |")
    lines.append("| VAYU-Basket-Rule-v1 (the selection rule) | VAYU design choice, not an official MoSPI/DGCA rule |")
    lines.append("| The specific 15 routes selected | VAYU basket selection, deterministically derived from the rule above |")
    lines.append("| traffic_weight values | Derived VAYU weights — traffic-proportional by construction, not officially endorsed |\n")

    lines.append("## VAYU-Basket-Rule-v1\n")
    lines.append(f"1. Include the top {BASKET_TOP_K} routes by **conservative** bidirectional "
                  "passenger traffic unconditionally.")
    lines.append("2. **Stage 1 (region gap-filling):** scan remaining routes in descending "
                  "traffic-rank order. Add a route if and only if it introduces a region "
                  "(of North/South/East/West/Central/Northeast) not yet in the basket. "
                  "Continue until all 6 regions are represented.")
    lines.append(f"3. **Stage 2 (city gap-filling):** continue scanning in descending rank "
                  f"order. Add a route if and only if it introduces a city not yet in the "
                  f"basket. Stop at {BASKET_TARGET_SIZE} routes.\n")
    lines.append("This rule is deterministic and reproducible: given the same ranked DGCA "
                  "table, any analyst re-running it gets the same 15 routes. No route was "
                  "chosen by name.\n")

    lines.append("## DASH treatment\n")
    lines.append("Conservative bidirectional traffic (both directions present, no "
                  "DGCA_DASH) is used for ranking, eligibility, and `traffic_weight`. "
                  "The zero-treated alternative (DGCA_DASH treated as 0) is preserved "
                  "in outputs purely as a documented analytical alternative and was not "
                  "used for selection or weighting.\n")

    lines.append("## GOA / DABOLIM\n")
    lines.append("The DGCA-standardized name `GOA` remains deliberately unmapped "
                  "(`FLAG_FOR_REVIEW`) — Goa has had two separate operating airports "
                  "since Jan 2023 (Dabolim/GOI, Manohar Intl-Mopa/GOX) and DGCA's `GOA` "
                  "vs `DABOLIM` rows carry materially different passenger counts. This "
                  "basket uses only the unambiguous `DABOLIM` (GOI) entries.\n")

    lines.append("## Publication weight precision and rounding rule\n")
    adjusted_route = published.loc[published["weight_residual_applied"] != 0, "route_id"]
    adjusted_route_id = adjusted_route.iloc[0] if len(adjusted_route) else "none"
    lines.append(f"Published `traffic_weight` values are rounded to "
                  f"{PUBLICATION_PRECISION} decimal places. Because independently "
                  f"rounding {len(published)} weights does not generally sum to "
                  f"exactly 1.0, any rounding residual is added to the single route "
                  f"with the largest full-precision weight (ties broken by lowest "
                  f"basket_rank) — for this basket, that route is **{adjusted_route_id}**. "
                  f"The unadjusted, full-precision weight for every route is preserved "
                  f"in `traffic_weight_full_precision` in the exported CSV and metadata, "
                  f"so the adjustment is fully auditable rather than hidden.\n")

    lines.append("## Approved basket\n")
    lines.append("| Basket Rank | Traffic Rank | Route | route_id | Bidirectional Pax | Weight | Stage |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, r in basket_weighted.iterrows():
        lines.append(
            f"| {int(r['basket_rank'])} | {int(r['traffic_rank'])} | "
            f"{r['city_1']}\u2013{r['city_2']} | {r['route_id']} | "
            f"{int(r['total_bidirectional_passengers']):,} | "
            f"{r['traffic_weight']*100:.2f}% | {r['selection_stage']} |"
        )
    lines.append("")

    lines.append("## Coverage and concentration statistics\n")
    lines.append(f"- Total basket traffic: {basket_pax:,} pax")
    lines.append(f"- Coverage of all eligible DGCA traffic: {coverage_pct:.2f}%")
    lines.append(f"- Distinct cities: {len(cities)} — {', '.join(cities)}")
    lines.append(f"- Distinct regions: {len(regions)} — {', '.join(regions)}")
    lines.append(f"- Delhi appears in {delhi_routes}/{len(basket_weighted)} routes "
                  f"({delhi_routes/len(basket_weighted)*100:.1f}%)")
    lines.append(f"- Mumbai appears in {mumbai_routes}/{len(basket_weighted)} routes "
                  f"({mumbai_routes/len(basket_weighted)*100:.1f}%)")
    lines.append(f"- Weight sum (verification): {basket_weighted['traffic_weight'].sum():.6f}\n")

    lines.append("## What this basket is NOT\n")
    lines.append("- NOT an official MoSPI basket")
    lines.append("- NOT official CPI route weights")
    lines.append("- NOT endorsed by DGCA or any government body")
    lines.append("- NOT final — weights will update when newer DGCA traffic data is published\n")

    with open(METHODOLOGY, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] Methodology doc saved -> {METHODOLOGY}")


def print_integrity_summary(full_df, ranked, total_pax):
    sep = "=" * 78
    print(f"\n{sep}")
    print("  PHASE 5 DATA-INTEGRITY SUMMARY")
    print(sep)
    print(f"  Total DGCA rows loaded          : {len(full_df)}")
    print(f"  Eligible for ranking (conservative): {len(ranked)}")

    self_pairs = full_df[full_df["exclusion_reason"].str.startswith("SELF_PAIR")]
    missing_dir = full_df[full_df["exclusion_reason"].str.startswith("MISSING_DIRECTIONAL_DATA")]
    unmapped = full_df[full_df["exclusion_reason"].str.startswith("UNMAPPED_CITY_CODE")]

    print(f"  Excluded - self-pairs           : {len(self_pairs)}")
    print(f"  Excluded - missing directional  : {len(missing_dir)}")
    print(f"  Excluded - unmapped city code   : {len(unmapped)}")

    flagged_cities = sorted(set(
        full_df.loc[full_df["mapping_status"] == FLAG_FOR_REVIEW, "city_1_standardized"]
    ) | set(
        full_df.loc[full_df["mapping_status"] == FLAG_FOR_REVIEW, "city_2_standardized"]
    ) - {c for c in CITY_TO_CODE})
    # The above line is defensive; recompute directly from flagged rows below.
    flagged_rows = full_df[full_df["mapping_status"] == FLAG_FOR_REVIEW]
    flagged_city_names = set()
    for _, r in flagged_rows.iterrows():
        if get_iata_code(r["city_1_standardized"])[1] == FLAG_FOR_REVIEW:
            flagged_city_names.add(r["city_1_standardized"])
        if get_iata_code(r["city_2_standardized"])[1] == FLAG_FOR_REVIEW:
            flagged_city_names.add(r["city_2_standardized"])

    print(f"  Distinct unmapped city names    : {len(flagged_city_names)}")
    print(f"  Total eligible conservative pax : {int(total_pax):,}")
    print(sep + "\n")

    return flagged_city_names


def verify_basket(basket_weighted, ranked):
    """
    Run all the explicit verification checks requested before reporting
    the basket as complete. Raises AssertionError with a clear message on
    any failure — this function must never silently pass a broken basket.
    """
    checks = []

    # 1. Exactly 15 routes
    checks.append(("Basket contains exactly 15 routes", len(basket_weighted) == 15))

    # 2. All routes exist in the DGCA ranked data (by route_id)
    ranked_ids = set(ranked["route_id"])
    all_in_ranked = set(basket_weighted["route_id"]).issubset(ranked_ids)
    checks.append(("All basket routes exist in ranked DGCA data", all_in_ranked))

    # 3. No duplicate route_ids
    no_dupes = basket_weighted["route_id"].duplicated().sum() == 0
    checks.append(("No duplicate route_ids in basket", no_dupes))

    # 4. Weights non-negative
    non_negative = (basket_weighted["traffic_weight"] >= 0).all()
    checks.append(("All weights non-negative", non_negative))

    # 5. Weights sum to 1.0 within tolerance
    weight_sum = basket_weighted["traffic_weight"].sum()
    sum_ok = abs(weight_sum - 1.0) < 1e-6
    checks.append((f"Weights sum to 1.000000 (actual: {weight_sum:.8f})", sum_ok))

    # 6. All 6 regions represented
    regions = set(basket_weighted["region_city_1"]) | set(basket_weighted["region_city_2"])
    all_regions_ok = ALL_REGIONS.issubset(regions)
    checks.append((f"All 6 regions represented (found: {sorted(regions)})", all_regions_ok))

    # 7. Reproducibility: re-run the rule and confirm identical result
    rerun = select_diversified_basket(ranked)
    reproducible = list(rerun["route_id"]) == list(basket_weighted.sort_values("basket_rank")["route_id"])
    checks.append(("Basket selection is reproducible (re-run matches)", reproducible))

    print("\n" + "=" * 78)
    print("  BASKET VERIFICATION")
    print("=" * 78)
    all_passed = True
    for desc, passed in checks:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {desc}")
        if not passed:
            all_passed = False
    print("=" * 78)

    if not all_passed:
        raise AssertionError("One or more basket verification checks failed — see log above.")

    return all_passed


def main():
    print("[START] Phase 5 - approved route basket + traffic weights (VAYU-Basket-Rule-v1)")

    full_df, ranked, total_pax = load_and_rank()

    flagged_city_names = print_integrity_summary(full_df, ranked, total_pax)

    save_ranking(ranked)
    save_excluded_report(full_df)

    print("[INFO] Unmapped city names (deliberately excluded from basket eligibility):")
    for name in sorted(flagged_city_names):
        print(f"    - {name}")

    # ── Build the approved basket ──────────────────────────────────────────
    basket = select_diversified_basket(ranked)
    basket_weighted, basket_total_pax = compute_weights(basket)

    verify_basket(basket_weighted, ranked)

    save_basket(basket_weighted, total_pax)
    save_basket_metadata(basket_weighted, total_pax)
    save_methodology_doc(basket_weighted, total_pax)

    print(f"\n[DONE] Phase 5 route basket complete.")
    print(f"  {RANKING_CSV}")
    print(f"  {os.path.join(OUT_DIR, 'dgca_route_exclusions.csv')}")
    print(f"  {BASKET_CSV}")
    print(f"  {BASKET_META}")
    print(f"  {METHODOLOGY}")

    return full_df, ranked, total_pax, basket_weighted, basket_total_pax


if __name__ == "__main__":
    main()
