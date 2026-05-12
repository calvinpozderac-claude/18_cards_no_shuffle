#!/usr/bin/env python3
"""
Balance simulation for the 18-cards-no-shuffle card game.

Runs 500 all-MCTS games (300 rollouts each) to measure turn-order bias,
draft pick popularity, score distributions, and game diversity.
Also runs 50 games of Random vs 2× MCTS as a sanity check.

Usage:
    python balance.py
"""

import sys
import os
import random
import statistics
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))

from app import (
    _new_state,
    _ai_arrange,
    _ai_take_turn,
    _calculate_scores,
    _do_draft_pick,
    _process_draft_picks,
    _process_ai_arrangements,
    LOCATION_NAMES,
    CARD_PTS,
)

# ── Configuration ─────────────────────────────────────────────────────────────

N_GAMES   = 500
ROLLOUTS  = 400
N_PLAYERS = 3
N_RANDOM_GAMES = 150  # enough for statistical significance


# ── Game runner ───────────────────────────────────────────────────────────────

def run_game(first_player_offset=0, rollouts=ROLLOUTS, random_player=None):
    """
    Run one complete game.

    Parameters
    ----------
    first_player_offset : int
        Unused positional rotation tracking (offset is informational; the
        actual draft starts from player 0 per _new_state — we just track
        which logical seat maps to which position for bias analysis).
    rollouts : int
        MCTS rollout budget.
    random_player : int or None
        If set, that player index uses "random" difficulty instead of MCTS.

    Returns
    -------
    tuple of:
        scores_dict  : {player_name: score}
        ranks_dict   : {player_name: rank (1=best)}
        draft_picks  : list of (draft_pick_index, card_type, player_idx)
                       in order picked
        arrangements : {player_idx: {card_type: day}}
    """
    player_names = [f"P{i+1}" for i in range(N_PLAYERS)]
    state = _new_state(player_names)

    # Mark all players as AI
    ai_players = list(range(N_PLAYERS))
    ai_diffs = {}
    for i in range(N_PLAYERS):
        if random_player is not None and i == random_player:
            ai_diffs[str(i)] = "random"
        else:
            ai_diffs[str(i)] = f"mcts:{rollouts}"

    state["ai_players"] = ai_players
    state["ai_difficulties"] = ai_diffs

    game = {"state": state, "tokens": [f"tok{i}" for i in range(N_PLAYERS)]}

    # ── Draft phase ───────────────────────────────────────────────────────────
    draft_picks = []  # list of (pick_index_global, card_type, player_idx)

    # Manually run the draft so we can record picks
    draft_order = state["draft_order"]
    for pick_idx, drafter in enumerate(draft_order):
        pool = state["draft_pool"]
        if not pool:
            break
        # Snapshot which types are available
        available = [c["card_type"] for c in pool]
        # Use the AI draft function
        from app import _ai_draft_pick
        ct = _ai_draft_pick(state, drafter)
        if ct is None:
            ct = random.choice(available)
        _do_draft_pick(state, drafter, ct)
        draft_picks.append((pick_idx, ct, drafter))

    # After draft is done, _do_draft_pick eventually calls _assign_normal_cards
    # which moves phase to "arrangement". Process AI arrangements.
    _process_ai_arrangements(game)

    # Record arrangements
    arrangements = {}
    for pidx, player in enumerate(state["players"]):
        arrangements[pidx] = {
            c["card_type"]: (i + 1)
            for i, c in enumerate(player["cards"])
            if c is not None
        }

    # ── Game phase ────────────────────────────────────────────────────────────
    limit = 500
    steps = 0
    while state["phase"] == "game" and not state["game_over"] and steps < limit:
        _ai_take_turn(game)
        steps += 1

    # ── Scoring ───────────────────────────────────────────────────────────────
    scores_dict = _calculate_scores(state)

    # Compute ranks (1 = best; ties share the better rank)
    sorted_scores = sorted(scores_dict.values(), reverse=True)
    ranks_dict = {}
    for name, sc in scores_dict.items():
        ranks_dict[name] = sorted_scores.index(sc) + 1

    return scores_dict, ranks_dict, draft_picks, arrangements


# ── Aggregation helpers ───────────────────────────────────────────────────────

def position_label(pidx):
    return f"P{pidx+1}"


def run_all_mcts(n=N_GAMES):
    """
    Run n all-MCTS games.  Returns aggregated stats.
    """
    # Per-position tracking (P1 = first drafter, P2 = second, P3 = third)
    wins_by_pos    = defaultdict(int)   # pos (0-indexed) -> win count
    scores_by_pos  = defaultdict(list)  # pos -> list of scores
    # Draft pick type frequency by pick slot
    pick_type_by_slot = defaultdict(lambda: defaultdict(int))  # slot -> {ct: count}
    # Arrangement matching: how often type N goes to day N
    match_by_type = defaultdict(int)   # ct -> count of matching placements
    match_total   = defaultdict(int)   # ct -> total placements
    # Score per-game list (for variance)
    all_game_scores = []

    print(f"Running {n} all-MCTS games ({ROLLOUTS} rollouts each) …")

    for g in range(n):
        if (g + 1) % 50 == 0:
            print(f"  … game {g+1}/{n}")

        scores, ranks, draft_picks, arrangements = run_game()
        game_scores = [scores[f"P{i+1}"] for i in range(N_PLAYERS)]
        all_game_scores.append(game_scores)

        # Winner (by index)
        max_score = max(game_scores)
        winners = [i for i, s in enumerate(game_scores) if s == max_score]
        # Tie-break: split credit equally (fractional wins)
        for w in winners:
            wins_by_pos[w] += 1.0 / len(winners)

        for pidx, sc in enumerate(game_scores):
            scores_by_pos[pidx].append(sc)

        for pick_idx, ct, drafter in draft_picks:
            pick_type_by_slot[pick_idx][ct] += 1

        for pidx, arr in arrangements.items():
            for ct, day in arr.items():
                match_total[ct] += 1
                if ct == day:
                    match_by_type[ct] += 1

    return {
        "wins_by_pos":       dict(wins_by_pos),
        "scores_by_pos":     dict(scores_by_pos),
        "pick_type_by_slot": dict(pick_type_by_slot),
        "match_by_type":     dict(match_by_type),
        "match_total":       dict(match_total),
        "all_game_scores":   all_game_scores,
        "n_games":           n,
    }


def run_random_vs_mcts(n=50):
    """
    Run n games where one player is Random, two are MCTS.
    Rotate which position is Random.
    Returns win rates for the random player.
    """
    random_wins = 0
    random_scores = []
    mcts_scores   = []

    print(f"\nRunning {n} Random vs 2×MCTS games …")
    for g in range(n):
        rp = g % N_PLAYERS  # rotate random player position
        scores, ranks, _, _ = run_game(random_player=rp)
        rname = f"P{rp+1}"
        r_sc = scores[rname]
        m_sc = [scores[f"P{i+1}"] for i in range(N_PLAYERS) if i != rp]
        random_scores.append(r_sc)
        mcts_scores.extend(m_sc)
        if ranks[rname] == 1:
            random_wins += 1

    return {
        "n":            n,
        "random_wins":  random_wins,
        "random_scores": random_scores,
        "mcts_scores":   mcts_scores,
    }


# ── Reporting ─────────────────────────────────────────────────────────────────

def report(stats, random_stats):
    n = stats["n_games"]
    wins    = stats["wins_by_pos"]
    scores  = stats["scores_by_pos"]
    picks   = stats["pick_type_by_slot"]
    matches = stats["match_by_type"]
    totals  = stats["match_total"]
    all_sc  = stats["all_game_scores"]

    sep = "=" * 72

    print("\n" + sep)
    print("  BALANCE SIMULATION RESULTS")
    print(f"  {n} all-MCTS games  ·  {ROLLOUTS} rollouts  ·  {N_PLAYERS} players")
    print(sep)

    # ── 1. Win rates by position ───────────────────────────────────────────
    print("\n── 1. WIN RATES BY DRAFT POSITION ─────────────────────────────────")
    print(f"  {'Position':<10} {'Wins':>8} {'Win%':>8}  {'Bias vs 33%':>12}")
    print("  " + "-" * 42)
    for pidx in range(N_PLAYERS):
        w   = wins.get(pidx, 0)
        pct = w / n * 100
        bias = pct - 100/N_PLAYERS
        flag = "  ← NOTABLE" if abs(bias) > 5 else ""
        print(f"  {position_label(pidx):<10} {w:>8.1f} {pct:>7.1f}%  {bias:>+11.1f}%{flag}")
    expected = 100 / N_PLAYERS
    print(f"\n  Expected win rate per position: {expected:.1f}%")
    print(f"  (>5% deviation flagged as notable turn-order bias)")

    # ── 2. Average score by position ──────────────────────────────────────
    print("\n── 2. SCORE DISTRIBUTION BY DRAFT POSITION ────────────────────────")
    print(f"  {'Position':<10} {'Mean':>8} {'Std':>8} {'Min':>8} {'Max':>8}")
    print("  " + "-" * 46)
    for pidx in range(N_PLAYERS):
        sc = scores.get(pidx, [0])
        print(f"  {position_label(pidx):<10} "
              f"{statistics.mean(sc):>+8.2f} "
              f"{statistics.stdev(sc) if len(sc)>1 else 0:>8.2f} "
              f"{min(sc):>+8} "
              f"{max(sc):>+8}")

    # ── 3. Overall score variance ──────────────────────────────────────────
    flat_scores = [s for row in all_sc for s in row]
    print(f"\n  Overall score mean : {statistics.mean(flat_scores):+.2f}")
    print(f"  Overall score std  : {statistics.stdev(flat_scores):.2f}")

    # Score spread per game (max - min)
    spreads = [max(row) - min(row) for row in all_sc]
    print(f"  Avg score spread per game: {statistics.mean(spreads):.2f}  "
          f"(std {statistics.stdev(spreads):.2f})")
    tight = sum(1 for s in spreads if s < 3) / n * 100
    print(f"  Games with spread < 3 pts: {tight:.1f}%  "
          f"({'boring' if tight > 30 else 'OK'})")

    # ── 4. Draft pick frequency by card type ──────────────────────────────
    print("\n── 3. DRAFT PICK FREQUENCY BY CARD TYPE ────────────────────────────")

    # Aggregate all picks
    type_counts = defaultdict(int)
    for slot_data in picks.values():
        for ct, cnt in slot_data.items():
            type_counts[ct] += cnt

    total_picks = sum(type_counts.values())
    print(f"  {'Card Type':<20} {'Picks':>8} {'%':>8}  Notes")
    print("  " + "-" * 52)
    for ct in sorted(type_counts, key=lambda x: -type_counts[x]):
        cnt = type_counts[ct]
        pct = cnt / total_picks * 100
        expected_pct = 100 / 6  # 6 card types, equal probability expected
        flag = "  ← DOMINANT" if pct > expected_pct * 1.5 else (
               "  ← AVOIDED"  if pct < expected_pct * 0.6 else "")
        print(f"  {LOCATION_NAMES[ct]:<20} {cnt:>8} {pct:>7.1f}%{flag}")

    # Pick frequency by round (snake draft: slots 0-2 = forward, 3-5 = reverse)
    print(f"\n  Draft pick breakdown by slot (0=P1 first pick … 5=P1 last pick):")
    print(f"  {'Slot':<6} {'Drafter':<10}", end="")
    for ct in range(1, 7):
        print(f" {LOCATION_NAMES[ct][:6]:>7}", end="")
    print()
    print("  " + "-" * (16 + 7 * 6))

    # snake order: 0→P1,1→P2,2→P3,3→P3,4→P2,5→P1
    snake = [0, 1, 2, 2, 1, 0]
    for slot in range(6):
        drafter = snake[slot]
        slot_data = picks.get(slot, {})
        slot_total = sum(slot_data.values()) or 1
        print(f"  {slot:<6} {position_label(drafter):<10}", end="")
        for ct in range(1, 7):
            pct = slot_data.get(ct, 0) / slot_total * 100
            print(f" {pct:>6.0f}%", end="")
        print()

    # ── 5. Day-matching rates ──────────────────────────────────────────────
    print("\n── 4. ARRANGEMENT — DAY-MATCH RATE BY CARD TYPE ───────────────────")
    print(f"  (how often type-N card is placed on day N)")
    print(f"  {'Card Type':<20} {'Match%':>8}  Notes")
    print("  " + "-" * 40)
    for ct in range(1, 7):
        tot = totals.get(ct, 0) or 1
        pct = matches.get(ct, 0) / tot * 100
        print(f"  {LOCATION_NAMES[ct]:<20} {pct:>7.1f}%")

    # ── 6. Random vs MCTS sanity check ────────────────────────────────────
    rn = random_stats["n"]
    rw = random_stats["random_wins"]
    rs = random_stats["random_scores"]
    ms = random_stats["mcts_scores"]
    print("\n── 5. RANDOM vs 2×MCTS SANITY CHECK ───────────────────────────────")
    print(f"  {rn} games, Random player rotates position each game")
    print(f"  Random win rate : {rw/rn*100:.1f}%  "
          f"(expected ~10-20% by chance alone)")
    print(f"  Random avg score: {statistics.mean(rs):+.2f}  "
          f"(MCTS avg: {statistics.mean(ms):+.2f})")
    diff = statistics.mean(ms) - statistics.mean(rs)
    print(f"  MCTS advantage  : {diff:+.2f} pts avg")
    sanity = "PASS" if rw / rn < 0.25 else "FAIL — Random too competitive!"
    print(f"  Sanity check    : {sanity}")

    # ── 7. Recommendations ────────────────────────────────────────────────
    print("\n── 6. RECOMMENDATIONS (for human review) ──────────────────────────")
    print()

    # Turn-order bias
    biases = {pidx: wins.get(pidx, 0)/n*100 - 100/N_PLAYERS
              for pidx in range(N_PLAYERS)}
    max_bias = max(abs(b) for b in biases.values())
    if max_bias > 5:
        worst = max(biases, key=lambda x: abs(biases[x]))
        print(f"  [TURN ORDER BIAS]  {position_label(worst)} has {biases[worst]:+.1f}% deviation.")
        print(f"  Consider adjusting draft order or giving later pickers compensation picks.")
    else:
        print(f"  [TURN ORDER BIAS]  None detected (max deviation {max_bias:.1f}%). Draft seems fair.")

    # Dominant card types
    dominant = [ct for ct in type_counts
                if type_counts[ct] / total_picks * 100 > (100/6)*1.5]
    avoided  = [ct for ct in type_counts
                if type_counts[ct] / total_picks * 100 < (100/6)*0.6]
    if dominant:
        print(f"\n  [DOMINANT CARDS]   {', '.join(LOCATION_NAMES[ct] for ct in dominant)} "
              f"are drafted disproportionately often.")
        print(f"  Consider reducing first-arrival points for these card types.")
    else:
        print(f"\n  [DOMINANT CARDS]   No single card type dominates the draft.")
    if avoided:
        print(f"\n  [WEAK CARDS]       {', '.join(LOCATION_NAMES[ct] for ct in avoided)} "
              f"are rarely drafted.")
        print(f"  Consider increasing point values or adding bonus effects.")

    # Score variance
    overall_std = statistics.stdev(flat_scores)
    if overall_std < 3:
        print(f"\n  [SCORE VARIANCE]   Low variance ({overall_std:.2f} std). "
              f"Games may feel repetitive.")
        print(f"  Consider increasing point spreads (e.g., bigger 1st-arrival bonuses).")
    elif overall_std > 8:
        print(f"\n  [SCORE VARIANCE]   High variance ({overall_std:.2f} std). "
              f"Luck may dominate skill.")
    else:
        print(f"\n  [SCORE VARIANCE]   Healthy variance ({overall_std:.2f} std). No change needed.")

    # Specific card point suggestions based on draft share
    print(f"\n  [CARD_PTS SUGGESTIONS]")
    print(f"  Current CARD_PTS = {{")
    for ct in range(1, 7):
        print(f"      {ct}: {CARD_PTS[ct]},   # {LOCATION_NAMES[ct]}")
    print(f"  }}")
    print(f"\n  Based on draft share (no changes made — human decides):")
    for ct in sorted(type_counts, key=lambda x: -type_counts[x]):
        pct = type_counts[ct] / total_picks * 100
        exp = 100 / 6
        if pct > exp * 1.3:
            print(f"    {LOCATION_NAMES[ct]}: drafted {pct:.0f}% — consider nerfing "
                  f"(e.g., reduce 1st-arrival from {CARD_PTS[ct][0]} to {CARD_PTS[ct][0]-1})")
        elif pct < exp * 0.75:
            print(f"    {LOCATION_NAMES[ct]}: drafted {pct:.0f}% — consider buffing "
                  f"(e.g., increase pts or add effect)")

    print("\n" + sep)
    print("  END OF REPORT  —  no rule changes applied")
    print(sep + "\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*72}")
    print(f"  18-Cards-No-Shuffle  —  Balance Simulation")
    print(f"  {N_GAMES} games, {ROLLOUTS} MCTS rollouts, {N_PLAYERS} players")
    print(f"{'='*72}\n")

    # Phase 1: all-MCTS
    stats = run_all_mcts(N_GAMES)

    # Phase 2: Random vs MCTS sanity check
    random_stats = run_random_vs_mcts(N_RANDOM_GAMES)

    # Report
    report(stats, random_stats)


if __name__ == "__main__":
    main()
