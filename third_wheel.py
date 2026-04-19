#!/usr/bin/env python3
"""Don't Be the Third Wheel! -- playable prototype.

A 3-player 18-card game. Each player gets cards 1-6 (the 'places') and
secretly assigns each to one of 6 day slots. Turns rotate: on your turn you
flip one of your face-down cards up, trigger its ability (first flip only),
and the card's arrival order within its (day, place) group is recorded.

Scoring (per (day, place) group):
  1 card   -> solo:       owner gets SCORING[t][0]
  2 cards  -> date:       1st/2nd get SCORING[t][1], SCORING[t][2]
  3 cards  -> third wheel:1st/2nd/3rd get SCORING[t][3..5]

Modes:
  python third_wheel.py              # 1 human vs 2 AI, hotseat-friendly
  python third_wheel.py --all-human  # 3 humans, hotseat
  python third_wheel.py --all-ai     # 3 AI, verbose single game
  python third_wheel.py --sim 1000   # 1000 AI games, print score stats
"""

import argparse
import os
import random
import sys
from dataclasses import dataclass, field
from statistics import mean, stdev

PLACES = {
    1: "Coffee Shop",
    2: "Movie Theater",
    3: "Beach Walk",
    4: "Fancy Restaurant",
    5: "Picnic in the Park",
    6: "Rooftop Bar",
}

ABILITIES = {
    1: "Flip an opponent's face-up card face-down (it becomes replayable).",
    2: "Flip one of your own face-up cards face-down (it becomes replayable).",
    3: "Swap the day slot of two of a chosen opponent's face-down cards (blind).",
    4: "Swap the day slot of two of your own face-down cards.",
    5: "Swap arrival order of two face-up cards in the same date (at least one opponent's).",
    6: "Swap arrival order of two face-up cards in the same date (at least one yours).",
}

# Per-place scoring: (solo, date_1st, date_2nd, triple_1st, triple_2nd, triple_3rd)
# Tweak freely when balancing.
SCORING = {
    1: (1, 1, 1,  0,  0, -1),  # Coffee Shop -- low stakes
    2: (1, 1, 2,  0,  0, -1),  # Movie Theater
    3: (1, 1, 2,  0,  0, -1),  # Beach Walk
    4: (1, 1, 3,  0,  0, -2),  # Fancy Restaurant -- high stakes
    5: (1, 2, 2,  0,  0, -1),  # Picnic -- 1st and 2nd both good
    6: (1, 1, 3,  0, -1, -2),  # Rooftop -- punishing triple
}

N_PLAYERS = 3
N_CARDS = 6  # cards per player == days


# ---------------------------------------------------------------- data types

@dataclass
class Card:
    owner: int
    card_type: int     # 1..6 (the place)
    day: int           # 1..6
    face_up: bool = False
    ability_used: bool = False
    arrival: int = 0   # 1/2/3 within (day, card_type) group; 0 if face-down

    def label(self):
        return f"{self.card_type}:{PLACES[self.card_type]}"


@dataclass
class Player:
    idx: int
    name: str
    is_ai: bool
    cards: list = field(default_factory=list)


# ---------------------------------------------------------------- game

class Game:
    def __init__(self, human_indices=(0,), seed=None, verbose=True):
        if seed is not None:
            random.seed(seed)
        self.verbose = verbose
        self.players = [
            Player(i, f"Player {i+1}", is_ai=(i not in human_indices))
            for i in range(N_PLAYERS)
        ]
        self.cards = []
        for p in self.players:
            for t in range(1, N_CARDS + 1):
                c = Card(owner=p.idx, card_type=t, day=0)
                self.cards.append(c)
                p.cards.append(c)
        # Turn order: P1, P2, P3, P1, P2, P3, ... (18 turns)
        self.turn_order = [i for _ in range(N_CARDS) for i in range(N_PLAYERS)]
        self.turn_idx = 0

    # ---------- helpers

    def log(self, msg):
        if self.verbose:
            print(msg)

    def group(self, day, card_type):
        """Face-up cards in (day, card_type), sorted by arrival."""
        cs = [c for c in self.cards if c.day == day and c.card_type == card_type and c.face_up]
        cs.sort(key=lambda x: x.arrival)
        return cs

    def next_arrival(self, day, card_type):
        return len(self.group(day, card_type)) + 1

    def renumber(self, day, card_type):
        for i, c in enumerate(self.group(day, card_type), 1):
            c.arrival = i

    def opponents_of(self, pi):
        return [p for p in self.players if p.idx != pi]

    # ---------- setup

    def setup(self):
        for p in self.players:
            if p.is_ai:
                days = list(range(1, N_CARDS + 1))
                random.shuffle(days)
                for c, d in zip(p.cards, days):
                    c.day = d
            else:
                self._human_setup(p)

    def _human_setup(self, p):
        clear_screen()
        print(f"=== SETUP: {p.name} ===")
        print("Places (the card types):")
        for t, name in PLACES.items():
            print(f"  {t} = {name}   -- ability: {ABILITIES[t]}")
        print()
        print("You will assign each of your 6 cards to a day (1..6), each day exactly once.")
        print("Enter six numbers separated by spaces: the day for cards 1,2,3,4,5,6 in order.")
        print("Example: '3 1 4 5 2 6' -> card 1 on day 3, card 2 on day 1, ...")
        while True:
            raw = input(f"{p.name}, days for cards 1..6: ").strip()
            try:
                days = [int(x) for x in raw.split()]
            except ValueError:
                print("  please enter integers.")
                continue
            if sorted(days) != list(range(1, N_CARDS + 1)):
                print("  must be a permutation of 1..6.")
                continue
            for c, d in zip(p.cards, days):
                c.day = d
            break
        input("  placement locked. Press Enter to pass the device...")
        clear_screen()

    # ---------- rendering

    def render_public(self):
        """Public view: face-up cards arranged by (day, place)."""
        lines = ["", "===== TABLE ====="]
        header = "Day |   " + "   ".join(f"{t}:{PLACES[t][:8]:<8}" for t in range(1, 7))
        lines.append(header)
        for d in range(1, 7):
            cells = []
            for t in range(1, 7):
                g = self.group(d, t)
                if not g:
                    cells.append("  .  ")
                else:
                    cells.append("/".join(f"P{c.owner+1}" for c in g))
            cells = [f"{c:<11}" for c in cells]
            lines.append(f" {d}  |   " + "".join(cells))
        lines.append("=================")
        return "\n".join(lines)

    def render_private(self, pi):
        p = self.players[pi]
        rows = []
        for d in range(1, 7):
            ents = [c for c in p.cards if c.day == d]
            ents.sort(key=lambda c: c.card_type)
            cell = ", ".join(
                f"{'[' + str(c.card_type) + ']' if not c.face_up else str(c.card_type)}"
                for c in ents
            )
            rows.append(f"  Day {d}: {cell}")
        legend = "(your cards -- [n] = face-down, n = face-up)"
        return f"--- {p.name} private view --- {legend}\n" + "\n".join(rows)

    # ---------- turn

    def play_turn(self):
        pi = self.turn_order[self.turn_idx]
        p = self.players[pi]
        face_down = [c for c in p.cards if not c.face_up]
        if not face_down:
            self.turn_idx += 1
            return
        if p.is_ai:
            card = self._ai_pick_card(p, face_down)
        else:
            card = self._human_pick_card(p, face_down)

        card.face_up = True
        card.arrival = self.next_arrival(card.day, card.card_type)
        self.log(f"\n[T{self.turn_idx+1}] {p.name} plays {card.label()} on Day {card.day} "
                 f"(arrival #{card.arrival})")

        if not card.ability_used:
            card.ability_used = True
            self._resolve_ability(p, card)
        else:
            self.log(f"  (ability already used; just a replay)")

        self.turn_idx += 1

    # ---------- abilities

    def _resolve_ability(self, p, card):
        t = card.card_type
        self.log(f"  Ability {t}: {ABILITIES[t]}")
        if t == 1:
            self._ability_flip_down(p, card, opponent=True)
        elif t == 2:
            self._ability_flip_down(p, card, opponent=False)
        elif t == 3:
            self._ability_swap_days(p, opponent=True)
        elif t == 4:
            self._ability_swap_days(p, opponent=False)
        elif t == 5:
            self._ability_swap_arrival(p, require_opponent=True)
        elif t == 6:
            self._ability_swap_arrival(p, require_own=True)

    def _ability_flip_down(self, p, card, opponent):
        if opponent:
            targets = [c for c in self.cards if c.face_up and c.owner != p.idx]
        else:
            targets = [c for c in self.cards if c.face_up and c.owner == p.idx and c is not card]
        if not targets:
            self.log("    no valid target -- ability fizzles.")
            return
        if p.is_ai:
            target = self._ai_pick_flip_target(p, targets, opponent)
        else:
            target = self._human_pick(p, targets,
                                      f"Pick a card to flip face-down",
                                      lambda c: f"P{c.owner+1} {c.label()} on Day {c.day} (arr #{c.arrival})")
        d, t_ = target.day, target.card_type
        self.log(f"    flips P{target.owner+1}'s {target.label()} on Day {d} face-down.")
        target.face_up = False
        target.arrival = 0
        self.renumber(d, t_)

    def _ability_swap_days(self, p, opponent):
        if opponent:
            opps = self.opponents_of(p.idx)
            # pick which opponent
            if p.is_ai:
                tgt = random.choice(opps)
            else:
                tgt = self._human_pick(p, opps, "Pick an opponent to shuffle",
                                       lambda o: o.name)
            face_down = [c for c in tgt.cards if not c.face_up]
        else:
            face_down = [c for c in p.cards if not c.face_up]
            tgt = p
        if len(face_down) < 2:
            self.log("    not enough face-down cards -- fizzles.")
            return
        if p.is_ai:
            a, b = random.sample(face_down, 2)
        else:
            if opponent:
                # blind: opponent's cards, show only day slots
                labeled = [f"Day {c.day} (face-down)" for c in face_down]
            else:
                labeled = [f"Day {c.day}: card {c.card_type} ({PLACES[c.card_type]})"
                           for c in face_down]
            a = self._human_pick(p, face_down, f"Pick first card from {tgt.name}", lambda c: labeled[face_down.index(c)])
            remaining = [c for c in face_down if c is not a]
            if opponent:
                labeled = [f"Day {c.day} (face-down)" for c in remaining]
            else:
                labeled = [f"Day {c.day}: card {c.card_type} ({PLACES[c.card_type]})"
                           for c in remaining]
            b = self._human_pick(p, remaining, f"Pick second card from {tgt.name}", lambda c: labeled[remaining.index(c)])
        a.day, b.day = b.day, a.day
        if opponent:
            self.log(f"    swaps two of {tgt.name}'s face-down cards (blind).")
        else:
            self.log(f"    swaps own cards: {a.label()}<->{b.label()} (now on days {a.day},{b.day}).")

    def _ability_swap_arrival(self, p, require_opponent=False, require_own=False):
        # find all (day, type) groups with >=2 face-up cards
        groups = {}
        for c in self.cards:
            if c.face_up:
                groups.setdefault((c.day, c.card_type), []).append(c)
        pairs = []
        for (d, t), cs in groups.items():
            if len(cs) < 2:
                continue
            for i in range(len(cs)):
                for j in range(i+1, len(cs)):
                    a, b = cs[i], cs[j]
                    if require_opponent and not (a.owner != p.idx or b.owner != p.idx):
                        continue
                    if require_own and not (a.owner == p.idx or b.owner == p.idx):
                        continue
                    pairs.append((a, b))
        if not pairs:
            self.log("    no valid swap pair -- fizzles.")
            return
        if p.is_ai:
            # heuristic: pick swap that most helps p's score
            best = max(pairs, key=lambda ab: self._score_delta_of_swap(*ab, for_player=p.idx))
            a, b = best
        else:
            a, b = self._human_pick(p, pairs, "Pick a pair to swap arrival",
                                    lambda ab: (f"P{ab[0].owner+1} {ab[0].label()} D{ab[0].day} #{ab[0].arrival}"
                                                f"  <->  P{ab[1].owner+1} {ab[1].label()} D{ab[1].day} #{ab[1].arrival}"))
        a.arrival, b.arrival = b.arrival, a.arrival
        self.log(f"    swaps arrivals: P{a.owner+1} now #{a.arrival} and P{b.owner+1} now #{b.arrival} "
                 f"for Day {a.day} {PLACES[a.card_type]}.")

    # ---------- AI

    def _ai_pick_card(self, p, face_down):
        # Greedy: choose the play that maximizes current scoring for p minus
        # best-opponent score, under the assumption that abilities are random.
        best = None
        best_delta = None
        for c in face_down:
            delta = self._evaluate_play(p.idx, c)
            if best_delta is None or delta > best_delta:
                best_delta = delta
                best = c
        return best

    def _evaluate_play(self, pi, c):
        # simulate flipping c face up, compute score swing vs. doing nothing
        before = self._score_now()
        c.face_up = True
        c.arrival = self.next_arrival(c.day, c.card_type)
        after = self._score_now()
        c.face_up = False
        c.arrival = 0
        self.renumber(c.day, c.card_type)
        own = after[pi] - before[pi]
        opp = max(after[j] - before[j] for j in range(N_PLAYERS) if j != pi)
        return own - 0.5 * opp

    def _ai_pick_flip_target(self, p, targets, opponent):
        # flip target that most hurts leader (opp) or most helps us (self)
        best = targets[0]
        best_delta = -1e9
        for t in targets:
            was_up, was_arr = t.face_up, t.arrival
            d, ct = t.day, t.card_type
            t.face_up = False
            t.arrival = 0
            self.renumber(d, ct)
            s = self._score_now()
            t.face_up = was_up
            t.arrival = was_arr
            self.renumber(d, ct)
            if opponent:
                delta = s[p.idx] - max(s[j] for j in range(N_PLAYERS) if j != p.idx)
            else:
                delta = s[p.idx]
            if delta > best_delta:
                best_delta = delta
                best = t
        return best

    def _score_delta_of_swap(self, a, b, for_player):
        before = self._score_now()
        a.arrival, b.arrival = b.arrival, a.arrival
        after = self._score_now()
        a.arrival, b.arrival = b.arrival, a.arrival
        own = after[for_player] - before[for_player]
        opp = max(after[j] - before[j] for j in range(N_PLAYERS) if j != for_player)
        return own - 0.5 * opp

    # ---------- human input

    def _human_pick_card(self, p, face_down):
        clear_screen()
        print(f"=== {p.name}'s TURN ===")
        print(self.render_public())
        print()
        print(self.render_private(p.idx))
        print()
        print("Face-down cards you can play:")
        for i, c in enumerate(face_down):
            print(f"  [{i}] Day {c.day}  card {c.card_type} ({PLACES[c.card_type]})  "
                  f"ability: {ABILITIES[c.card_type]}")
        while True:
            raw = input("Choose card index to play: ").strip()
            try:
                return face_down[int(raw)]
            except (ValueError, IndexError):
                print("  invalid.")

    def _human_pick(self, p, options, prompt, label_fn):
        print(f"\n  {prompt}:")
        for i, o in enumerate(options):
            print(f"    [{i}] {label_fn(o)}")
        while True:
            raw = input("  > ").strip()
            try:
                return options[int(raw)]
            except (ValueError, IndexError):
                print("  invalid.")

    # ---------- scoring

    def _score_now(self):
        s = [0] * N_PLAYERS
        groups = {}
        for c in self.cards:
            if c.face_up:
                groups.setdefault((c.day, c.card_type), []).append(c)
        for (d, t), cs in groups.items():
            cs.sort(key=lambda x: x.arrival)
            solo, d1, d2, t1, t2, t3 = SCORING[t]
            if len(cs) == 1:
                s[cs[0].owner] += solo
            elif len(cs) == 2:
                s[cs[0].owner] += d1
                s[cs[1].owner] += d2
            elif len(cs) == 3:
                s[cs[0].owner] += t1
                s[cs[1].owner] += t2
                s[cs[2].owner] += t3
        return s

    def final_scores(self):
        return self._score_now()

    # ---------- run

    def run(self):
        self.setup()
        while self.turn_idx < len(self.turn_order):
            self.play_turn()
        scores = self.final_scores()
        if self.verbose:
            print("\n" + self.render_public())
            print("\n=== FINAL SCORES ===")
            for i, s in enumerate(scores):
                print(f"  Player {i+1}: {s}")
            winner = max(range(N_PLAYERS), key=lambda i: scores[i])
            print(f"  Winner: Player {winner+1}")
        return scores


def clear_screen():
    if os.environ.get("NO_CLEAR"):
        print("\n" * 3)
        return
    os.system("cls" if os.name == "nt" else "clear")


# ---------------------------------------------------------------- simulation

def simulate(n_games):
    totals = [[] for _ in range(N_PLAYERS)]
    wins = [0] * N_PLAYERS
    ties = 0
    for _ in range(n_games):
        g = Game(human_indices=(), verbose=False)
        s = g.run()
        for i, v in enumerate(s):
            totals[i].append(v)
        top = max(s)
        leaders = [i for i in range(N_PLAYERS) if s[i] == top]
        if len(leaders) == 1:
            wins[leaders[0]] += 1
        else:
            ties += 1
    print(f"Simulated {n_games} AI games.")
    for i in range(N_PLAYERS):
        xs = totals[i]
        print(f"  Player {i+1}: mean={mean(xs):.2f}  stdev={stdev(xs):.2f}  "
              f"min={min(xs)}  max={max(xs)}  wins={wins[i]}")
    print(f"  ties: {ties}")
    # per-place contribution
    print("\n(Re-running a sample game verbose for inspection is available via --all-ai)")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Don't Be the Third Wheel! prototype")
    ap.add_argument("--all-human", action="store_true", help="3 humans, hotseat")
    ap.add_argument("--all-ai", action="store_true", help="3 AIs, verbose single game")
    ap.add_argument("--sim", type=int, default=0, help="run N simulated AI games and report")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.sim > 0:
        simulate(args.sim)
        return
    if args.all_ai:
        Game(human_indices=(), seed=args.seed, verbose=True).run()
        return
    if args.all_human:
        Game(human_indices=(0, 1, 2), seed=args.seed, verbose=True).run()
        return
    # default: 1 human, 2 AI
    Game(human_indices=(0,), seed=args.seed, verbose=True).run()


if __name__ == "__main__":
    main()
