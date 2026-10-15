name: FootIQ StatsBomb Event Import

on:
  workflow_dispatch:
    inputs:
      download_only:
        description: "Only download and verify files (skip database import)"
        type: boolean
        default: true

jobs:
  import-events:
    runs-on: ubuntu-24.04
    timeout-minutes: 360

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          pip install psycopg2-binary

      - name: Download StatsBomb event files from GitHub
        run: |
          set -euo pipefail
          BASE="https://raw.githubusercontent.com/statsbomb/open-data/master/data"
          curl -fsSL --retry 5 --retry-delay 3 "$BASE/matches/2/27.json" -o matches.json
          jq -r '.[].match_id' matches.json > match_ids.txt
          COUNT=$(wc -l < match_ids.txt)
          echo "Matches listed: $COUNT"
          if [ "$COUNT" -ne 380 ]; then
            echo "Expected 380 matches"
            exit 1
          fi
          mkdir -p statsbomb_events
          xargs -P 8 -I{} curl -fsSL --retry 5 --retry-delay 3 "$BASE/events/{}.json" -o "statsbomb_events/{}.json" < match_ids.txt

      - name: Verify downloaded files
        run: |
          python3 - <<'EOF'
          import json, pathlib
          files = sorted(pathlib.Path("statsbomb_events").glob("*.json"))
          assert len(files) == 380, f"Expected 380 files, found {len(files)}"
          for f in files:
              data = json.load(open(f, encoding="utf-8"))
              assert isinstance(data, list) and data, f"Bad file: {f}"
          print(f"OK: {len(files)} valid event files")
          EOF

      - name: Measure trimmed size
        run: |
          python3 - <<'EOF'
          import json, pathlib, sys, collections
          sys.path.insert(0, "scripts")
          from slim_events import slim_event
          kept = 0
          total = 0
          size = 0
          types = collections.Counter()
          for f in sorted(pathlib.Path("statsbomb_events").glob("*.json")):
              events = json.load(open(f, encoding="utf-8"))
              total += len(events)
              for e in events:
                  s = slim_event(e)
                  if s is not None:
                      kept += 1
                      size += len(json.dumps(s))
                      types[s["type"]["name"]] += 1
          print(f"EVENTS: {total:,} total, {kept:,} kept")
          print(f"SLIM JSON: {size/1e6:.0f} MB")
          print(f"ESTIMATED DB SIZE: {(size*1.15 + kept*350)/1e6:.0f} MB (free limit 500 MB, 13 MB already used)")
          for name, count in types.most_common():
              print(f"  {name}: {count:,}")
          EOF

      - name: Import events into FootIQ
        if: ${{ inputs.download_only == false }}
        env:
          SUPABASE_DB_URL: ${{ secrets.SUPABASE_DB_URL }}
        run: |
          python scripts/import_events.py
