# Don't Be the Third Wheel!

A strategic card game for 3 players — romantic scheduling, private information, and mutual sabotage.

---

## Setup

**Snake Draft:** Players take turns picking 1 strong card each from a pool of 6 (one per location). With 3 players and a snake draft, each player gets exactly 2 strong cards. Everyone then receives 1 normal card for each type they did NOT draft, giving every player 6 cards total.

Each player secretly arranges their 6 cards face-down across 6 day slots (Day 1–6). Only you can see your own arrangement.

---

## Gameplay

On your turn, do one of the following:
- **Flip** one of your face-down cards face-up (registers your arrival at that location)
- **Use your pocketed ability** (if you have one stored)

After flipping, you choose what to do with the card's ability:
- **Use Now** — resolve the ability immediately
- **Pocket for Later** — save it for a future turn (replaces any previously pocketed ability)
- **Skip** — discard the ability unused

The **Beach (ct=5) ability** is always decided immediately and cannot be pocketed.

Only one ability can be pocketed at a time.

---

## Card Types, Abilities, and Scoring

Arrival scoring applies only when 2 or more players arrive at the same location (type). Solo arrivals score 0.

### 1 — Coffee Shop
- **Strong:** Lock an entire day — all cards on that day become immune to abilities
- **Normal:** Lock 2 cards on a chosen day
- **Scoring:** 1st +1 · 2nd +2 · 3rd −1

### 2 — Park
- **Strong:** Swap any two of your own cards (day slots)
- **Normal:** Shift one of your cards to an adjacent day (wraps)
- **Scoring:** 1st +1 · 2nd +2 · 3rd −1

### 3 — Cinema
- **Strong:** Swap any two cards of one opponent
- **Normal:** Shift one opponent's card to an adjacent day (wraps)
- **Scoring:** 1st +3 · 2nd +1 · 3rd −2

### 4 — Restaurant *(arrive LAST for best score!)*
- **Strong:** Peek at 2 opponents' face-down cards (private information — only you see it)
- **Normal:** Peek at 1 opponent's face-down card
- **Scoring:** 1st −1 · 2nd +1 · 3rd +3

### 5 — Beach
- **Strong:** Bank +2 pts now (opt out of arrival scoring and day-match bonus)
- **Normal:** Bank +1 pt now
- **Scoring:** 1st +5 · 2nd +3 · 3rd −4

### 6 — Museum
- **Strong:** Flip one of your own face-up cards back down
- **Normal:** Flip an opponent's face-up card down
- **Scoring:** 1st +3 · 2nd +1 · 3rd ±0

---

## Arrival Queue

Arrival queues are **global per card type** (not per day). The first player to flip a given type is 1st in that type's global queue, regardless of which day slot the card occupies.

Points are awarded when 2 or more players arrive at the same location type.

---

## Day-Match Bonus

If your card of type N is placed on Day N AND is face-up at game end (and not banked):
- If 2 or more players match on that day: **+2 pts** (normal card) or **+1 pt** (strong card)
- If only 1 player matches that day: **−1 pt**

---

## End of Game

The game ends when all 18 cards are face-up.

**Final score = arrival points + day-match bonuses + banked points**

Highest score wins.

---

## Running the Digital Version

```
pip install flask
python3 app.py
# Visit http://localhost:5000
```

Players on separate devices can use the room code system to find each other without sharing URLs directly.
