"""Check SerpApi account/key access without spending a Google Flights search."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ACCOUNT_URL = "https://serpapi.com/account.json"
SAFE_FIELDS = (
    "account_status",
    "plan_name",
    "plan_searches_left",
    "total_searches_left",
    "this_month_usage",
    "account_rate_limit_per_hour",
)


def _clean_key(val: str) -> str:
    """Safely remove zero-width unicode characters, outer quotes, and surrounding whitespace."""
    return re.sub(r"[\u200B-\u200D\uFEFF]", "", val).strip(" \t\r\n").strip("'\"")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify SerpApi account status and key validity without consuming search credits."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Attempt the HTTP request to SerpApi even if format validation fails.",
    )
    args = parser.parse_args()

    # 1. Check process environment first (standard 12-factor precedence)
    raw_env_key = os.environ.get("SERPAPI_API_KEY", "")
    cleaned_env_key = _clean_key(raw_env_key)

    key_to_test = ""
    key_source = ""

    if cleaned_env_key:
        key_to_test = cleaned_env_key
        key_source = "process environment variable ($env:SERPAPI_API_KEY)"
    else:
        # Fallback to local .env file only if not set in process environment
        repo_root = Path(__file__).resolve().parents[1]
        for env_path in [Path(".env"), repo_root / ".env"]:
            if env_path.is_file():
                try:
                    for line in env_path.read_text(encoding="utf-8").splitlines():
                        stripped = line.strip()
                        if stripped.startswith("SERPAPI_API_KEY="):
                            env_val = _clean_key(stripped.split("=", 1)[1])
                            if env_val:
                                key_to_test = env_val
                                key_source = f"local file ({env_path.name})"
                                break
                except OSError:
                    pass
            if key_to_test:
                break

    if not key_to_test:
        print("SERPAPI_API_KEY is not set (or is empty) in this terminal session and not found in .env.", file=sys.stderr)
        print("Note: In Windows PowerShell, $env:SERPAPI_API_KEY is process-local and only exists in the specific terminal window where it was set.", file=sys.stderr)
        print("To set it in your current PowerShell session:", file=sys.stderr)
        print("  $env:SERPAPI_API_KEY = (Get-Clipboard -Raw).Trim()", file=sys.stderr)
        return 2

    # Check for 64-hex key format
    match_64 = re.search(r"([0-9a-fA-F]{64})", key_to_test)
    if match_64:
        api_key = match_64.group(1)
        if len(key_to_test) != 64:
            print(f"Notice: Extracted 64-hex API key from {key_source} (surrounding parameter or text stripped).")
        else:
            print(f"Key loaded from {key_source}: 64-hex format verified.")
    else:
        api_key = key_to_test
        key_len = len(key_to_test)
        is_hex = bool(re.fullmatch(r"[0-9a-fA-F]+", key_to_test))

        print(f"Key format check: FAILED (Loaded from {key_source})", file=sys.stderr)
        print(f"  Length: {key_len} characters (expected: exactly 64 hexadecimal characters)", file=sys.stderr)
        print(f"  Hexadecimal: {'Yes' if is_hex else 'No (contains non-hex characters)'}", file=sys.stderr)

        if key_len == 50:
            print("\nDIAGNOSIS: The key is exactly 50 characters long.", file=sys.stderr)
            print("  In the SerpApi dashboard (https://serpapi.com/manage-api-key), the visible text box", file=sys.stderr)
            print("  only displays ~50 characters before truncating. Highlighting or double-clicking the", file=sys.stderr)
            print("  input field with the mouse copies only the visible 50 characters instead of the full key.", file=sys.stderr)
            print("\nSAFE NEXT STEPS:", file=sys.stderr)
            print("  1. Open https://serpapi.com/manage-api-key in your browser.", file=sys.stderr)
            print("  2. Click the dedicated 'Copy' button (clipboard icon) next to the API key field.", file=sys.stderr)
            print("     Do NOT highlight or drag over the text box.", file=sys.stderr)
            print("  3. In your active PowerShell terminal, run:", file=sys.stderr)
            print("     $env:SERPAPI_API_KEY = (Get-Clipboard -Raw).Trim()", file=sys.stderr)
            print("  4. Verify the length in PowerShell:", file=sys.stderr)
            print("     if ($env:SERPAPI_API_KEY -match '^[0-9A-Fa-f]{64}$') { 'Key format OK (64 characters)' } else { \"Key format invalid: $($env:SERPAPI_API_KEY.Length) characters. Copy again.\" }", file=sys.stderr)
            print("  5. Re-run this check: python scripts/check_serpapi_account.py", file=sys.stderr)
        elif key_len < 64:
            print(f"\nDIAGNOSIS: The key appears truncated ({key_len} < 64 characters).", file=sys.stderr)
            print("  On https://serpapi.com/manage-api-key, click the dedicated 'Copy' icon next to the key rather than selecting text.", file=sys.stderr)
        else:
            print(f"\nDIAGNOSIS: The key is {key_len} characters long and does not contain a 64-hex key.", file=sys.stderr)
            print("  Check for extra characters, labels, or quotes when setting the variable.", file=sys.stderr)

        if not args.force:
            print("\nAborting account check to prevent guaranteed HTTP 401 error. Use --force to test against the server anyway.", file=sys.stderr)
            return 1

    # Call SerpApi free account endpoint
    # The account endpoint is free and does not consume a Google Flights search credit.
    request_url = f"{ACCOUNT_URL}?{urlencode({'api_key': api_key})}"
    request = Request(
        request_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Vayu-Backend/1.0",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Never echo the request URL, headers, or raw response bodies; they can contain secrets.
        if exc.code == 401:
            print("\nSerpApi account check: HTTP 401 Unauthorized")
            print("Explanation: The SerpApi server actively rejected the provided API key as invalid or unrecognized.")
            print("\nDistinction between HTTP 401 and 403:")
            print("  - HTTP 401 (Unauthorized): Authentication failed. SerpApi does NOT recognize this credential.")
            print("  - HTTP 403 (Forbidden): Authentication succeeded, but account is forbidden from the resource (e.g. quota limit / account locked).")
            print("\nMost likely causes for HTTP 401:")
            print("  1. Key was regenerated in SerpApi dashboard: Generating a new key immediately revokes any prior key.")
            print("     Ensure the newly generated key has been copied and set in this specific terminal session.")
            print("  2. Truncated key (e.g. 50 chars): Highlighting the dashboard text box only copies visible characters.")
            print("  3. Stale terminal session: $env:SERPAPI_API_KEY set in one PowerShell window does NOT affect other windows.")
            print("  4. Process environment vs .env mismatch: Verify which source is being read.")
            print("\nCode changes cannot make an invalid or revoked key valid on SerpApi's servers.")
            print("Please copy the newly active key from https://serpapi.com/manage-api-key using the Copy button.")
        elif exc.code == 403:
            print("\nSerpApi account check: HTTP 403 Forbidden")
            print("Explanation: The API key was authenticated and recognized by SerpApi, but account access is forbidden.")
            print("Causes: Search plan quota exhausted (e.g. monthly limit reached), account suspended, or IP restriction.")
        else:
            print(f"\nSerpApi account check failed with HTTP {exc.code}.")
        return 1
    except (URLError, TimeoutError, json.JSONDecodeError):
        print("Could not reach or parse the SerpApi account endpoint. Check your network connection and retry.", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("SerpApi account endpoint returned an unexpected response shape.", file=sys.stderr)
        return 1

    if payload.get("error"):
        print("SerpApi account check returned an API error. Verify account status on https://serpapi.com/dashboard", file=sys.stderr)
        return 1

    print("\nSerpApi account check succeeded (no Google Flights search was consumed).")
    for field in SAFE_FIELDS:
        if field in payload:
            print(f"  {field}: {payload[field]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
