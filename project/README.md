# Premier League Match Outcome Prediction

`notebook.ipynb` predicts **home win / draw / away win** for English Premier
League matches, using only information available before kickoff. Data comes
from `../clean/games.csv` (the audited Transfermarkt core — see
`../clean/README.md`), filtered to `competition_id == 'GB1'`.

It is the only table the notebook reads.

## What the notebook does

1. **Quality checks on `games.csv`** — nulls, `game_id` uniqueness, and which
   columns are safe to keep. Manager names, attendance and formations are
   dropped where null coverage makes them unusable.
2. **Leakage check on `home_club_position` / `away_club_position`.** If these
   were pre-match standings, every club would be level on matchday 1. They
   aren't — they're already spread 1–20, so they're post-match standings.
   Excluded from every feature set for that reason.
3. **EDA** on the Premier League slice — outcome distribution, most common
   scorelines, cumulative all-time points (Big Six vs. rest).
4. **Two models, both time-split** (train seasons < 2024, test 2024–2025):
   - **v1 — context only.** One-hot `stadium`, `competition_type`, both club
     names, both manager names, plus `season`. Logistic regression (`C=0.5`).
   - **v2 — v1 + strength and form.** Adds a sequential **Elo** rating
     (K=20, home advantage 60) and **rolling 5-game form** (points and goal
     difference, per club). Both are computed leak-free: Elo reads each club's
     rating *before* the match then updates it, and form uses `.shift(1)`
     before the rolling window, so no row ever sees its own result. Median
     imputation → scaling → logistic regression (`C=0.2`).
5. **`predict_match` / `predict_match_v2`** — call an arbitrary fixture by club
   and manager name. v2 looks up each club's current Elo and latest form, and
   optionally converts predicted probabilities to fair odds against a supplied
   bookmaker line.

## Results

Test set: 760 Premier League matches, seasons 2024–2025. Trained on everything
before 2024, never shuffled.

| model | test accuracy | macro-F1 | log loss |
|---|---:|---:|---:|
| v2 — Elo + rolling form | **48.0%** | 0.361 | 1.046 |
| v1 — names/stadium/season only | 45.4% | 0.350 | — |
| majority class (always home win) | 41.7% | — | — |

Elo and form are worth about **+2.6 points of accuracy** over club identity
alone — a real gain, but modest.

## The draw problem

Neither model can call a draw. v2 gets **recall 0.005 on draws — 1 correct out
of 197**, and precision 0.091. It has effectively learned to never predict one.

That isn't a bug in the pipeline, it's what these features support: draws have
no distinctive pre-match signature, so a model optimizing overall accuracy is
better off never guessing one. This is consistent with the outcome-prediction
literature (Dixon–Coles and successors model goals, not the three-way outcome,
partly for this reason). Home wins carry the model: recall 0.792.

Read the headline accuracy with that in mind — 48% against a 41.7% baseline is
mostly better home/away separation, not three-way skill.

## Known limitations

- **Draws are not predicted** (see above). Macro-F1 of 0.361 is the honest
  number; accuracy flatters the model.
- **Premier League only.** `clean/` covers 31 domestic leagues; this notebook
  uses one. Nothing here has been validated outside GB1.
- **No hyperparameter search.** `C` was set by hand on both models. There's no
  cross-validation and no validation split — the 2024–2025 test set is the only
  holdout, so repeated tweaking against it would erode its independence.
- **One model family.** Logistic regression only; no tree/boosting comparison.
- **Manager name as a feature** is high-cardinality and one-hot encoded, so a
  new manager is simply unseen (`handle_unknown="ignore"` → all-zero).
- **`predict_match_v2`'s odds output is descriptive, not advice.** Model
  probabilities with log loss 1.046 are not sharp enough to bet on.

## Run it

Data is in `../clean/` and already committed. From this folder:

```bash
pip install -r requirements.txt
jupyter lab notebook.ipynb
```

### If scikit-learn fails to import

On Windows, Smart App Control can block scikit-learn's compiled DLLs
(`ImportError: DLL load failed ... An Application Control policy has blocked
this file`) — a per-file reputation check with no user-level override. A
different Python install usually has wheels that pass:

```bash
python314 -m pip install -r requirements.txt
python314 -m ipykernel install --user --name py314 --display-name "Python 3.14 (sklearn)"
```

## Next steps

- Cross-validate with `TimeSeriesSplit` and carve a validation split out of the
  training seasons, so `C` is tuned without touching the test set.
- Compare against gradient boosting and a random forest on the same features.
- Model **goals** (Poisson / Dixon–Coles) instead of the three-way outcome —
  the standard route to getting draws right.
- Extend beyond GB1; `clean/` already holds 30 other leagues.
