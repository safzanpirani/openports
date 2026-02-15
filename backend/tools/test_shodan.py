"""Quick Shodan sanity check.

Usage:
  cd backend
  export SHODAN_API_KEY='...'
  uv run python tools/test_shodan.py

It prints your API plan info and tries a tiny search.
"""

from __future__ import annotations

import os

import shodan


def main() -> None:
    key = os.getenv("SHODAN_API_KEY")
    if not key:
        raise SystemExit("SHODAN_API_KEY env var not set")

    api = shodan.Shodan(key)

    print("== api.info() ==")
    try:
        info = api.info()
        for k in sorted(info.keys()):
            print(f"{k}: {info[k]}")
    except Exception as e:
        print("api.info() failed:", repr(e))

    print("\n== search test ==")
    try:
        res = api.search("port:8188", limit=1)
        matches = res.get("matches", [])
        print("matches:", len(matches))
        if matches:
            m = matches[0]
            print("first ip:", m.get("ip_str"), "port:", m.get("port"))
    except Exception as e:
        print("search failed:", repr(e))


if __name__ == "__main__":
    main()
