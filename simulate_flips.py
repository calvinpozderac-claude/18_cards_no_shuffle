#!/usr/bin/env python3
"""
Simulate 3-MCTS games (1000 rollouts each).
Track how many times each card type is flipped face-up, grouped by
(player_order_position, win_position).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import app as _app
from app import (
    _new_state, _ai_arrange, _ai_take_turn, _calculate_scores,
    LOCATION_NAMES,
)
import collections

N_GAMES = 200
ROLLOUTS = 1000
N_PLAYERS = 3

# ── patch _flip_up to record events ──────────────────────────────────────────
_orig_flip_up = _app._flip_up

def _tracked_flip_up(state, pidx, day):
    result = _orig_flip_up(state, pidx, day)
    if result:
        card = state["players"][pidx]["cards"][day - 1]
        state.setdefault("_flip_log", []).append((pidx, card["card_type"]))
    return result

_app._flip_up = _tracked_flip_up
# also patch the module-level reference used in _ai_take_turn
import importlib, types
# _ai_take_turn calls _flip_up from its own module scope — we patched _app._flip_up
# so it's already picked up since they share the same module object.

# ── game runner ───────────────────────────────────────────────────────────────
def run_game():
    state = _new_state([f"P{i+1}" for i in range(N_PLAYERS)])
    ai_players = list(range(N_PLAYERS))
    ai_diffs = {str(i): f"mcts:{ROLLOUTS}" for i in range(N_PLAYERS)}

    for i in range(N_PLAYERS):
        cards = [None] * 6
        for ct, day in _ai_arrange().items():
            cards[day - 1] = {"card_type": ct, "face_up": False, "arrival": 0}
        state["players"][i]["cards"] = cards
        state["players"][i]["arranged"] = True

    state["ai_players"] = ai_players
    state["ai_difficulties"] = ai_diffs
    state["phase"] = "game"
    state["_flip_log"] = []

    game = {"state": state, "tokens": [f"tok{i}" for i in range(N_PLAYERS)]}

    limit = 500
    for _ in range(limit):
        if state["phase"] != "game" or state["game_over"]:
            break
        _ai_take_turn(game)

    scores = _calculate_scores(state)
    score_vals = [scores[f"P{i+1}"] for i in range(N_PLAYERS)]

    # Rank players (1-indexed); ties share the lower rank
    sorted_scores = sorted(set(score_vals), reverse=True)
    rank = {s: i + 1 for i, s in enumerate(sorted_scores)}
    ranks = [rank[s] for s in score_vals]

    return state["_flip_log"], ranks, score_vals


# ── accumulate stats ──────────────────────────────────────────────────────────
# flip_counts[(player_order, win_position)][card_type] += count
flip_counts = collections.defaultdict(lambda: collections.defaultdict(int))
game_counts  = collections.defaultdict(int)  # games per (player_order, win_pos)

print(f"Running {N_GAMES} games with 3× MCTS-{ROLLOUTS}…", flush=True)

for g in range(N_GAMES):
    if (g + 1) % 10 == 0:
        print(f"  game {g+1}/{N_GAMES}", flush=True)
    flip_log, ranks, scores = run_game()

    # Tally flips-per-card per player
    player_flips = collections.defaultdict(lambda: collections.defaultdict(int))
    for pidx, ct in flip_log:
        player_flips[pidx][ct] += 1

    for pidx in range(N_PLAYERS):
        player_order = pidx + 1          # 1, 2, 3
        win_pos      = ranks[pidx]       # 1=1st, 2=2nd, 3=3rd
        key = (player_order, win_pos)
        game_counts[key] += 1
        for ct in range(1, 7):
            flip_counts[key][ct] += player_flips[pidx][ct]

# ── report ────────────────────────────────────────────────────────────────────
card_names = {1: "Coffee", 2: "Park", 3: "Cinema", 4: "Rest.", 5: "Beach", 6: "Museum"}

header = f"{'Player':>7}  {'Place':>7}   {'N':>5}  " + "  ".join(f"{card_names[ct]:>7}" for ct in range(1, 7)) + "  {'Total':>7}"
print()
print(header)
print("─" * len(header))

for player_order in range(1, N_PLAYERS + 1):
    for win_pos in range(1, N_PLAYERS + 1):
        key = (player_order, win_pos)
        n = game_counts.get(key, 0)
        if n == 0:
            continue
        avgs = [flip_counts[key][ct] / n for ct in range(1, 7)]
        total_avg = sum(avgs)
        row = f"{'P'+str(player_order):>7}  {str(win_pos)+'st/2nd/3rd'.split('/')[win_pos-1]:>7}   {n:>5}  "
        row += "  ".join(f"{a:>7.3f}" for a in avgs)
        row += f"  {total_avg:>7.3f}"
        print(row)
    print()

# ── collapsed: win position only (averaged over all player orders) ─────────────
print("\n── Collapsed by win position (all player orders pooled) ──")
wp_flips = collections.defaultdict(lambda: collections.defaultdict(int))
wp_counts = collections.defaultdict(int)
for (po, wp), n in game_counts.items():
    wp_counts[wp] += n
    for ct in range(1, 7):
        wp_flips[wp][ct] += flip_counts[(po, wp)][ct]

print(f"\n{'Place':>7}   {'N':>5}  " + "  ".join(f"{card_names[ct]:>7}" for ct in range(1, 7)) + "  {'Total':>7}")
print("─" * (len(header) - 12))
for wp in range(1, N_PLAYERS + 1):
    n = wp_counts[wp]
    label = ["1st", "2nd", "3rd"][wp - 1]
    avgs = [wp_flips[wp][ct] / n for ct in range(1, 7)]
    row = f"{label:>7}   {n:>5}  " + "  ".join(f"{a:>7.3f}" for a in avgs)
    row += f"  {sum(avgs):>7.3f}"
    print(row)

print("\nDone.")
