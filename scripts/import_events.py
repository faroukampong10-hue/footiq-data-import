#!/usr/bin/env python3

import json
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import Json, execute_values

DB_URL = os.environ.get("SUPABASE_DB_URL")
EVENTS_DIR = Path("statsbomb_events")
BATCH_SIZE = 1000
COMPETITION_ID = 2
SEASON_ID = 27


def main():
    if not DB_URL:
        sys.exit("ERROR: SUPABASE_DB_URL secret is missing.")

    files = sorted(EVENTS_DIR.rglob("*.json"))
    if not files:
        sys.exit(
            f"ERROR: No JSON event files found in {EVENTS_DIR.resolve()}"
        )

    print(f"Found {len(files)} event files.", flush=True)

    conn = psycopg2.connect(DB_URL, connect_timeout=30)

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (s.raw_data->>'match_id')::bigint,
                    m.id
                FROM public.statsbomb_matches_staging s
                JOIN public.statsbomb_team_mapping hm
                  ON hm.statsbomb_competition_id = s.competition_id
                 AND hm.statsbomb_season_id = s.season_id
                 AND hm.statsbomb_team_name =
                     s.raw_data->'home_team'->>'home_team_name'
                JOIN public.statsbomb_team_mapping am
                  ON am.statsbomb_competition_id = s.competition_id
                 AND am.statsbomb_season_id = s.season_id
                 AND am.statsbomb_team_name =
                     s.raw_data->'away_team'->>'away_team_name'
                JOIN public.matches m
                  ON m.match_date =
                     (s.raw_data->>'match_date')::date
                 AND m.home_team_id = hm.footiq_team_id
                 AND m.away_team_id = am.footiq_team_id
                 AND m.season_id = hm.footiq_season_id
                WHERE s.competition_id = %s
                  AND s.season_id = %s
                """,
                (COMPETITION_ID, SEASON_ID),
            )
            mapping = {
                int(statsbomb_id): int(footiq_id)
                for statsbomb_id, footiq_id in cur.fetchall()
            }

        print(f"Found {len(mapping)} mapped matches.", flush=True)

        if len(mapping) != 380:
            raise RuntimeError(
                f"Expected 380 mapped matches; found {len(mapping)}. "
                "Stopping without importing."
            )

        total_events = 0

        for file_number, path in enumerate(files, start=1):
            try:
                statsbomb_id = int(path.stem)
            except ValueError:
                print(f"Skipping non-match file: {path}", flush=True)
                continue

            if statsbomb_id not in mapping:
                raise RuntimeError(
                    f"No FootIQ mapping for StatsBomb match {statsbomb_id}"
                )

            with path.open("r", encoding="utf-8") as handle:
                events = json.load(handle)

            if not isinstance(events, list):
                raise RuntimeError(f"Unexpected JSON format in {path}")

            with conn.cursor() as cur:
                for start in range(0, len(events), BATCH_SIZE):
                    batch = events[start:start + BATCH_SIZE]

                    rows = [
                        (
                            statsbomb_id,
                            mapping[statsbomb_id],
                            COMPETITION_ID,
                            SEASON_ID,
                            start + offset,
                            event.get("id"),
                            (event.get("type") or {}).get("name"),
                            event.get("timestamp"),
                            Json(event),
                            str(path),
                        )
                        for offset, event in enumerate(batch)
                    ]

                    execute_values(
                        cur,
                        """
                        INSERT INTO public.statsbomb_events_raw (
                            statsbomb_match_id,
                            footiq_match_id,
                            competition_id,
                            season_id,
                            event_index,
                            event_id,
                            event_type,
                            event_timestamp,
                            raw_event,
                            source_file
                        ) VALUES %s
                        ON CONFLICT (
                            statsbomb_match_id,
                            event_index
                        ) DO NOTHING
                        """,
                        rows,
                        page_size=BATCH_SIZE,
                    )

            conn.commit()
            total_events += len(events)

            if file_number % 10 == 0 or file_number == len(files):
                print(
                    f"Processed {file_number}/{len(files)} files; "
                    f"{total_events:,} source events read.",
                    flush=True,
                )

        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM public.statsbomb_events_raw"
            )
            final_count = cur.fetchone()[0]

        print(
            f"Import finished. Total rows in target table: "
            f"{final_count:,}",
            flush=True,
        )

        if final_count == 0:
            raise RuntimeError("Validation failed: target table is empty.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
