# DON'T BE THE THIRD WHEEL!
### A game of romantic scheduling and strategic sabotage — 2–3 players

---

## OVERVIEW
Each player is juggling six potential dates across six days. Everyone shares the same six locations, but the timing is everything. Show up to a date with exactly one other person and it's romantic — show up as a third wheel and suffer the consequences.

---

## COMPONENTS
- 18 cards (6 identical sets of locations 1–6)
- This manual

**The six locations:**

| # | Location |
|---|----------|
| 1 | Coffee Shop |
| 2 | Park |
| 3 | Cinema |
| 4 | Restaurant |
| 5 | Beach |
| 6 | Museum |

---

## SETUP
1. Each player takes one full set of cards (1–6) and, **secretly**, arranges them face-down in a row of six slots. Each slot is a **Day** (Day 1 through Day 6). Each location goes to exactly one day.
2. Once all players have locked in their schedules, reveal nothing — cards stay face-down.
3. Randomly determine who goes first.

---

## ON YOUR TURN
Flip one of your **face-down** cards **face-up**. This represents you showing up to that date.

**Arrival position** is tracked per location per day:
- **1st to arrive** → card is placed *above* your row
- **2nd to arrive** → card stays *in line*
- **3rd to arrive** → card is placed *below* your row

After flipping, immediately resolve that card's ability (see below), then play passes clockwise.

---

## CARD ABILITIES
Each location has a special ability that triggers the moment you flip it.

| # | Location | Ability |
|---|----------|---------|
| 1 | Coffee Shop | Flip one of **another player's** face-up cards face-down |
| 2 | Park | Flip one of **your own** face-up cards face-down |
| 3 | Cinema | Swap the Day slots of two cards belonging to **another player** |
| 4 | Restaurant | Swap the Day slots of **two of your own** cards |
| 5 | Beach | Change the arrival order of one of **an opponent's** face-up cards |
| 6 | Museum | Change the arrival order of one of **your own** face-up cards |

If a card's ability has no valid target, it is skipped.

---

## END OF GAME
The game ends when all cards have been flipped face-up. Score every location/day combination where **more than one player** showed up.

| Players at same location on same day | 1st arrival | 2nd arrival | 3rd arrival |
|--------------------------------------|------------|-------------|-------------|
| **2 players** | +1 pt | +2 pts | — |
| **3 players** | 0 pts | 0 pts | **−1 pt** |
| **1 player** | No points | — | — |

The player with the **most points** wins. In a tie, the player with the most successful 2-person dates wins.

---

## TIPS
- Being **second** to a 2-person date is better than being first — but only if no one else shows up.
- Use abilities to break up rivals' dates or rescue yourself from a third-wheel situation.
- Your opponents can see which of your cards are face-up, but not what's still hidden — plan accordingly.

---

## RUNNING THE DIGITAL VERSION

**Desktop (tkinter):**
```bash
python3 game.py
```

**Web (Flask + ngrok):**
```bash
# Install dependencies
pip install flask

# Start the server
python3 app.py

# In a second terminal, expose it publicly
ngrok http 5000
```
Share the ngrok URL with your players. All players use the same URL and pass the device for their turn.
