#!/usr/bin/env python3
"""Simulate MCTS (500 rollouts) vs Random AI across 8 player configurations."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Import game engine internals
from app import (
    _new_state, _ai_arrange, _ai_take_turn, _process_ai_turns,
    _calculate_scores, GAMES
)

import random
from collections import defaultdict

N_GAMES = 100  # games per configuration

CONFIGS = [
    ("MCTS",   "MCTS",   "MCTS"),
    ("MCTS",   "MCTS",   "RANDOM"),
    ("MCTS",   "RANDOM", "MCTS"),
    ("RANDOM", "MCTS",   "MCTS"),
    ("MCTS",   "RANDOM", "RANDOM"),
    ("RANDOM", "MCTS",   "RANDOM"),
    ("RANDOM", "RANDOM", "MCTS"),
    ("RANDOM", "RANDOM", "RANDOM"),
]

def run_game(config):
    """Run one full game with given config tuple ('MCTS'|'RANDOM', ...).
    Returns list of (name, score) in player order."""
    player_names = [f"P{i+1}" for i in range(len(config))]
    state = _new_state(player_names)

    ai_players = list(range(len(config)))
    ai_diffs = {}
    for i, ctype in enumerate(config):
        if ctype == "MCTS":
            ai_diffs[str(i)] = "mcts:500"
        else:
            ai_diffs[str(i)] = "random"
        # Arrange cards
        cards = [None] * 6
        for ct, day in _ai_arrange().items():
            cards[day - 1] = {"card_type": ct, "face_up": False, "arrival": 0}
        state["players"][i]["cards"] = cards
        state["players"][i]["arranged"] = True

    state["ai_players"] = ai_players
    state["ai_difficulties"] = ai_diffs
    state["phase"] = "game"

    # Use a temp game dict (no need to store in GAMES)
    game = {"state": state, "tokens": [f"tok{i}" for i in range(len(config))]}

    # Run until game over
    limit = 500
    i = 0
    while state["phase"] == "game" and not state["game_over"] and i < limit:
        _ai_take_turn(game)
        i += 1

    scores = _calculate_scores(state)
    return [(name, scores[name]) for name in player_names]


def simulate_config(config, n):
    wins   = defaultdict(int)  # wins[pos] = count
    ties   = 0
    total_scores = defaultdict(float)

    for _ in range(n):
        results = run_game(config)
        scores = [s for _, s in results]
        max_score = max(scores)
        winners = [i for i, s in enumerate(scores) if s == max_score]
        if len(winners) > 1:
            ties += 1
        else:
            wins[winners[0]] += 1
        for i, s in enumerate(scores):
            total_scores[i] += s

    return wins, ties, total_scores


def label(config):
    return "(" + ", ".join(config) + ")"


def main():
    print(f"Running {N_GAMES} games per configuration...\n")
    print(f"{'Config':<40} {'P1':>8} {'P2':>8} {'P3':>8}  {'Ties':>6}  {'AvgScore P1':>11} {'AvgScore P2':>11} {'AvgScore P3':>11}")
    print("-" * 120)

    for config in CONFIGS:
        wins, ties, total_scores = simulate_config(config, N_GAMES)
        win_pcts = [f"{wins[i]/N_GAMES*100:5.1f}%" for i in range(3)]
        avg_scores = [f"{total_scores[i]/N_GAMES:+.2f}" for i in range(3)]
        print(f"{label(config):<40} {win_pcts[0]:>8} {win_pcts[1]:>8} {win_pcts[2]:>8}  {ties:>6}  {avg_scores[0]:>11} {avg_scores[1]:>11} {avg_scores[2]:>11}")

    print("\nDone.")


if __name__ == "__main__":
    main()
