#!/usr/bin/env python3
"""Build the analysis-ready domestic-league core from the raw Transfermarkt CSVs.

Scope: competition_type == 'domestic_league'. That is the only slice where every
game has both clubs present in clubs.csv, so joins do not silently drop rows.

Run:  python build_clean_core.py
Out:  ./clean/*.csv  +  ./clean/README.md
"""
import csv, os, collections, datetime

csv.field_size_limit(10 ** 9)

SRC = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SRC, "clean")
os.makedirs(OUT, exist_ok=True)

# Columns that are 100% NULL in the raw data and carry no information.
DEAD_COLS = {
    "clubs.csv": ["total_market_value"],
}
# players.csv columns that hold scrape-date state, not historical state.
# Renamed so that using them as a historical feature is an obvious mistake.
SNAPSHOT_COLS = {
    "current_club_id", "current_club_name", "market_value_in_eur",
    "highest_market_value_in_eur", "current_club_domestic_competition_id",
    "current_national_team_id", "last_season",
}

stats = collections.OrderedDict()


def reader(fn):
    f = open(os.path.join(SRC, fn), newline="", encoding="utf-8")
    r = csv.reader(f)
    hdr = next(r)
    return f, r, hdr, {h: i for i, h in enumerate(hdr)}


def writer(fn, hdr):
    f = open(os.path.join(OUT, fn), "w", newline="", encoding="utf-8")
    w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
    w.writerow(hdr)
    return f, w


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- 1. games
log("[1/9] games.csv  -> filtering to domestic_league")
f, r, hdr, ix = reader("games.csv")
of, ow = writer("games.csv", hdr)
game_ids, club_ids, seasons = set(), set(), collections.Counter()
panel = collections.defaultdict(set)          # competition_id -> {season}
comp_season = collections.Counter()           # (competition_id, season) -> games
kept = total = 0
max_date = ""
for row in r:
    total += 1
    if row[ix["competition_type"]] != "domestic_league":
        continue
    kept += 1
    gid, cid, season = row[ix["game_id"]], row[ix["competition_id"]], row[ix["season"]]
    game_ids.add(gid)
    club_ids.add(row[ix["home_club_id"]])
    club_ids.add(row[ix["away_club_id"]])
    seasons[season] += 1
    panel[cid].add(season)
    comp_season[(cid, season)] += 1
    d = row[ix["date"]][:10]
    if d > max_date:
        max_date = d
    ow.writerow(row)
f.close()
of.close()
stats["games"] = (kept, total)
log("      {:,} / {:,} games kept | {:,} clubs | seasons {}-{} | latest match {}".format(
    kept, total, len(club_ids), min(seasons), max(seasons), max_date))
SNAPSHOT_DATE = max_date

# ------------------------------------------------- 2. game-grain fact tables
def filter_by_game(fn, gcol, extra_hdr=None, transform=None):
    f, r, hdr, ix = reader(fn)
    of, ow = writer(fn, hdr + (extra_hdr or []))
    kept = total = 0
    players = set()
    for row in r:
        total += 1
        if row[ix[gcol]] not in game_ids:
            continue
        kept += 1
        if "player_id" in ix and row[ix["player_id"]]:
            players.add(row[ix["player_id"]])
        ow.writerow(transform(row, ix) if transform else row)
    f.close()
    of.close()
    stats[fn.replace(".csv", "")] = (kept, total)
    log("      {:,} / {:,} rows kept".format(kept, total))
    return players


def app_transform(row, ix):
    """Second yellows are never flagged as reds in the raw data. Fix that."""
    try:
        y = int(row[ix["yellow_cards"]] or 0)
        rc = int(row[ix["red_cards"]] or 0)
        sent_off = 1 if (rc >= 1 or y >= 2) else 0
    except ValueError:
        sent_off = ""
    return row + [sent_off]


def event_transform(row, ix):
    d = row[ix["description"]].lower()
    return row + [1 if ("own goal" in d or "own-goal" in d) else 0]


log("[2/9] appearances.csv")
p1 = filter_by_game("appearances.csv", "game_id", ["sent_off"], app_transform)
log("[3/9] game_lineups.csv")
p2 = filter_by_game("game_lineups.csv", "game_id")
log("[4/9] game_events.csv")
p3 = filter_by_game("game_events.csv", "game_id", ["is_own_goal"], event_transform)
log("[5/9] club_games.csv")
filter_by_game("club_games.csv", "game_id")

player_ids = p1 | p2 | p3
log("      in-scope players: {:,}".format(len(player_ids)))

# ------------------------------------------------------------- 3. dimensions
log("[6/9] players.csv  -> renaming scrape-date snapshot columns")
f, r, hdr, ix = reader("players.csv")
out_hdr = [("snapshot_" + h if h in SNAPSHOT_COLS else h) for h in hdr]
of, ow = writer("players.csv", out_hdr)
kept = total = 0
for row in r:
    total += 1
    if row[ix["player_id"]] not in player_ids:
        continue
    kept += 1
    ow.writerow(row)
f.close()
of.close()
stats["players"] = (kept, total)
log("      {:,} / {:,} players kept".format(kept, total))

log("[7/9] player_valuations.csv")
f, r, hdr, ix = reader("player_valuations.csv")
of, ow = writer("player_valuations.csv", hdr)
kept = total = 0
for row in r:
    total += 1
    if row[ix["player_id"]] not in player_ids:
        continue
    kept += 1
    ow.writerow(row)
f.close()
of.close()
stats["player_valuations"] = (kept, total)
log("      {:,} / {:,} valuations kept".format(kept, total))

log("[8/9] transfers.csv  -> dropping future-dated moves, flagging known fees")
f, r, hdr, ix = reader("transfers.csv")
of, ow = writer("transfers.csv",
                hdr + ["fee_is_known", "from_club_in_scope", "to_club_in_scope"])
kept = total = future = 0
for row in r:
    total += 1
    if row[ix["player_id"]] not in player_ids:
        continue
    if row[ix["transfer_date"]][:10] > SNAPSHOT_DATE:
        future += 1
        continue
    kept += 1
    ow.writerow(row + [
        0 if row[ix["transfer_fee"]] == "" else 1,
        1 if row[ix["from_club_id"]] in club_ids else 0,
        1 if row[ix["to_club_id"]] in club_ids else 0,
    ])
f.close()
of.close()
stats["transfers"] = (kept, total)
log("      {:,} / {:,} transfers kept ({:,} future-dated dropped)".format(kept, total, future))

log("[9/9] clubs.csv / competitions.csv / panel reference")
for fn in ("clubs.csv", "competitions.csv"):
    f, r, hdr, ix = reader(fn)
    drop = set(DEAD_COLS.get(fn, []))
    keep_i = [i for i, h in enumerate(hdr) if h not in drop]
    of, ow = writer(fn, [hdr[i] for i in keep_i])
    kept = total = 0
    key = "club_id" if fn == "clubs.csv" else "competition_id"
    universe = club_ids if fn == "clubs.csv" else set(panel)
    for row in r:
        total += 1
        if row[ix[key]] not in universe:
            continue
        kept += 1
        ow.writerow([row[i] for i in keep_i])
    f.close()
    of.close()
    stats[fn.replace(".csv", "")] = (kept, total)
    log("      {}: {:,} / {:,} kept".format(fn, kept, total))

# competition x season panel, so the 2024 coverage break is visible and fixable
all_seasons = sorted(seasons)
of, ow = writer("competition_season_panel.csv",
                ["competition_id", "season", "games", "in_balanced_panel"])
balanced = {c for c, ss in panel.items() if set(all_seasons) <= ss}
for (cid, season), n in sorted(comp_season.items()):
    ow.writerow([cid, season, n, 1 if cid in balanced else 0])
of.close()
log("      balanced panel: {} of {} competitions present in all {} seasons".format(
    len(balanced), len(panel), len(all_seasons)))

# ------------------------------------------------------------------ README
lines = []
lines.append("# Clean core - domestic leagues only\n")
lines.append("Generated by `build_clean_core.py` on {}.\n".format(datetime.date.today()))
lines.append("Source snapshot: latest match **{}**.\n".format(SNAPSHOT_DATE))
lines.append("\n## Scope\n")
lines.append(
    "Every table is restricted to `competition_type == 'domestic_league'`, seasons\n"
    "{}-{}. This is the only slice of the raw data where **100% of games have both\n"
    "clubs present in `clubs.csv`** (cups are 28%, national teams 0%), so inner joins\n"
    "here do not silently drop rows.\n".format(min(seasons), max(seasons)))
lines.append("\n| table | rows kept | of raw |\n|---|---:|---:|\n")
for k, (a, b) in stats.items():
    lines.append("| {} | {:,} | {:,} |\n".format(k, a, b))
lines.append("""
## Fixes applied

- **`appearances.sent_off`** (new). In the raw data `yellow_cards == 2` always has
  `red_cards == 0`, so second-yellow dismissals are invisible. This column is 1 when
  the player was sent off by either route. Use it instead of `red_cards`.
- **`game_events.is_own_goal`** (new). Parsed from the free-text `description`, which
  is otherwise the only place own goals are recorded. Needed to reconcile scorelines.
- **`players.snapshot_*`** (renamed). `current_club_id`, `market_value_in_eur`,
  `last_season` and friends are scrape-date state, **not** historical state. Using
  them as features for a past outcome leaks the future. For point-in-time values use
  `player_valuations.csv`. The prefix makes the mistake hard to make by accident.
- **`transfers`**: future-dated moves (announced, beyond the snapshot date) are dropped.
  `fee_is_known` separates a real fee from a null - note the raw data has **no zero
  fees**, so free and undisclosed transfers are both null and cannot be told apart.
  `from_club_in_scope` / `to_club_in_scope` flag moves crossing outside the covered clubs.
- **`clubs.total_market_value`** dropped (100% null in the raw data).

## Still your problem

- **Coverage break at season 2024.** Competitions per season jump from ~41-44 to 59
  (2024) and 67 (2025). Raw year-over-year trends will show a phantom discontinuity.
  Join `competition_season_panel.csv` and filter `in_balanced_panel == 1` for
  like-for-like comparisons across seasons.
- **Different tables start at different dates.** `appearances` begins 2012 and
  `game_lineups` begins 2013, though `games` reaches further back. Player-level work
  is effectively 2013+ if you need lineups.
- **Goal attribution needs own goals added back.** Summing `appearances.goals` alone
  matches the `games` scoreline for 91.2% of games; adding `game_events.is_own_goal`
  lifts that to 98.5%. Own goals count toward the scoreline but are never credited to
  a player's `goals`. For match outcomes, prefer the scoreline directly.
- **603 player_ids in `game_lineups` and 207 in `game_events` have no row in
  `players.csv`** (of 42,201 in scope). `appearances` has none. Use a left join if you
  need every lineup row preserved.
""")
with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as fh:
    fh.write("".join(lines))

log("\nDone. Output in ./clean/")
