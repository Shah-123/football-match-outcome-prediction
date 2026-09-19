# Football Match Outcome Prediction

Two things live here:

1. **A cleaned, audited core** of the Transfermarkt football dataset — 31
   domestic leagues, seasons 2012–2025, with the traps documented and the
   worst of them fixed. Built by [`build_clean_core.py`](build_clean_core.py),
   output in [`clean/`](clean/README.md).
2. **A match-outcome model** on the Premier League slice of it —
   [`project/notebook.ipynb`](project/README.md), predicting home win / draw /
   away win from pre-match information only.

The cleaning stage is the larger piece of work, and useful on its own.

## Why the raw data needs cleaning

The raw Transfermarkt export joins badly, and quietly:

- **Only domestic leagues join cleanly.** `competition_type ==
  'domestic_league'` is the one slice where 100% of games have both clubs
  present in `clubs.csv`. Cups manage 28%; national teams 0%. An inner join
  anywhere else silently drops rows. The clean core is restricted to that
  slice for exactly this reason.
- **Second-yellow sendings-off are invisible.** `yellow_cards == 2` always
  pairs with `red_cards == 0`, so counting `red_cards` undercounts
  dismissals. Fixed with a new `sent_off` column.
- **Own goals live only in free text** and are never credited to any player's
  `goals`, so scorelines don't reconcile. Summing `appearances.goals` matches
  the `games` scoreline for 91.2% of games; adding the parsed `is_own_goal`
  lifts that to 98.5%.
- **`players.csv` is a scrape-date snapshot, not history.** `current_club_id`,
  `market_value_in_eur` and friends describe the player *today*, so using them
  as features for a past match leaks the future. Renamed to `snapshot_*` so
  the mistake is hard to make by accident; use `player_valuations.csv` for
  point-in-time values.
- **Coverage roughly doubles at season 2024** — competitions per season jump
  from ~41–44 to 59 then 67. Raw year-over-year trends show a discontinuity
  that isn't real. Join `competition_season_panel.csv` and filter
  `in_balanced_panel == 1` for like-for-like comparisons.

Full audit, row counts and the caveats that remain unfixed:
[`clean/README.md`](clean/README.md).

## The model

Premier League only (`competition_id == 'GB1'`), reading `clean/games.csv`.
Sequential Elo plus rolling 5-game form, both computed leak-free, into a
logistic regression. Trained on seasons before 2024, tested on 2024–2025.

| model | test accuracy | macro-F1 |
|---|---:|---:|
| Elo + rolling form | **48.0%** | 0.361 |
| club/stadium/manager identity only | 45.4% | 0.350 |
| majority class (always home win) | 41.7% | — |

**Caveat worth reading before the accuracy number:** the model essentially
never predicts a draw — recall 0.005, one correct call out of 197. The gain
over baseline is better home/away separation, not three-way skill. Details and
limitations: [`project/README.md`](project/README.md).

## Layout

```
build_clean_core.py           raw CSVs -> clean/ (stdlib only, no pandas)
clean/                        the audited core, committed here
  README.md                   the audit: what was fixed, what still bites
  games.csv                   the table the notebook uses
  *.csv, *.csv.gz             10 more tables (3 gzipped for size)
project/
  notebook.ipynb              EDA, features, models, evaluation
  README.md                   method and results
  requirements.txt
```

## Run it

The clean data is committed, so the notebook runs straight from a clone:

```bash
pip install -r project/requirements.txt
jupyter lab project/notebook.ipynb
```

`appearances`, `game_events` and `game_lineups` are gzipped to stay under
GitHub's 100 MB file limit. pandas reads them without any extra step:

```python
pd.read_csv("clean/appearances.csv.gz")
```

To rebuild `clean/` from scratch, download the raw export
([Kaggle: `davidcariboo/player-scores`](https://www.kaggle.com/datasets/davidcariboo/player-scores))
into the repo root and run `python build_clean_core.py`. The script is
stdlib-only. Row counts in `clean/README.md` are regenerated each run, so a
newer snapshot will shift them.
