import copy
import threading
import uuid
import random
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
app.secret_key = "dtbtw-ai-secret-2024"

GAMES = {}

# ── room lobby ────────────────────────────────────────────────────────────────
# Rooms allow players on separate devices to find each other via a 3-digit code
# before the underlying game is created.

ROOMS: dict = {}
ROOMS_LOCK = threading.Lock()


def _gen_room_code() -> str:
    for _ in range(2000):
        code = f"{random.randint(100, 999)}"
        if code not in ROOMS:
            return code
    raise RuntimeError("Room namespace exhausted")


def _room_view(room: dict, lobby_token: str) -> dict:
    """Serialise room state for a particular lobby participant."""
    my_idx = next((i for i, p in enumerate(room["players"])
                   if p["lobby_token"] == lobby_token), None)
    my_game_url = None
    if room["game_id"] and my_idx is not None:
        gt = room["players"][my_idx].get("game_token")
        if gt:
            my_game_url = f"/game/{room['game_id']}/{gt}"
    return {
        "room_code":   room["code"],
        "status":      room["status"],
        "is_host":     room["host_token"] == lobby_token,
        "my_idx":      my_idx,
        "my_game_url": my_game_url,
        "version":     room["version"],
        "players": [
            {
                "name":        p["name"],
                "is_ai":       p["is_ai"],
                "ai_type":     p.get("ai_type"),
                "ai_rollouts": p.get("ai_rollouts", 50),
                "is_me":       p["lobby_token"] == lobby_token,
                "player_id":   p["lobby_token"],
            }
            for p in room["players"]
        ],
    }

LOCATION_NAMES = {
    1: "Coffee Shop",
    2: "Park",
    3: "Cinema",
    4: "Restaurant",
    5: "Beach",
    6: "Museum",
}

# Rule 2: per-card-type point distributions (1st-arrival pts, 2nd, 3rd)
CARD_PTS = {
    1: (1, 2, -1),   # Coffee Shop  — late arrival best
    2: (1, 2, -1),   # Park         — late arrival best
    3: (2, 1, -1),   # Cinema       — early arrival best
    4: (4, 2, -2),   # Restaurant   — early arrival best, big swings
    5: (3, 3, -2),   # Beach        — 1st = 2nd, third wheel brutal
    6: (1, 1,  0),   # Museum       — flat, no third-wheel penalty
}

# ── core game logic ───────────────────────────────────────────────────────────

def _card_at(player, day):
    return player["cards"][day - 1] if 1 <= day <= 6 else None

def _key(day, ct):
    return f"{day},{ct}"

def _renumber(state, day, ct):
    for i, pidx in enumerate(state["arrivals"].get(_key(day, ct), [])):
        _card_at(state["players"][pidx], day)["arrival"] = i + 1

def _is_locked(state, pidx, day):
    """Check if [pidx, day-1] is in state['locks'] (day is 1-based)."""
    return [pidx, day - 1] in state.get("locks", [])

def _flip_up(state, pidx, day):
    card = _card_at(state["players"][pidx], day)
    if not card or card["face_up"]:
        return False
    card["face_up"] = True
    k = _key(day, card["card_type"])
    state["arrivals"].setdefault(k, []).append(pidx)
    card["arrival"] = len(state["arrivals"][k])
    return True

def _flip_down(state, pidx, day):
    card = _card_at(state["players"][pidx], day)
    if not card or not card["face_up"]:
        return False
    if _is_locked(state, pidx, day):
        return False
    k = _key(day, card["card_type"])
    arr = state["arrivals"].get(k, [])
    if pidx in arr:
        arr.remove(pidx)
        state["arrivals"][k] = arr
        _renumber(state, day, card["card_type"])
    card["face_up"] = False
    card["arrival"] = 0
    card["banked"] = False  # unbank when flipped down
    return True

def _swap_days(state, pidx, day1, day2):
    if _is_locked(state, pidx, day1) or _is_locked(state, pidx, day2):
        return False
    player = state["players"][pidx]
    c1, c2 = _card_at(player, day1), _card_at(player, day2)
    if not c1 or not c2 or day1 == day2:
        return False
    for day, card in [(day1, c1), (day2, c2)]:
        if card["face_up"]:
            k = _key(day, card["card_type"])
            arr = state["arrivals"].get(k, [])
            if pidx in arr:
                arr.remove(pidx)
                state["arrivals"][k] = arr
                _renumber(state, day, card["card_type"])
    player["cards"][day1 - 1], player["cards"][day2 - 1] = (
        player["cards"][day2 - 1], player["cards"][day1 - 1],
    )
    for day, card in [(day1, c2), (day2, c1)]:
        if card["face_up"]:
            k = _key(day, card["card_type"])
            state["arrivals"].setdefault(k, []).append(pidx)
            card["arrival"] = len(state["arrivals"][k])
    return True

def _change_arrival(state, pidx, day, new_pos):
    card = _card_at(state["players"][pidx], day)
    if not card or not card["face_up"]:
        return False
    k = _key(day, card["card_type"])
    arr = state["arrivals"].get(k, [])
    if pidx not in arr:
        return False
    new_pos = max(1, min(new_pos, len(arr)))
    arr.remove(pidx)
    arr.insert(new_pos - 1, pidx)
    state["arrivals"][k] = arr
    _renumber(state, day, card["card_type"])
    return True

def _check_game_over(state):
    if all(c["face_up"] for p in state["players"] for c in p["cards"]):
        state["game_over"] = True
        state["phase"] = "end"
    return state["game_over"]

def _advance_turn(state):
    n = len(state["players"])
    state["turn_count"] += 1
    state["current_player_idx"] = (state["current_player_idx"] + 1) % n
    if _check_game_over(state):
        return
    skips = 0
    while (
        all(c["face_up"] for c in state["players"][state["current_player_idx"]]["cards"])
        and skips < n
    ):
        state["turn_count"] += 1
        state["current_player_idx"] = (state["current_player_idx"] + 1) % n
        skips += 1
        if _check_game_over(state):
            return

def _calculate_scores(state):
    scores = {p["name"]: 0 for p in state["players"]}

    # Base arrival scoring
    for k, arr in state["arrivals"].items():
        n = len(arr)
        if n < 2:
            continue
        _, ct = (int(v) for v in k.split(","))
        pts = CARD_PTS[ct]
        for i, pidx in enumerate(arr[:3]):
            if i < len(pts):
                scores[state["players"][pidx]["name"]] += pts[i]

    # Day-matching bonus: type N on day N
    for ct in range(1, 7):
        # Players whose type-ct card is on day ct (day_index = ct-1) and not banked
        matching_players = []
        for pidx, player in enumerate(state["players"]):
            card = player["cards"][ct - 1]  # day ct is index ct-1
            if card and card.get("card_type") == ct and card.get("face_up") and not card.get("banked"):
                matching_players.append((pidx, card.get("strength", "normal")))

        if len(matching_players) == 1:
            pidx, _ = matching_players[0]
            scores[state["players"][pidx]["name"]] -= 1
        elif len(matching_players) >= 2:
            for pidx, strength in matching_players:
                bonus = 1 if strength == "strong" else 2
                scores[state["players"][pidx]["name"]] += bonus

    # Bank points
    for pidx, player in enumerate(state["players"]):
        for card in player["cards"]:
            if card and card.get("banked") and card.get("face_up"):
                pts = 2 if card.get("strength") == "strong" else 1
                scores[player["name"]] += pts

    return scores

def _arrivals_display(state):
    rows = []
    for k, arr in sorted(state["arrivals"].items(),
                         key=lambda x: [int(v) for v in x[0].split(",")]):
        day, ct = (int(v) for v in k.split(","))
        rows.append({
            "day": day, "card_type": ct,
            "location": LOCATION_NAMES[ct],
            "players": [state["players"][pi]["name"] for pi in arr],
            "n": len(arr),
        })
    return rows

def _new_state(player_names):
    n = len(player_names)
    # Build snake draft order
    draft_order = list(range(n)) + list(range(n - 1, -1, -1))
    # Shuffle the 6 strong cards in draft pool
    draft_pool = [{"card_type": ct, "strength": "strong"} for ct in range(1, 7)]
    random.shuffle(draft_pool)
    return {
        "phase": "draft",
        "players": [{"name": name, "cards": [], "arranged": False, "draft_cards": []}
                    for name in player_names],
        "current_player_idx": 0,
        "turn_count": 0,
        "arrivals": {},
        "pending_action": None,
        "action_ctx": {},
        "action_message": None,
        "game_over": False,
        "move_log": [],
        "ai_players": [],
        "ai_difficulty": None,
        "ai_difficulties": {},
        "draft_pool": draft_pool,
        "draft_order": draft_order,
        "draft_pick_idx": 0,
        "locks": [],
    }

def _assign_normal_cards(state):
    """After draft: each player gets 1 normal card for each type they didn't draft."""
    n = len(state["players"])
    for ct in range(1, 7):
        # Find who drafted this strong type
        drafter_idx = None
        for i, p in enumerate(state["players"]):
            if any(c["card_type"] == ct for c in p.get("draft_cards", [])):
                drafter_idx = i
                break
        # Everyone except the drafter gets a normal card of this type
        for pidx in range(n):
            if pidx != drafter_idx:
                state["players"][pidx].setdefault("draft_cards", []).append(
                    {"card_type": ct, "strength": "normal"}
                )
    state["phase"] = "arrangement"
    state["current_player_idx"] = 0

def _state_for_player(game, my_pidx):
    state = game["state"]
    players_out = []
    for i, player in enumerate(state["players"]):
        p = {"name": player["name"], "arranged": player.get("arranged", False),
             "is_me": i == my_pidx, "cards": []}

        if state["phase"] == "draft":
            # In draft phase: expose draft_cards for self
            p["draft_cards"] = player.get("draft_cards", []) if i == my_pidx else []
            # cards is empty during draft
        elif state["phase"] in ("arrangement", "game", "end"):
            # Always expose draft_cards for self (needed for arrangement screen)
            if i == my_pidx:
                p["draft_cards"] = player.get("draft_cards", [])

        if state["phase"] == "arrangement":
            # Show own cards with strength, hide opponents
            for c in player["cards"]:
                if i == my_pidx or c["face_up"]:
                    card_copy = dict(c)
                    p["cards"].append(card_copy)
                else:
                    p["cards"].append({"card_type": None, "face_up": False, "arrival": 0, "strength": None})
        else:
            # game/end phase
            for c in player["cards"]:
                if i == my_pidx or c["face_up"]:
                    card_copy = dict(c)
                    # Include strength and banked for face-up cards
                    p["cards"].append(card_copy)
                else:
                    p["cards"].append({"card_type": None, "face_up": False, "arrival": 0, "strength": None, "banked": False})

        players_out.append(p)

    out = {
        "phase": state["phase"],
        "players": players_out,
        "my_player_idx": my_pidx,
        "current_player_idx": state["current_player_idx"],
        "turn_count": state["turn_count"],
        "arrivals": state["arrivals"],
        "pending_action": state["pending_action"],
        "action_ctx": state["action_ctx"],
        "action_message": state["action_message"],
        "game_over": state["game_over"],
        "num_players": len(state["players"]),
        "ai_players": state.get("ai_players", []),
        "ai_difficulty": state.get("ai_difficulty"),
        "ai_difficulties": {str(k): v for k, v in state.get("ai_difficulties", {}).items()},
        "move_log": state.get("move_log", []),
        "locks": state.get("locks", []),
    }

    # Draft phase extras
    if state["phase"] == "draft":
        out["draft_pool"] = state.get("draft_pool", [])
        out["draft_order"] = state.get("draft_order", [])
        out["draft_pick_idx"] = state.get("draft_pick_idx", 0)

    if state["phase"] in ("game", "end"):
        out["scores"] = _calculate_scores(state)
        out["arrivals_display"] = _arrivals_display(state)

    return out

def _get_pidx(game, token):
    try:
        return game["tokens"].index(token)
    except ValueError:
        return None

def _log(state, msg):
    state.setdefault("move_log", []).insert(0, msg)
    if len(state["move_log"]) > 100:
        state["move_log"] = state["move_log"][:100]

# ── draft helpers ─────────────────────────────────────────────────────────────

def _process_draft_picks(game):
    """Auto-play consecutive AI draft picks until a human's turn or draft done."""
    state = game["state"]
    if state["phase"] != "draft":
        return
    ai_set = set(state.get("ai_players", []))
    limit = 20
    i = 0
    while (
        state["phase"] == "draft"
        and state["draft_pick_idx"] < len(state["draft_order"])
        and i < limit
    ):
        cur_drafter = state["draft_order"][state["draft_pick_idx"]]
        if cur_drafter not in ai_set:
            break
        # AI auto-picks randomly from draft pool
        pool = state["draft_pool"]
        if not pool:
            break
        pick = random.choice(pool)
        _do_draft_pick(state, cur_drafter, pick["card_type"])
        i += 1
    # If draft complete, assign normal cards and process AI arrangements
    if state["phase"] == "arrangement":
        _process_ai_arrangements(game)

def _do_draft_pick(state, pidx, card_type):
    """Execute a single draft pick. Returns True if successful."""
    pool = state["draft_pool"]
    picked = next((c for c in pool if c["card_type"] == card_type), None)
    if not picked:
        return False
    pool.remove(picked)
    state["players"][pidx].setdefault("draft_cards", []).append(
        {"card_type": card_type, "strength": "strong"}
    )
    state["draft_pick_idx"] += 1
    _log(state, f"{state['players'][pidx]['name']} drafted strong {LOCATION_NAMES[card_type]}")
    # Check if draft complete
    if state["draft_pick_idx"] >= len(state["draft_order"]):
        _assign_normal_cards(state)
    return True

def _process_ai_arrangements(game):
    """Auto-arrange all AI players that haven't arranged yet."""
    state = game["state"]
    if state["phase"] != "arrangement":
        return
    ai_set = set(state.get("ai_players", []))
    for ai_pidx in ai_set:
        player = state["players"][ai_pidx]
        if not player.get("arranged"):
            assignment = _ai_arrange(player.get("draft_cards", []))
            cards = [None] * 6
            for ct, day in assignment.items():
                strength = next(
                    c["strength"] for c in player["draft_cards"] if c["card_type"] == ct
                )
                cards[day - 1] = {
                    "card_type": ct, "face_up": False, "arrival": 0,
                    "strength": strength, "banked": False
                }
            player["cards"] = cards
            player["arranged"] = True
    if all(p["arranged"] for p in state["players"]):
        state["phase"] = "game"

# ── rollout helpers (no logging — used by MCTS) ───────────────────────────────

def _rollout_ability(state, pidx, ct, strength, difficulty="random", current_day=None):
    """Resolve a card ability without logging, for use in rollout simulations."""
    if ct == 1:  # Lock
        day = random.randint(1, 6)
        if strength == "strong":
            for pi in range(len(state["players"])):
                di = day - 1
                if [pi, di] not in state["locks"]:
                    state["locks"].append([pi, di])
        else:
            candidates = [[pi, day - 1] for pi in range(len(state["players"]))]
            for item in random.sample(candidates, min(2, len(candidates))):
                if item not in state["locks"]:
                    state["locks"].append(item)

    elif ct == 2:  # Swap own
        if strength == "strong":
            d1, d2 = random.sample(range(1, 7), 2)
            if not _is_locked(state, pidx, d1) and not _is_locked(state, pidx, d2):
                _swap_days(state, pidx, d1, d2)
        else:
            day = random.choice(list(range(1, 7)))
            adj = [(day - 2) % 6 + 1, day % 6 + 1]
            tday = random.choice(adj)
            if not _is_locked(state, pidx, day) and not _is_locked(state, pidx, tday):
                _swap_days(state, pidx, day, tday)

    elif ct == 3:  # Swap others
        opponents = [pi for pi in range(len(state["players"])) if pi != pidx]
        if opponents:
            tpi = random.choice(opponents)
            if strength == "strong":
                d1, d2 = random.sample(range(1, 7), 2)
                if not _is_locked(state, tpi, d1) and not _is_locked(state, tpi, d2):
                    _swap_days(state, tpi, d1, d2)
            else:
                day = random.choice(list(range(1, 7)))
                adj = [(day - 2) % 6 + 1, day % 6 + 1]
                tday = random.choice(adj)
                if not _is_locked(state, tpi, day) and not _is_locked(state, tpi, tday):
                    _swap_days(state, tpi, day, tday)

    elif ct == 4:  # Switch arrival order
        all_slots = [
            (int(d_str), int(c_str))
            for k in state["arrivals"]
            for d_str, c_str in [k.split(",")]
            if len(state["arrivals"][k]) >= 2
        ]
        if all_slots:
            d, c = random.choice(all_slots)
            arr = state["arrivals"][f"{d},{c}"]
            if strength == "strong":
                random.shuffle(arr)
                _renumber(state, d, c)
            else:
                if len(arr) >= 2:
                    i, j = random.sample(range(len(arr)), 2)
                    arr[i], arr[j] = arr[j], arr[i]
                    _renumber(state, d, c)

    elif ct == 5:  # Bank points (AI auto-decide)
        player_cards = state["players"][pidx]["cards"]
        for idx, card in enumerate(player_cards):
            if card and card.get("card_type") == 5 and card.get("face_up") and not card.get("banked"):
                bank_pts = 2 if strength == "strong" else 1
                day = idx + 1
                k = f"{day},{5}"
                arr = state["arrivals"].get(k, [])
                arrival_val = CARD_PTS[5][len(arr) - 1] if arr else 0
                if bank_pts > arrival_val:
                    card["banked"] = True
                break

    elif ct == 6:  # Flip down
        if strength == "strong":
            # Exclude the card just flipped (current_day) to avoid immediate re-flip
            targets = [
                (d + 1, c) for d, c in enumerate(state["players"][pidx]["cards"])
                if c and c["face_up"] and not _is_locked(state, pidx, d + 1)
                and (d + 1) != current_day
            ]
            if not targets:
                # Fall back to including all face-up cards
                targets = [
                    (d + 1, c) for d, c in enumerate(state["players"][pidx]["cards"])
                    if c and c["face_up"] and not _is_locked(state, pidx, d + 1)
                ]
            if targets:
                d, _ = random.choice(targets)
                _flip_down(state, pidx, d)
        else:
            opp_targets = [
                (pi, d + 1) for pi in range(len(state["players"])) if pi != pidx
                for d, c in enumerate(state["players"][pi]["cards"])
                if c and c["face_up"] and not _is_locked(state, pi, d + 1)
            ]
            if opp_targets:
                tpi, td = random.choice(opp_targets)
                _flip_down(state, tpi, td)


def _rollout_take_turn(state):
    """Play one random turn in a rollout simulation (no logging)."""
    if state["phase"] != "game":
        return
    pidx = state["current_player_idx"]
    player = state["players"][pidx]
    candidates = [d + 1 for d, c in enumerate(player["cards"]) if not c["face_up"]]
    if not candidates:
        _advance_turn(state)
        return
    day = random.choice(candidates)
    _flip_up(state, pidx, day)
    card = player["cards"][day - 1]
    ct = card["card_type"]
    strength = card.get("strength", "normal")
    _rollout_ability(state, pidx, ct, strength, "random", current_day=day)
    _advance_turn(state)


def _determinize_state(state, observing_pidx):
    """Return a deep copy of state with opponents' face-down card types randomized."""
    s = copy.deepcopy(state)
    for pi, player in enumerate(s["players"]):
        if pi == observing_pidx:
            continue
        known = {c["card_type"] for c in player["cards"] if c["face_up"]}
        hidden_slots = [i for i, c in enumerate(player["cards"]) if not c["face_up"]]
        if not hidden_slots:
            continue
        unknown_types = [t for t in range(1, 7) if t not in known]
        random.shuffle(unknown_types)
        for slot_i, card_i in enumerate(hidden_slots):
            player["cards"][card_i]["card_type"] = unknown_types[slot_i % len(unknown_types)]
    return s


def _mcts_flip_decision(state, pidx, rollouts):
    """Flat Monte Carlo: score each candidate flip with N random playouts. Returns best day."""
    player = state["players"][pidx]
    candidates = [d + 1 for d, c in enumerate(player["cards"]) if not c["face_up"]]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    n_per = max(1, rollouts // len(candidates))
    totals = {d: 0.0 for d in candidates}
    my_name = player["name"]

    for d in candidates:
        for _ in range(n_per):
            sim = _determinize_state(state, pidx)
            _flip_up(sim, pidx, d)
            card = sim["players"][pidx]["cards"][d - 1]
            ct = card["card_type"]
            strength = card.get("strength", "normal")
            _rollout_ability(sim, pidx, ct, strength, "basic", current_day=d)
            _advance_turn(sim)
            steps = 0
            while sim["phase"] == "game" and steps < 30:
                _rollout_take_turn(sim)
                steps += 1
            totals[d] += _calculate_scores(sim).get(my_name, 0)

    return max(candidates, key=lambda d: totals[d])


# ── AI logic ──────────────────────────────────────────────────────────────────

def _ai_arrange(player_draft_cards):
    """Assign cards to days with bias toward matching day (type N on day N)."""
    cards_info = list(player_draft_cards)
    days = list(range(1, 7))

    assignment = {}
    taken_days = set()

    # Greedy: assign matching days first
    for card in cards_info:
        ct = card["card_type"]
        if ct not in taken_days:  # day ct is open
            assignment[ct] = ct
            taken_days.add(ct)

    # Assign remaining randomly
    remaining_cards = [c["card_type"] for c in cards_info if c["card_type"] not in assignment]
    remaining_days = [d for d in days if d not in taken_days]
    random.shuffle(remaining_days)
    for ct, day in zip(remaining_cards, remaining_days):
        assignment[ct] = day

    return assignment


def _ai_pick_flip(state, pidx, difficulty):
    """Choose a face-down card to flip. Returns day number."""
    player = state["players"][pidx]
    candidates = [d + 1 for d, c in enumerate(player["cards"]) if not c["face_up"]]
    if not candidates:
        return None
    if difficulty == "random":
        return random.choice(candidates)

    def ct(d): return _card_at(player, d)["card_type"]
    def n_arr(d): return len(state["arrivals"].get(_key(d, ct(d)), []))

    # Hard-veto: would become 3rd at cards with pts[2] <= -2 (Restaurant, Beach)
    non_veto = [d for d in candidates if not (n_arr(d) >= 2 and CARD_PTS[ct(d)][2] <= -2)]
    pool = non_veto if non_veto else candidates

    # Priority 1: Beach 2nd arrival (+3)
    beach_2nd = [d for d in pool if ct(d) == 5 and n_arr(d) == 1]
    if beach_2nd: return random.choice(beach_2nd)

    # Priority 2: Restaurant 1st arrival (+4)
    rest_1st = [d for d in pool if ct(d) == 4 and n_arr(d) == 0]
    if rest_1st: return random.choice(rest_1st)

    # Priority 3: Restaurant 2nd arrival (+2)
    rest_2nd = [d for d in pool if ct(d) == 4 and n_arr(d) == 1]
    if rest_2nd: return random.choice(rest_2nd)

    # Priority 4: Cinema 1st (+2) or Coffee Shop/Park 2nd (+2)
    good = [d for d in pool
            if (ct(d) == 3 and n_arr(d) == 0) or (ct(d) in (1, 2) and n_arr(d) == 1)]
    if good: return random.choice(good)

    # Priority 5: any 2nd arrival
    second = [d for d in pool if n_arr(d) == 1]
    if second: return random.choice(second)

    safe = [d for d in pool if n_arr(d) == 0]
    return random.choice(safe) if safe else random.choice(pool)


# ── AI ability helpers for new card types ────────────────────────────────────

def _ai_lock_target(state, pidx, strength, difficulty):
    """Type 1 Lock: pick a day to lock. Returns day (1-6)."""
    if difficulty == "random":
        return random.randint(1, 6)
    # Basic: lock the day where our highest-scoring face-up card is
    player = state["players"][pidx]
    best_day, best_val = None, -999
    for d, c in enumerate(player["cards"]):
        if c and c["face_up"]:
            day = d + 1
            ct = c["card_type"]
            arr = state["arrivals"].get(_key(day, ct), [])
            pts = CARD_PTS[ct]
            val = pts[c["arrival"] - 1] if 0 <= c["arrival"] - 1 < len(pts) else 0
            if val > best_val:
                best_val, best_day = val, day
    return best_day if best_day else random.randint(1, 6)


def _ai_swap_own_adj_target(state, pidx, difficulty):
    """Type 2 normal: pick own card and adjacent day. Returns (day, tday)."""
    player = state["players"][pidx]
    candidates = [
        d + 1 for d, c in enumerate(player["cards"])
        if not _is_locked(state, pidx, d + 1)
    ]
    if not candidates:
        return None, None
    day = random.choice(candidates)
    adj = [(day - 2) % 6 + 1, day % 6 + 1]
    unlocked_adj = [a for a in adj if not _is_locked(state, pidx, a)]
    if not unlocked_adj:
        return None, None
    tday = random.choice(unlocked_adj)
    return day, tday


def _ai_swap_other_strong_target(state, pidx, difficulty):
    """Type 3 strong: pick opponent and 2 days. Returns (tpi, d1, d2)."""
    opponents = [pi for pi in range(len(state["players"])) if pi != pidx]
    if not opponents:
        return None, None, None
    tpi = random.choice(opponents)
    unlocked = [d + 1 for d in range(6) if not _is_locked(state, tpi, d + 1)]
    if len(unlocked) < 2:
        return None, None, None
    d1, d2 = random.sample(unlocked, 2)
    return tpi, d1, d2


def _ai_swap_other_adj_target(state, pidx, difficulty):
    """Type 3 normal: pick opponent card and adjacent day. Returns (tpi, day, tday)."""
    opponents = [pi for pi in range(len(state["players"])) if pi != pidx]
    if not opponents:
        return None, None, None
    tpi = random.choice(opponents)
    candidates = [
        d + 1 for d in range(6)
        if not _is_locked(state, tpi, d + 1)
    ]
    if not candidates:
        return None, None, None
    day = random.choice(candidates)
    adj = [(day - 2) % 6 + 1, day % 6 + 1]
    unlocked_adj = [a for a in adj if not _is_locked(state, tpi, a)]
    if not unlocked_adj:
        return None, None, None
    tday = random.choice(unlocked_adj)
    return tpi, day, tday


def _ai_switch_arrival_target(state, pidx, strength, difficulty):
    """Type 4: pick (day, ct) slot with 2+ arrivals. Returns (day, ct) or (None, None)."""
    all_slots = [
        (int(d_str), int(c_str))
        for k in state["arrivals"]
        for d_str, c_str in [k.split(",")]
        if len(state["arrivals"][k]) >= 2
    ]
    if not all_slots:
        return None, None
    return random.choice(all_slots)


def _ai_flip_down_strong_target(state, pidx, difficulty, exclude_day=None):
    """Type 6 strong: flip own face-up card. Returns day or None.
    exclude_day: the day just flipped (avoid flipping it back down immediately)."""
    targets = [
        d + 1 for d, c in enumerate(state["players"][pidx]["cards"])
        if c and c["face_up"] and not _is_locked(state, pidx, d + 1)
        and (d + 1) != exclude_day
    ]
    if not targets:
        # If no other target, allow the just-flipped card as last resort
        targets = [
            d + 1 for d, c in enumerate(state["players"][pidx]["cards"])
            if c and c["face_up"] and not _is_locked(state, pidx, d + 1)
        ]
    if not targets:
        return None
    if difficulty == "random":
        return random.choice(targets)
    # Basic: flip own card with worst current score
    player = state["players"][pidx]
    scored = []
    for d in targets:
        c = _card_at(player, d)
        ct = c["card_type"]
        arr = state["arrivals"].get(_key(d, ct), [])
        pts = CARD_PTS[ct]
        val = pts[c["arrival"] - 1] if 0 <= c["arrival"] - 1 < len(pts) else 0
        scored.append((val, d))
    scored.sort()
    worst_val = scored[0][0]
    if worst_val < 1:
        return random.choice([d for v, d in scored if v == worst_val])
    return random.choice(targets)


def _ai_flip_down_normal_target(state, pidx, difficulty):
    """Type 6 normal: flip opponent face-up card. Returns (tpi, day) or (None, None)."""
    targets = [
        (pi, d + 1)
        for pi in range(len(state["players"])) if pi != pidx
        for d, c in enumerate(state["players"][pi]["cards"])
        if c and c["face_up"] and not _is_locked(state, pi, d + 1)
    ]
    if not targets:
        return None, None
    if difficulty == "random":
        return random.choice(targets)
    # Basic: target opponent's best-scoring face-up card
    best, best_val = None, -999
    for tpi, tday in targets:
        c = _card_at(state["players"][tpi], tday)
        ct = c["card_type"]
        pts = CARD_PTS[ct]
        val = pts[c["arrival"] - 1] if 0 <= c["arrival"] - 1 < len(pts) else 0
        if val > best_val:
            best_val, best = val, (tpi, tday)
    return best if best else random.choice(targets)


def _ai_take_turn(game):
    """Execute one complete AI turn: flip + resolve ability in one shot."""
    state = game["state"]
    pidx = state["current_player_idx"]
    ai_diffs = state.get("ai_difficulties", {})
    diff_str = ai_diffs.get(str(pidx)) or state.get("ai_difficulty", "random") or "random"

    is_mcts = diff_str.startswith("mcts:")
    if is_mcts:
        rollouts = int(diff_str.split(":")[1])
        difficulty = "basic"
    else:
        difficulty = diff_str

    player = state["players"][pidx]
    pname = player["name"]

    day = _mcts_flip_decision(state, pidx, rollouts) if is_mcts else _ai_pick_flip(state, pidx, difficulty)
    if day is None:
        _advance_turn(state)
        return

    _flip_up(state, pidx, day)
    card = player["cards"][day - 1]
    ct = card["card_type"]
    strength = card.get("strength", "normal")
    arr_label = {1: "1st", 2: "2nd", 3: "3rd"}.get(card["arrival"], f"#{card['arrival']}")
    strength_label = "★" if strength == "strong" else ""
    _log(state, f"{pname} flipped {strength_label}{LOCATION_NAMES[ct]} on Day {day} — {arr_label} to arrive")

    if ct == 1:  # Lock
        day_to_lock = _ai_lock_target(state, pidx, strength, difficulty)
        if strength == "strong":
            for pi in range(len(state["players"])):
                di = day_to_lock - 1
                if [pi, di] not in state["locks"]:
                    state["locks"].append([pi, di])
            _log(state, f"↳ {pname} used Lock (strong): locked all cards on Day {day_to_lock}")
        else:
            locked_cards = []
            candidates = [[pi, day_to_lock - 1] for pi in range(len(state["players"]))]
            for item in random.sample(candidates, min(2, len(candidates))):
                if item not in state["locks"]:
                    state["locks"].append(item)
                    locked_cards.append(f"{state['players'][item[0]]['name']} Day {day_to_lock}")
            _log(state, f"↳ {pname} used Lock (normal): locked {', '.join(locked_cards)} on Day {day_to_lock}")

    elif ct == 2:  # Swap own
        if strength == "strong":
            unlocked = [d + 1 for d in range(6) if not _is_locked(state, pidx, d + 1)]
            if len(unlocked) >= 2:
                d1, d2 = random.sample(unlocked, 2)
                _swap_days(state, pidx, d1, d2)
                _log(state, f"↳ {pname} used Swap Own (strong): swapped Day {d1} ↔ Day {d2}")
        else:
            day_s, tday_s = _ai_swap_own_adj_target(state, pidx, difficulty)
            if day_s is not None:
                _swap_days(state, pidx, day_s, tday_s)
                _log(state, f"↳ {pname} used Swap Own (normal): shifted Day {day_s} → Day {tday_s}")

    elif ct == 3:  # Swap others
        if strength == "strong":
            tpi, d1, d2 = _ai_swap_other_strong_target(state, pidx, difficulty)
            if tpi is not None:
                _swap_days(state, tpi, d1, d2)
                _log(state, f"↳ {pname} used Swap Others (strong): swapped {state['players'][tpi]['name']}'s Day {d1} ↔ Day {d2}")
        else:
            tpi, day_s, tday_s = _ai_swap_other_adj_target(state, pidx, difficulty)
            if tpi is not None:
                _swap_days(state, tpi, day_s, tday_s)
                _log(state, f"↳ {pname} used Swap Others (normal): shifted {state['players'][tpi]['name']}'s Day {day_s} → Day {tday_s}")

    elif ct == 4:  # Switch arrival order
        slot_day, slot_ct = _ai_switch_arrival_target(state, pidx, strength, difficulty)
        if slot_day is not None:
            arr = state["arrivals"].get(f"{slot_day},{slot_ct}", [])
            if strength == "strong":
                random.shuffle(arr)
                _renumber(state, slot_day, slot_ct)
                _log(state, f"↳ {pname} used Switch Arrival (strong): reordered {LOCATION_NAMES[slot_ct]} on Day {slot_day}")
            else:
                if len(arr) >= 2:
                    i, j = random.sample(range(len(arr)), 2)
                    arr[i], arr[j] = arr[j], arr[i]
                    _renumber(state, slot_day, slot_ct)
                    _log(state, f"↳ {pname} used Switch Arrival (normal): swapped arrivals at {LOCATION_NAMES[slot_ct]} Day {slot_day}")

    elif ct == 5:  # Bank points — AI auto-decide
        bank_pts = 2 if strength == "strong" else 1
        k = f"{day},{5}"
        arr = state["arrivals"].get(k, [])
        arrival_val = CARD_PTS[5][len(arr) - 1] if arr else 0
        if bank_pts > arrival_val:
            card["banked"] = True
            _log(state, f"↳ {pname} banked Beach card (+{bank_pts} pts)")
        else:
            card["banked"] = False
            _log(state, f"↳ {pname} kept Beach card for day-match bonus")

    elif ct == 6:  # Flip down
        if strength == "strong":
            tday = _ai_flip_down_strong_target(state, pidx, difficulty, exclude_day=day)
            if tday is not None:
                tcard = _card_at(player, tday)
                tct = tcard["card_type"] if tcard else ct
                _flip_down(state, pidx, tday)
                _log(state, f"↳ {pname} used Flip Down (strong): flipped own {LOCATION_NAMES[tct]} (Day {tday}) face down")
        else:
            result = _ai_flip_down_normal_target(state, pidx, difficulty)
            if result[0] is not None:
                tpi, tday = result
                tcard = _card_at(state["players"][tpi], tday)
                tct = tcard["card_type"] if tcard else ct
                _flip_down(state, tpi, tday)
                _log(state, f"↳ {pname} used Flip Down (normal): flipped {state['players'][tpi]['name']}'s {LOCATION_NAMES[tct]} (Day {tday}) face down")

    _advance_turn(state)


def _process_ai_turns(game):
    """Auto-play all consecutive AI turns until a human's turn or game over."""
    state = game["state"]
    ai_set = set(state.get("ai_players", []))
    if not ai_set:
        return
    limit = 20
    i = 0
    while (
        state["phase"] == "game"
        and state["current_player_idx"] in ai_set
        and not state["pending_action"]
        and i < limit
    ):
        _ai_take_turn(game)
        i += 1

# ── routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", game_id=None, token=None,
                           player_idx=None, player_name=None)

@app.route("/game/<game_id>/<token>")
def game_page(game_id, token):
    if game_id not in GAMES:
        return "Game not found. Ask the host to share a new link.", 404
    game = GAMES[game_id]
    pidx = _get_pidx(game, token)
    if pidx is None:
        return "Invalid player token.", 403
    return render_template(
        "index.html",
        game_id=game_id, token=token,
        player_idx=pidx,
        player_name=game["state"]["players"][pidx]["name"],
    )

def _bot_label(diff_str):
    if diff_str.startswith("mcts:"):
        return f"MCTS ({diff_str.split(':')[1]})"
    return "Strategic" if diff_str == "basic" else "Random"


@app.route("/api/create", methods=["POST"])
def api_create():
    data = request.json
    vs_ai = data.get("vs_ai", False)

    if vs_ai:
        human_name = str(data.get("human_name", "Player 1")).strip() or "Player 1"

        bots_spec = data.get("bots")
        if bots_spec:
            ai_diffs = {}
            for i, bot_info in enumerate(bots_spec[:2]):
                ai_pidx = i + 1
                bt = bot_info.get("type", "random")
                if bt == "mcts":
                    r = max(1, int(bot_info.get("rollouts", 50)))
                    ai_diffs[str(ai_pidx)] = f"mcts:{r}"
                elif bt == "basic":
                    ai_diffs[str(ai_pidx)] = "basic"
                else:
                    ai_diffs[str(ai_pidx)] = "random"
        else:
            diff = data.get("ai_difficulty", "random")
            ai_diffs = {"1": diff, "2": diff}

        player_names = [
            human_name,
            f"Bot 1 ({_bot_label(ai_diffs.get('1', 'random'))})",
            f"Bot 2 ({_bot_label(ai_diffs.get('2', 'random'))})",
        ]

        game_id = uuid.uuid4().hex[:10]
        tokens = [uuid.uuid4().hex for _ in range(3)]
        state = _new_state(player_names)
        state["ai_players"] = [1, 2]
        state["ai_difficulties"] = ai_diffs

        game = {"state": state, "tokens": tokens}
        GAMES[game_id] = game

        # Auto-process AI draft picks (player 0 is human)
        _process_draft_picks(game)

        return jsonify({
            "vs_ai": True,
            "player_url": f"/game/{game_id}/{tokens[0]}",
        })
    else:
        n = max(2, min(3, int(data.get("num_players", 3))))
        names = data.get("names", [])
        player_names = [
            (str(names[i]).strip() if i < len(names) else "") or f"Player {i + 1}"
            for i in range(n)
        ]
        game_id = uuid.uuid4().hex[:10]
        tokens = [uuid.uuid4().hex for _ in range(n)]
        GAMES[game_id] = {"state": _new_state(player_names), "tokens": tokens}
        return jsonify({
            "vs_ai": False,
            "game_id": game_id,
            "tokens": tokens,
            "player_names": player_names,
        })

def _resolve(game_id, token):
    game = GAMES.get(game_id)
    if not game:
        return None, None
    return game, _get_pidx(game, token)

@app.route("/api/game/<game_id>/<token>/state")
def api_state(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_state_for_player(game, pidx))

@app.route("/api/game/<game_id>/<token>/draft_pick", methods=["POST"])
def api_draft_pick(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["phase"] != "draft":
        return jsonify({"error": "Not in draft phase"}), 400
    cur_drafter = state["draft_order"][state["draft_pick_idx"]]
    if cur_drafter != pidx:
        return jsonify({"error": "Not your draft turn"}), 400

    card_type = int(request.json.get("card_type", -1))
    pool = state["draft_pool"]
    if not any(c["card_type"] == card_type for c in pool):
        return jsonify({"error": "Card not available in draft pool"}), 400

    _do_draft_pick(state, pidx, card_type)

    # If we advanced to arrangement, process AI arrangements
    if state["phase"] == "arrangement":
        _process_ai_arrangements(game)
        if state["phase"] == "game":
            _process_ai_turns(game)
    else:
        # Process any consecutive AI picks
        _process_draft_picks(game)
        if state["phase"] == "arrangement":
            _process_ai_arrangements(game)
            if state["phase"] == "game":
                _process_ai_turns(game)

    return jsonify(_state_for_player(game, pidx))

@app.route("/api/game/<game_id>/<token>/arrange", methods=["POST"])
def api_arrange(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["phase"] != "arrangement" or state["players"][pidx]["arranged"]:
        return jsonify({"error": "Cannot arrange now"}), 400

    player = state["players"][pidx]
    draft_cards = player.get("draft_cards", [])
    cards = [None] * 6
    for ct_str, day in request.json.get("arrangement", {}).items():
        ct = int(ct_str)
        strength = next(
            (c["strength"] for c in draft_cards if c["card_type"] == ct),
            "normal"
        )
        cards[int(day) - 1] = {
            "card_type": ct, "face_up": False, "arrival": 0,
            "strength": strength, "banked": False
        }
    state["players"][pidx]["cards"] = cards
    state["players"][pidx]["arranged"] = True
    if all(p["arranged"] for p in state["players"]):
        state["phase"] = "game"
        _process_ai_turns(game)
    return jsonify(_state_for_player(game, pidx))

@app.route("/api/game/<game_id>/<token>/flip", methods=["POST"])
def api_flip(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["phase"] != "game" or state["pending_action"]:
        return jsonify({"error": "Cannot flip now"}), 400
    if pidx != state["current_player_idx"]:
        return jsonify({"error": "Not your turn"}), 400

    day = int(request.json.get("day"))
    player = state["players"][pidx]
    card = _card_at(player, day)
    if not card or card["face_up"]:
        return jsonify({"error": "Cannot flip that card"}), 400

    _flip_up(state, pidx, day)
    ct = card["card_type"]
    strength = card.get("strength", "normal")
    arr_label = {1: "1st", 2: "2nd", 3: "3rd"}.get(card["arrival"], f"#{card['arrival']}")
    strength_label = "★" if strength == "strong" else ""
    _log(state, f"{player['name']} flipped {strength_label}{LOCATION_NAMES[ct]} on Day {day} — {arr_label} to arrive")
    pending, msg = None, None

    if ct == 1:  # Lock
        if strength == "strong":
            pending = "lock_pick_day"
            msg = f"Lock (strong): Choose a day — ALL cards on that day will be locked."
            state["action_ctx"] = {"actor": pidx, "strength": "strong"}
        else:
            pending = "lock_pick_day"
            msg = f"Lock (normal): Choose a day, then select 2 cards to lock."
            state["action_ctx"] = {"actor": pidx, "strength": "normal"}

    elif ct == 2:  # Swap own
        if strength == "strong":
            pending = "swap_own_1"
            msg = f"Swap Own (strong): Click one of your cards — first of two to swap."
            state["action_ctx"] = {"actor": pidx, "strength": "strong"}
        else:
            pending = "adj_swap_own"
            msg = f"Swap Own (normal): Click one of your cards to shift it to an adjacent day."
            state["action_ctx"] = {"actor": pidx, "strength": "normal"}

    elif ct == 3:  # Swap others
        if strength == "strong":
            pending = "swap_other_1"
            msg = f"Swap Others (strong): Click an opponent's card — first of two to swap."
            state["action_ctx"] = {"actor": pidx, "strength": "strong"}
        else:
            pending = "adj_swap_other"
            msg = f"Swap Others (normal): Click an opponent's card to shift it to an adjacent day."
            state["action_ctx"] = {"actor": pidx, "strength": "normal"}

    elif ct == 4:  # Switch arrival order
        pending = "switch_arrival_pick"
        msg = f"Switch Arrival ({'strong: reorder all' if strength == 'strong' else 'normal: swap two'}): Click a card to choose an arrival slot."
        state["action_ctx"] = {"actor": pidx, "strength": strength}

    elif ct == 5:  # Bank points — human decides
        # Set pending bank_decision with context
        state["action_ctx"] = {"actor": pidx, "bank_day": day, "strength": strength}
        pending = "bank_decision"
        bank_pts = 2 if strength == "strong" else 1
        msg = f"Beach card flipped! Bank +{bank_pts} pts now, or keep for day-matching bonus?"

    elif ct == 6:  # Flip down
        if strength == "strong":
            # Flip own face-up card
            face_up_own = [c for c in player["cards"] if c["face_up"]]
            if face_up_own:
                pending = "flip_own_down"
                msg = f"Flip Down (strong): Click one of YOUR face-up cards to flip it down."
                state["action_ctx"] = {"actor": pidx, "strength": "strong"}
        else:
            # Flip opponent's face-up card
            opp_face_up = [
                c for pi, p in enumerate(state["players"]) if pi != pidx
                for c in p["cards"] if c["face_up"]
            ]
            if opp_face_up:
                pending = "flip_other_down"
                msg = f"Flip Down (normal): Click an OPPONENT'S face-up card to flip it down."
                state["action_ctx"] = {"actor": pidx, "strength": "normal"}

    if pending:
        state["pending_action"] = pending
        if not state.get("action_ctx"):
            state["action_ctx"] = {"actor": pidx}
        state["action_message"] = msg
    else:
        _advance_turn(state)
        _process_ai_turns(game)

    return jsonify(_state_for_player(game, pidx))

@app.route("/api/game/<game_id>/<token>/bank_decision", methods=["POST"])
def api_bank_decision(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["phase"] != "game" or state["pending_action"] != "bank_decision":
        return jsonify({"error": "No bank decision pending"}), 400
    if pidx != state["current_player_idx"]:
        return jsonify({"error": "Not your turn"}), 400

    ctx = state["action_ctx"]
    bank = bool(request.json.get("bank", False))
    bank_day = ctx.get("bank_day")
    strength = ctx.get("strength", "normal")

    card = _card_at(state["players"][pidx], bank_day)
    if card:
        card["banked"] = bank

    bank_pts = 2 if strength == "strong" else 1
    if bank:
        _log(state, f"↳ {state['players'][pidx]['name']} banked Beach card (+{bank_pts} pts)")
    else:
        _log(state, f"↳ {state['players'][pidx]['name']} kept Beach card for day-match bonus")

    state["pending_action"] = None
    state["action_ctx"] = {}
    state["action_message"] = None
    _advance_turn(state)
    _process_ai_turns(game)
    return jsonify(_state_for_player(game, pidx))

@app.route("/api/game/<game_id>/<token>/action", methods=["POST"])
def api_action(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["phase"] != "game" or not state["pending_action"]:
        return jsonify({"error": "No pending action"}), 400
    if pidx != state["current_player_idx"]:
        return jsonify({"error": "Not your turn"}), 400

    action = state["pending_action"]
    ctx = state["action_ctx"]
    actor = ctx["actor"]
    data = request.json
    tpi = int(data.get("player_idx", -1))
    tday = int(data.get("day", -1))

    err, done, needs_pos, arrival_info, success_msg = None, False, False, None, None

    # ── Lock actions ─────────────────────────────────────────────────────────
    if action == "lock_pick_day":
        day = int(data.get("day", -1))
        if day < 1 or day > 6:
            err = "Choose a day 1-6."
        else:
            strength = ctx.get("strength", "normal")
            if strength == "strong":
                # Lock ALL cards on that day
                for pi in range(len(state["players"])):
                    di = day - 1
                    if [pi, di] not in state["locks"]:
                        state["locks"].append([pi, di])
                _log(state, f"↳ {state['players'][actor]['name']} used Lock (strong): locked all cards on Day {day}")
                success_msg = f"Locked all cards on Day {day}!"
                done = True
            else:
                # Normal: need to pick 2 cards on that day
                ctx["lock_day"] = day
                ctx["lock_picks"] = []
                state["pending_action"] = "lock_pick_2"
                state["action_message"] = f"Day {day} selected. Now click 2 cards on Day {day} to lock them."

    elif action == "lock_pick_2":
        lock_day = ctx.get("lock_day")
        if tday != lock_day:
            err = f"Must click a card on Day {lock_day}."
        elif _is_locked(state, tpi, tday):
            err = "That card is already locked."
        else:
            picks = ctx.get("lock_picks", [])
            pair = [tpi, tday - 1]
            if pair in picks:
                err = "Already selected that card."
            else:
                picks.append(pair)
                ctx["lock_picks"] = picks
                if len(picks) >= 2:
                    for item in picks:
                        if item not in state["locks"]:
                            state["locks"].append(item)
                    names = [f"{state['players'][p[0]]['name']} Day {p[1]+1}" for p in picks]
                    _log(state, f"↳ {state['players'][actor]['name']} used Lock (normal): locked {', '.join(names)}")
                    success_msg = f"Locked 2 cards on Day {lock_day}!"
                    done = True
                else:
                    state["action_message"] = f"1 card selected on Day {lock_day}. Click 1 more card to lock."

    # ── Swap own (strong) ─────────────────────────────────────────────────────
    elif action == "swap_own_1":
        if tpi != actor:
            err = "Must target your own card."
        elif _is_locked(state, tpi, tday):
            err = "That card is locked."
        else:
            ctx["first_day"] = tday
            state["pending_action"] = "swap_own_2"
            state["action_message"] = (
                f"Selected your Day {tday}. Now click a second card of yours to complete the swap."
            )

    elif action == "swap_own_2":
        if tpi != actor:
            err = "Must target your own card."
        elif tday == ctx.get("first_day"):
            err = "Must select a different day."
        elif _is_locked(state, tpi, tday):
            err = "That card is locked."
        elif _is_locked(state, actor, ctx.get("first_day", -1)):
            err = "First selected card is locked."
        else:
            _swap_days(state, actor, ctx["first_day"], tday)
            success_msg = f"Swapped your Day {ctx['first_day']} and Day {tday}!"
            _log(state, f"↳ {state['players'][actor]['name']} used Swap Own (strong): swapped Day {ctx['first_day']} ↔ Day {tday}")
            done = True

    # ── Adjacent swap own (normal) ────────────────────────────────────────────
    elif action == "adj_swap_own":
        if tpi != actor:
            err = "Must target your own card."
        elif _is_locked(state, tpi, tday):
            err = "That card is locked."
        else:
            ctx["adj_day"] = tday
            state["pending_action"] = "adj_swap_own_dir"
            adj = [(tday - 2) % 6 + 1, tday % 6 + 1]
            state["action_message"] = (
                f"Selected Day {tday}. Now click an adjacent day card (Day {adj[0]} or Day {adj[1]}) to swap."
            )

    elif action == "adj_swap_own_dir":
        src = ctx.get("adj_day")
        adj = [(src - 2) % 6 + 1, src % 6 + 1]
        if tpi != actor:
            err = "Must target your own card."
        elif tday not in adj:
            err = f"Must pick an adjacent day (Day {adj[0]} or Day {adj[1]})."
        elif _is_locked(state, actor, tday):
            err = "Target day is locked."
        elif _is_locked(state, actor, src):
            err = "Source day is locked."
        else:
            _swap_days(state, actor, src, tday)
            success_msg = f"Shifted your card from Day {src} to Day {tday}!"
            _log(state, f"↳ {state['players'][actor]['name']} used Swap Own (normal): shifted Day {src} → Day {tday}")
            done = True

    # ── Swap other (strong) ───────────────────────────────────────────────────
    elif action == "swap_other_1":
        if tpi == actor:
            err = "Must target another player's card."
        elif _is_locked(state, tpi, tday):
            err = "That card is locked."
        else:
            ctx["first_pi"] = tpi
            ctx["first_day"] = tday
            state["pending_action"] = "swap_other_2"
            state["action_message"] = (
                f"Selected {state['players'][tpi]['name']}'s Day {tday}. "
                "Now click a second card from the same player."
            )

    elif action == "swap_other_2":
        if tpi == actor:
            err = "Must target another player's card."
        elif tpi != ctx.get("first_pi"):
            err = "Must pick two cards from the same player."
        elif tday == ctx.get("first_day"):
            err = "Must select a different day."
        elif _is_locked(state, tpi, tday):
            err = "That card is locked."
        elif _is_locked(state, tpi, ctx.get("first_day", -1)):
            err = "First selected card is locked."
        else:
            _swap_days(state, tpi, ctx["first_day"], tday)
            success_msg = f"Swapped {state['players'][tpi]['name']}'s Day {ctx['first_day']} and Day {tday}!"
            _log(state, f"↳ {state['players'][actor]['name']} used Swap Others (strong): swapped {state['players'][tpi]['name']}'s Day {ctx['first_day']} ↔ Day {tday}")
            done = True

    # ── Adjacent swap other (normal) ──────────────────────────────────────────
    elif action == "adj_swap_other":
        if tpi == actor:
            err = "Must target an opponent's card."
        elif _is_locked(state, tpi, tday):
            err = "That card is locked."
        else:
            ctx["adj_pi"] = tpi
            ctx["adj_day"] = tday
            state["pending_action"] = "adj_swap_other_dir"
            adj = [(tday - 2) % 6 + 1, tday % 6 + 1]
            state["action_message"] = (
                f"Selected {state['players'][tpi]['name']}'s Day {tday}. "
                f"Now click their adjacent day card (Day {adj[0]} or Day {adj[1]}) to swap."
            )

    elif action == "adj_swap_other_dir":
        src_pi = ctx.get("adj_pi")
        src = ctx.get("adj_day")
        adj = [(src - 2) % 6 + 1, src % 6 + 1]
        if tpi != src_pi:
            err = "Must click the same player's card."
        elif tday not in adj:
            err = f"Must pick an adjacent day (Day {adj[0]} or Day {adj[1]})."
        elif _is_locked(state, src_pi, tday):
            err = "Target day is locked."
        elif _is_locked(state, src_pi, src):
            err = "Source day is locked."
        else:
            _swap_days(state, src_pi, src, tday)
            success_msg = f"Shifted {state['players'][src_pi]['name']}'s card from Day {src} to Day {tday}!"
            _log(state, f"↳ {state['players'][actor]['name']} used Swap Others (normal): shifted {state['players'][src_pi]['name']}'s Day {src} → Day {tday}")
            done = True

    # ── Switch arrival pick (type 4) ──────────────────────────────────────────
    elif action == "switch_arrival_pick":
        card = _card_at(state["players"][tpi], tday)
        if not card or not card["face_up"]:
            err = "Must click a face-up card."
        else:
            ct = card["card_type"]
            k = _key(tday, ct)
            arr = state["arrivals"].get(k, [])
            if len(arr) < 2:
                err = "Need at least 2 arrivals at that location."
            else:
                ctx["sw_day"] = tday
                ctx["sw_ct"] = ct
                strength = ctx.get("strength", "normal")
                if strength == "strong":
                    # Show reorder UI
                    state["pending_action"] = "switch_arrival_reorder"
                    state["action_ctx"]["arrivals"] = list(arr)
                    state["action_message"] = f"Reorder arrivals at {LOCATION_NAMES[ct]} Day {tday}. Use set_reorder."
                    needs_pos = True
                    arrival_info = {
                        "player_name": f"{LOCATION_NAMES[ct]} Day {tday}",
                        "location": LOCATION_NAMES[ct],
                        "day": tday,
                        "current": card["arrival"],
                        "num": len(arr),
                        "arrival_list": [state["players"][pi]["name"] for pi in arr],
                        "arrival_pidxs": list(arr),
                        "reorder": True,
                    }
                else:
                    # Normal: swap 2
                    state["pending_action"] = "switch_arrival_swap_1"
                    state["action_ctx"]["arrival_list"] = list(arr)
                    state["action_message"] = (
                        f"Select first arrival to swap at {LOCATION_NAMES[ct]} Day {tday}. "
                        f"Players there: {', '.join(state['players'][pi]['name'] for pi in arr)}"
                    )
                    needs_pos = True
                    arrival_info = {
                        "player_name": f"{LOCATION_NAMES[ct]} Day {tday}",
                        "location": LOCATION_NAMES[ct],
                        "day": tday,
                        "current": card["arrival"],
                        "num": len(arr),
                        "arrival_list": [state["players"][pi]["name"] for pi in arr],
                        "arrival_pidxs": list(arr),
                        "reorder": False,
                    }

    elif action == "switch_arrival_reorder":
        # Handled by set_reorder endpoint
        err = "Use /set_reorder to complete this action."

    elif action == "switch_arrival_swap_1":
        # Player selected which arrival position to swap (by player_idx)
        arr = state["arrivals"].get(_key(ctx["sw_day"], ctx["sw_ct"]), [])
        if tpi not in arr:
            err = "That player is not at that location."
        else:
            ctx["swap_first_pi"] = tpi
            state["pending_action"] = "switch_arrival_swap_2"
            state["action_message"] = (
                f"Selected {state['players'][tpi]['name']}. Click a second player at that location to swap."
            )

    elif action == "switch_arrival_swap_2":
        arr = state["arrivals"].get(_key(ctx["sw_day"], ctx["sw_ct"]), [])
        first_pi = ctx.get("swap_first_pi")
        if tpi not in arr:
            err = "That player is not at that location."
        elif tpi == first_pi:
            err = "Must select a different player."
        else:
            i1 = arr.index(first_pi)
            i2 = arr.index(tpi)
            arr[i1], arr[i2] = arr[i2], arr[i1]
            _renumber(state, ctx["sw_day"], ctx["sw_ct"])
            _log(state, f"↳ {state['players'][actor]['name']} used Switch Arrival (normal): swapped {state['players'][first_pi]['name']} ↔ {state['players'][tpi]['name']} at {LOCATION_NAMES[ctx['sw_ct']]} Day {ctx['sw_day']}")
            success_msg = f"Swapped arrival positions!"
            done = True

    # ── Flip down (type 6) ────────────────────────────────────────────────────
    elif action == "flip_other_down":
        if tpi == actor:
            err = "Must target an opponent's card."
        elif _is_locked(state, tpi, tday):
            err = "That card is locked."
        else:
            card = _card_at(state["players"][tpi], tday)
            if not card or not card["face_up"]:
                err = "Must target a face-up card."
            else:
                _flip_down(state, tpi, tday)
                success_msg = f"Flipped {state['players'][tpi]['name']}'s {LOCATION_NAMES[card['card_type']]} (Day {tday}) face down!"
                _log(state, f"↳ {state['players'][actor]['name']} used Flip Down (normal): flipped {state['players'][tpi]['name']}'s {LOCATION_NAMES[card['card_type']]} (Day {tday}) face down")
                done = True

    elif action == "flip_own_down":
        if tpi != actor:
            err = "Must target your own card."
        elif _is_locked(state, tpi, tday):
            err = "That card is locked."
        else:
            card = _card_at(state["players"][tpi], tday)
            if not card or not card["face_up"]:
                err = "Must target a face-up card."
            else:
                _flip_down(state, tpi, tday)
                success_msg = f"Flipped your {LOCATION_NAMES[card['card_type']]} (Day {tday}) face down!"
                _log(state, f"↳ {state['players'][actor]['name']} used Flip Down (strong): flipped own {LOCATION_NAMES[card['card_type']]} (Day {tday}) face down")
                done = True

    elif action in ("change_arr_other", "change_arr_own"):
        is_other = action == "change_arr_other"
        if is_other and tpi == actor:
            err = "Must target an opponent's card."
        elif not is_other and tpi != actor:
            err = "Must target your own card."
        else:
            card = _card_at(state["players"][tpi], tday)
            if not card or not card["face_up"]:
                err = "Must target a face-up card."
            else:
                k = _key(tday, card["card_type"])
                arr = state["arrivals"].get(k, [])
                if len(arr) < 2:
                    err = "Only one player there — no arrival order to change."
                else:
                    ctx["ability"] = "Beach" if action == "change_arr_other" else "Museum"
                    ctx["target_pi"] = tpi
                    ctx["target_day"] = tday
                    state["pending_action"] = "set_arrival"
                    state["action_message"] = (
                        f"Select new arrival position for "
                        f"{state['players'][tpi]['name']}'s "
                        f"{LOCATION_NAMES[card['card_type']]} on Day {tday}."
                    )
                    needs_pos = True
                    arrival_info = {
                        "player_name": state["players"][tpi]["name"],
                        "location": LOCATION_NAMES[card["card_type"]],
                        "day": tday, "current": card["arrival"],
                        "num": len(arr),
                    }

    if done:
        state["pending_action"] = None
        state["action_ctx"] = {}
        state["action_message"] = None
        _advance_turn(state)
        _process_ai_turns(game)

    resp = _state_for_player(game, pidx)
    resp["action_result"] = {
        "error": err, "done": done,
        "needs_position": needs_pos, "arrival_info": arrival_info,
        "message": success_msg,
    }
    return jsonify(resp)

@app.route("/api/game/<game_id>/<token>/set_arrival", methods=["POST"])
def api_set_arrival(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["pending_action"] != "set_arrival":
        return jsonify({"error": "No arrival to set"}), 400
    ctx = state["action_ctx"]
    new_pos = int(request.json.get("new_pos", 1))
    _change_arrival(state, ctx["target_pi"], ctx["target_day"], new_pos)
    card = _card_at(state["players"][ctx["target_pi"]], ctx["target_day"])
    ability_name = ctx.get("ability", "Switch Arrival")
    actor_pidx = ctx.get("actor")
    actor_name_log = state["players"][actor_pidx]["name"] if actor_pidx is not None else "?"
    _log(state, f"↳ {actor_name_log} used {ability_name}: {state['players'][ctx['target_pi']]['name']}'s {LOCATION_NAMES[card['card_type']]} arrival → #{new_pos}")
    msg = (f"Changed {state['players'][ctx['target_pi']]['name']}'s "
           f"{LOCATION_NAMES[card['card_type']]} arrival to position #{new_pos}!")
    state["pending_action"] = None
    state["action_ctx"] = {}
    state["action_message"] = None
    _advance_turn(state)
    _process_ai_turns(game)
    resp = _state_for_player(game, pidx)
    resp["action_result"] = {"error": None, "done": True, "message": msg}
    return jsonify(resp)

@app.route("/api/game/<game_id>/<token>/set_reorder", methods=["POST"])
def api_set_reorder(game_id, token):
    """For type 4 strong: set a new arrival order."""
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["pending_action"] != "switch_arrival_reorder":
        return jsonify({"error": "No reorder pending"}), 400
    if pidx != state["current_player_idx"]:
        return jsonify({"error": "Not your turn"}), 400

    ctx = state["action_ctx"]
    sw_day = ctx["sw_day"]
    sw_ct = ctx["sw_ct"]
    k = _key(sw_day, sw_ct)
    current_arr = state["arrivals"].get(k, [])
    new_order = request.json.get("new_order", [])

    # Validate: must be a permutation of current arrivals
    if sorted(new_order) != sorted(current_arr):
        return jsonify({"error": "Invalid permutation of current arrivals"}), 400

    state["arrivals"][k] = list(new_order)
    _renumber(state, sw_day, sw_ct)

    actor_name = state["players"][pidx]["name"]
    _log(state, f"↳ {actor_name} used Switch Arrival (strong): reordered {LOCATION_NAMES[sw_ct]} on Day {sw_day}")

    state["pending_action"] = None
    state["action_ctx"] = {}
    state["action_message"] = None
    _advance_turn(state)
    _process_ai_turns(game)
    resp = _state_for_player(game, pidx)
    resp["action_result"] = {"error": None, "done": True, "message": f"Reordered arrivals at {LOCATION_NAMES[sw_ct]} Day {sw_day}!"}
    return jsonify(resp)

@app.route("/api/game/<game_id>/<token>/cancel", methods=["POST"])
def api_cancel(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    _log(state, f"{state['players'][pidx]['name']} skipped their ability")
    state["pending_action"] = None
    state["action_ctx"] = {}
    state["action_message"] = None
    _advance_turn(state)
    _process_ai_turns(game)
    return jsonify(_state_for_player(game, pidx))

@app.route("/api/game/<game_id>/<token>/end_game", methods=["POST"])
def api_end_game(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    game["state"]["phase"] = "end"
    game["state"]["game_over"] = True
    return jsonify(_state_for_player(game, pidx))

# ── room routes ───────────────────────────────────────────────────────────────

@app.route("/api/rooms/create", methods=["POST"])
def api_rooms_create():
    data = request.json or {}
    name = str(data.get("name", "")).strip() or "Player 1"
    lobby_token = uuid.uuid4().hex
    with ROOMS_LOCK:
        code = _gen_room_code()
        room = {
            "code": code,
            "host_token": lobby_token,
            "status": "lobby",
            "players": [{"lobby_token": lobby_token, "name": name,
                         "is_ai": False, "ai_type": None, "ai_rollouts": 50,
                         "game_token": None}],
            "game_id": None,
            "version": 0,
        }
        ROOMS[code] = room
    return jsonify({"room_code": code, "lobby_token": lobby_token,
                    **_room_view(room, lobby_token)})


@app.route("/api/rooms/join", methods=["POST"])
def api_rooms_join():
    data = request.json or {}
    code = str(data.get("code", "")).strip()
    name = str(data.get("name", "")).strip() or "Player"
    lobby_token = uuid.uuid4().hex
    with ROOMS_LOCK:
        room = ROOMS.get(code)
        if not room:
            return jsonify({"error": "Room not found. Check the code and try again."}), 404
        if room["status"] != "lobby":
            return jsonify({"error": "Game has already started."}), 400
        if len(room["players"]) >= 3:
            return jsonify({"error": "Room is full (max 3 players)."}), 400
        room["players"].append({"lobby_token": lobby_token, "name": name,
                                "is_ai": False, "ai_type": None, "ai_rollouts": 50,
                                "game_token": None})
        room["version"] += 1
    return jsonify({"room_code": code, "lobby_token": lobby_token,
                    **_room_view(room, lobby_token)})


@app.route("/api/rooms/<code>")
def api_room_get(code):
    lobby_token = request.args.get("t", "")
    room = ROOMS.get(code)
    if not room:
        return jsonify({"error": "Room not found"}), 404
    return jsonify(_room_view(room, lobby_token))


@app.route("/api/rooms/<code>/add_ai", methods=["POST"])
def api_room_add_ai(code):
    data = request.json or {}
    lobby_token = data.get("t", "")
    with ROOMS_LOCK:
        room = ROOMS.get(code)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        if room["host_token"] != lobby_token:
            return jsonify({"error": "Only the host can add AI players"}), 403
        if room["status"] != "lobby":
            return jsonify({"error": "Game already started"}), 400
        if len(room["players"]) >= 3:
            return jsonify({"error": "Room is full (max 3 players)"}), 400
        ai_type = str(data.get("ai_type", "random"))
        ai_rollouts = max(1, min(500, int(data.get("ai_rollouts", 50))))
        n_bots = sum(1 for p in room["players"] if p["is_ai"])
        ai_name = str(data.get("name", f"Bot {n_bots + 1}")).strip() or f"Bot {n_bots + 1}"
        room["players"].append({"lobby_token": f"ai_{uuid.uuid4().hex}", "name": ai_name,
                                "is_ai": True, "ai_type": ai_type, "ai_rollouts": ai_rollouts,
                                "game_token": None})
        room["version"] += 1
    return jsonify(_room_view(room, lobby_token))


@app.route("/api/rooms/<code>/remove_player", methods=["POST"])
def api_room_remove_player(code):
    data = request.json or {}
    lobby_token = data.get("t", "")
    with ROOMS_LOCK:
        room = ROOMS.get(code)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        if room["host_token"] != lobby_token:
            return jsonify({"error": "Only the host can remove players"}), 403
        if room["status"] != "lobby":
            return jsonify({"error": "Game already started"}), 400
        target = data.get("player_id", "")
        if target == lobby_token:
            return jsonify({"error": "Cannot remove yourself"}), 400
        room["players"] = [p for p in room["players"] if p["lobby_token"] != target]
        room["version"] += 1
    return jsonify(_room_view(room, lobby_token))


@app.route("/api/rooms/<code>/move_player", methods=["POST"])
def api_room_move_player(code):
    data = request.json or {}
    lobby_token = data.get("t", "")
    with ROOMS_LOCK:
        room = ROOMS.get(code)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        if room["host_token"] != lobby_token:
            return jsonify({"error": "Only the host can reorder players"}), 403
        if room["status"] != "lobby":
            return jsonify({"error": "Game already started"}), 400
        target = data.get("player_id", "")
        direction = data.get("direction", "")
        players = room["players"]
        idx = next((i for i, p in enumerate(players) if p["lobby_token"] == target), None)
        if idx is None:
            return jsonify({"error": "Player not found"}), 404
        new_idx = idx - 1 if direction == "up" else idx + 1
        if 0 <= new_idx < len(players):
            players[idx], players[new_idx] = players[new_idx], players[idx]
            room["version"] += 1
    return jsonify(_room_view(room, lobby_token))


@app.route("/api/rooms/<code>/start", methods=["POST"])
def api_room_start(code):
    data = request.json or {}
    lobby_token = data.get("t", "")
    with ROOMS_LOCK:
        room = ROOMS.get(code)
        if not room:
            return jsonify({"error": "Room not found"}), 404
        if room["host_token"] != lobby_token:
            return jsonify({"error": "Only the host can start the game"}), 403
        if room["status"] != "lobby":
            return jsonify({"error": "Game already started"}), 400
        if len(room["players"]) < 2:
            return jsonify({"error": "Need at least 2 players to start"}), 400

        player_names = [p["name"] for p in room["players"]]
        game_id = uuid.uuid4().hex[:10]
        game_tokens = [uuid.uuid4().hex for _ in room["players"]]

        state = _new_state(player_names)
        ai_players = []
        ai_diffs = {}

        for i, rp in enumerate(room["players"]):
            if rp["is_ai"]:
                ai_players.append(i)
                ai_type = rp.get("ai_type", "random")
                n_roll = max(1, rp.get("ai_rollouts", 50))
                if ai_type == "mcts":
                    ai_diffs[str(i)] = f"mcts:{n_roll}"
                elif ai_type == "basic":
                    ai_diffs[str(i)] = "basic"
                else:
                    ai_diffs[str(i)] = "random"

        state["ai_players"] = ai_players
        state["ai_difficulties"] = ai_diffs

        game = {"state": state, "tokens": game_tokens}
        GAMES[game_id] = game

        # Process AI draft picks and arrangements
        _process_draft_picks(game)
        if state["phase"] == "game":
            _process_ai_turns(game)

        for i, rp in enumerate(room["players"]):
            rp["game_token"] = game_tokens[i]
        room["game_id"] = game_id
        room["status"] = "started"
        room["version"] += 1

    return jsonify(_room_view(room, lobby_token))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
