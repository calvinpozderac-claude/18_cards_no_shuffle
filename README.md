# DON'T BE THE THIRD WHEEL!
### A game of dates, strategy & sabotage — exactly 3 players

---

## OVERVIEW

Three players each hold the **same 6 cards**. Over two phases — a **card-playing phase** and a **date phase** — you jockey for position on 6 dates. Land in a cozy pair and you score big. Show up as the third wheel and you pay the price.

---

## COMPONENTS

18 cards total — 6 identical sets (one per player), color-coded by player.
Each set is cards **1 through 6**.

| Card | Type   | Action (use to trigger) | Modifier (skip to keep bonus / use to get debuff) |
|------|--------|------------------------|--------------------------------------------------|
| 1    | Bonus  | Switch any two date piles | **+1 pt** at end of game |
| 2    | Bonus  | Swap arrival order of any two cards in a pile | As 3rd wheel in MM+MM+MM: score **0** instead of −2 |
| 3    | Bonus  | Deactivate opponent's bonus **or** activate opponent's avoided debuff | **Peek** at one player's move before choosing yours this date |
| 4    | Debuff | Switch any two date piles | **−1 pt** at end of game |
| 5    | Debuff | Swap arrival order of any two cards in a pile | As 3rd wheel in MM+MM+MM: score **−4** instead of −2 |
| 6    | Debuff | Deactivate opponent's bonus **or** activate opponent's avoided debuff | **Show** your move to one player before they choose this date |

> **Both sides of each card can be used:** orient action-side-up when using the action; flip to modifier-side-up when skipping.

---

## CARD-PLAYING PHASE

Players take turns until all 18 cards are placed (6 cards × 3 players across 6 piles).

**On your turn:**
1. Pick one of your unplayed cards (1–6).
2. Place it on an existing pile you haven't played to yet, OR start a **new pile** to the far left or right.
3. Choose how to play it:
   - **Use the Action** → action triggers immediately; you **forgo** any bonus or **take on** the debuff.
   - **Skip the Action** → nothing triggers; you **keep** the bonus or **avoid** the debuff.

Your play order within a pile = your **arrival order** at that date (1st, 2nd, 3rd).

---

## DATE PHASE

Dates resolve **left to right** once all 6 piles are complete.

### Third Wheel Rule
| Pile position | Third Wheel |
|---------------|-------------|
| Piles 1–2     | 3rd arrival |
| Piles 3–4     | 2nd arrival |
| Piles 5–6     | 1st arrival |

### The Date
Each player privately and simultaneously chooses **MM** (Make a Move) or **PS** (Play it Safe).

#### Scoring Matrix (Third Wheel · Normal · Normal)

| TW  | N1  | N2  | TW  | N1  | N2  |
|-----|-----|-----|-----|-----|-----|
| PS  | PS  | PS  | 0   | +1  | +1  |
| PS  | MM  | PS  | 0   | −1  | +1  |
| PS  | PS  | MM  | 0   | +1  | −1  |
| PS  | MM  | MM  | 0   | +2  | +2  |
| MM  | PS  | PS  | −2  | +1  | +1  |
| MM  | MM  | PS  | +2  | +2  | 0   |
| MM  | PS  | MM  | +2  | 0   | +2  |
| MM  | MM  | MM  | −2* | +2  | +2  |

> *Card 2 Bonus (active): TW scores **0** · Card 5 Debuff (active): TW scores **−4**

---

## BONUSES & DEBUFFS

| Modifier | When Applied | Effect |
|----------|-------------|--------|
| Card 1 Bonus | End of game | +1 to final score |
| Card 2 Bonus | This date's resolution | TW in MM+MM+MM → 0 instead of −2 |
| Card 3 Bonus | Before choosing your move | Peek at one other player's move |
| Card 4 Debuff | End of game | −1 to final score |
| Card 5 Debuff | This date's resolution | TW in MM+MM+MM → −4 instead of −2 |
| Card 6 Debuff | Before choosing your move | Must show your move to one chosen player |

### Deactivate / Activate (Cards 3 & 6 action)
Target any **opponent's card played without action**:
- **Bonus card** → deactivate their bonus (they lose it)
- **Debuff card** → activate their debuff (they now have it even though they skipped)

---

## FINAL SCORING

Sum all per-date scores, then add Card 1 bonuses (+1 each) and Card 4 debuffs (−1 each). Highest total wins.

---

## RUNNING THE DIGITAL VERSION

```bash
# Install Flask if needed
pip install flask

# Start the server
python3 app.py
```

Open `http://localhost:5000`. Pass the device between players for private moves.

Share with remote players via ngrok:
```bash
ngrok http 5000
```
