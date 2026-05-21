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
# Two groups: (+1,+2,-1) positional, (+2,+1,-1) reactive/late-game.
CARD_PTS = {
    1: (1, 2, -1),   # Coffee Shop  — positional
    2: (1, 2, -1),   # Park         — positional
    3: (2, 1, -1),   # Cinema       — reactive, late game
    4: (2, 1, -1),   # Restaurant   — reactive, late game
    5: (1, 2, -1),   # Beach        — positional
    6: (2, 1, -1),   # Museum       — reactive, late game
}

# Card types that carry a solo arrival penalty of -1 (arriving alone is punished).
# Cinema and Restaurant are opponent-manipulation cards — useless when alone.
CARD_SOLO_PENALTY_CTS = {3, 4}

# Draft value estimates: strong card of this type (tuned after balance sim)
# Restaurant and Beach are now equally desirable; Museum buffed.
DRAFT_VALUES = {4: 70, 5: 80, 3: 65, 2: 60, 1: 55, 6: 60}

# ── core game logic ───────────────────────────────────────────────────────────

def _card_at(player, day):
    return player["cards"][day - 1] if 1 <= day <= 6 else None

def _key(day, ct):
    return f"{ct}_{day}"

def _renumber(state, key):
    """Update arrival positions for players in the queue at key (format: 'ct_day')."""
    parts = str(key).split("_")
    ct, day = int(parts[0]), int(parts[1])
    for i, pidx in enumerate(state["arrivals"].get(key, [])):
        card = _card_at(state["players"][pidx], day)
        if card and card.get("card_type") == ct:
            card["arrival"] = i + 1

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
    ct = card["card_type"]
    k = _key(day, ct)
    arr = state["arrivals"].get(k, [])
    if pidx in arr:
        arr.remove(pidx)
        state["arrivals"][k] = arr
        _renumber(state, k)
    card["face_up"] = False
    card["arrival"] = 0
    card["banked"] = False
    return True

def _return_to_hand(state, pidx, day):
    """Remove a placed card from the board and return it to the player's hand."""
    player = state["players"][pidx]
    card = _card_at(player, day)
    if not card or not card.get("face_up"):
        return False
    if _is_locked(state, pidx, day):
        return False
    ct = card["card_type"]
    strength = card.get("strength", "normal")
    k = _key(day, ct)
    arr = state["arrivals"].get(k, [])
    if pidx in arr:
        arr.remove(pidx)
        state["arrivals"][k] = arr
        _renumber(state, k)
    player["cards"][day - 1] = None
    player.setdefault("hand_cards", []).append({"card_type": ct, "strength": strength})
    return True

def _swap_days(state, pidx, day1, day2):
    if day1 == day2:
        return False
    if _is_locked(state, pidx, day1) or _is_locked(state, pidx, day2):
        return False
    player = state["players"][pidx]
    c1, c2 = _card_at(player, day1), _card_at(player, day2)
    if c1 is None and c2 is None:
        return False
    if (c1 is None and _is_locked(state, pidx, day1)) or (c2 is None and _is_locked(state, pidx, day2)):
        return False

    def _dequeue(card, day):
        if card and card.get("face_up"):
            k = _key(day, card["card_type"])
            arr = state["arrivals"].get(k, [])
            if pidx in arr:
                arr.remove(pidx)
                state["arrivals"][k] = arr
            _renumber(state, k)

    def _enqueue(card, day):
        if card and card.get("face_up"):
            k = _key(day, card["card_type"])
            state["arrivals"].setdefault(k, []).append(pidx)
            card["arrival"] = len(state["arrivals"][k])
        elif card:
            card["arrival"] = 0

    _dequeue(c1, day1)
    _dequeue(c2, day2)
    player["cards"][day1 - 1] = c2  # c2 moves to day1
    player["cards"][day2 - 1] = c1  # c1 moves to day2
    _enqueue(c2, day1)
    _enqueue(c1, day2)
    return True

def _change_arrival(state, pidx, day, new_pos):
    card = _card_at(state["players"][pidx], day)
    if not card or not card["face_up"]:
        return False
    ct = card["card_type"]
    k = _key(day, ct)
    arr = state["arrivals"].get(k, [])
    if pidx not in arr:
        return False
    new_pos = max(1, min(new_pos, len(arr)))
    arr.remove(pidx)
    arr.insert(new_pos - 1, pidx)
    state["arrivals"][k] = arr
    _renumber(state, k)
    return True

def _check_game_over(state):
    if all(c is not None and c["face_up"] for p in state["players"] for c in p["cards"]):
        state["game_over"] = True
        _start_date_resolution(state)
    return state["game_over"]


def _start_date_resolution(state):
    def _dk(k):
        parts = k.split("_")
        return (int(parts[0]), int(parts[1]))
    queue = [k for k, arr in sorted(state["arrivals"].items(), key=lambda x: _dk(x[0]))
             if len(arr) >= 2]
    state["date_queue"] = queue
    state["date_results"] = []
    state["date_resolution_pts"] = {str(i): 0 for i in range(len(state["players"]))}
    if queue:
        state["phase"] = "date_resolution"
        ct, day = _dk(queue[0])
        state["current_date_ct"] = ct
        state["current_date_day"] = day
        state["date_moves"] = {}
    else:
        state["phase"] = "end"


def _resolve_current_date(state):
    ct = state["current_date_ct"]
    day = state["current_date_day"]
    arr = state["arrivals"].get(_key(day, ct), [])
    moves = state["date_moves"]   # {str(pidx): bool}
    pts = CARD_PTS[ct]
    n = min(len(arr), 3)
    participants = arr[:n]

    def np(i):  # normal pts for position i
        return pts[i] if i < len(pts) else 0

    normal = {participants[i]: np(i) for i in range(n)}
    moved = {pi for pi in participants if moves.get(str(pi), False)}
    result = {}
    outcome = ""

    if n == 2:
        p1, p2 = participants
        if p1 in moved and p2 in moved:
            result = {p1: normal[p1] * 2, p2: normal[p2] * 2}
            outcome = "Both made a move — points doubled!"
        elif p1 in moved:
            result = {p1: 0, p2: normal[p2]}
            outcome = f"{state['players'][p1]['name']} moved alone — forfeited their points"
        elif p2 in moved:
            result = {p1: normal[p1], p2: 0}
            outcome = f"{state['players'][p2]['name']} moved alone — forfeited their points"
        else:
            result = {p1: normal[p1], p2: normal[p2]}
            outcome = "No moves — normal points"

    elif n >= 3:
        p1, p2, p3 = participants[0], participants[1], participants[2]
        m1, m2, m3 = p1 in moved, p2 in moved, p3 in moved
        if m1 and m2 and m3:
            result = {p1: 0, p2: 0, p3: 0}
            outcome = "All three made a move — awkward! No points for anyone"
        elif m3 and m1 and not m2:
            result = {p1: normal[p1], p2: normal[p3], p3: normal[p2]}
            outcome = f"{state['players'][p3]['name']} stole from {state['players'][p2]['name']}!"
        elif m3 and not m1 and m2:
            result = {p1: normal[p3], p2: normal[p2], p3: normal[p1]}
            outcome = f"{state['players'][p3]['name']} stole from {state['players'][p1]['name']}!"
        elif m3 and not m1 and not m2:
            result = {p1: normal[p1], p2: normal[p2], p3: normal[p3] * 2}
            outcome = f"{state['players'][p3]['name']} moved alone — penalty doubled!"
        elif m1 and m2 and not m3:
            result = {p1: normal[p1] * 2, p2: normal[p2] * 2, p3: normal[p3]}
            outcome = "Both positives made a move — points doubled!"
        elif m1 and not m2 and not m3:
            result = {p1: 0, p2: normal[p2], p3: normal[p3]}
            outcome = f"{state['players'][p1]['name']} moved alone — forfeited their points"
        elif not m1 and m2 and not m3:
            result = {p1: normal[p1], p2: 0, p3: normal[p3]}
            outcome = f"{state['players'][p2]['name']} moved alone — forfeited their points"
        else:
            result = {p: normal[p] for p in participants}
            outcome = "No moves — normal points"

    # Accumulate
    for pi, v in result.items():
        state["date_resolution_pts"][str(pi)] = state["date_resolution_pts"].get(str(pi), 0) + v

    # Record for display
    state["date_results"].append({
        "ct": ct,
        "location": LOCATION_NAMES[ct],
        "players": [state["players"][pi]["name"] for pi in participants],
        "pidxs": list(participants),
        "moves": {str(pi): moves.get(str(pi), False) for pi in participants},
        "normal_pts": {str(pi): normal[pi] for pi in participants},
        "result_pts": {str(pi): result.get(pi, 0) for pi in participants},
        "outcome": outcome,
    })
    _log(state, f"Date resolved — {LOCATION_NAMES[ct]}: {outcome}")

    # Advance
    queue = state["date_queue"]
    cur_key = _key(day, ct)
    idx = queue.index(cur_key)
    if idx + 1 < len(queue):
        next_key = queue[idx + 1]
        parts = next_key.split("_")
        state["current_date_ct"] = int(parts[0])
        state["current_date_day"] = int(parts[1])
        state["date_moves"] = {}
    else:
        state["phase"] = "end"
        state["current_date_ct"] = None
        state["current_date_day"] = None


def _process_date_ai_moves(game):
    state = game["state"]
    if state["phase"] != "date_resolution":
        return
    ct = state.get("current_date_ct")
    day = state.get("current_date_day")
    if ct is None or day is None:
        return
    arr = state["arrivals"].get(_key(day, ct), [])
    participants = arr[:min(len(arr), 3)]
    ai_set = set(state.get("ai_players", []))
    pts = CARD_PTS[ct]

    for i, pidx in enumerate(participants):
        if pidx in ai_set and str(pidx) not in state["date_moves"]:
            my_pts = pts[i] if i < len(pts) else 0
            # Heuristic: if negative arrival pts, usually make a move; else 50/50
            make_move = random.random() < (0.65 if my_pts < 0 else 0.45)
            state["date_moves"][str(pidx)] = make_move

    all_submitted = all(str(pi) in state["date_moves"] for pi in participants)
    if all_submitted:
        _resolve_current_date(state)
        if state["phase"] == "date_resolution":
            _process_date_ai_moves(game)

def _advance_turn(state):
    # In hand mode (ability_resolution_queue is active), do nothing here.
    # _advance_ability_queue handles progression.
    if state.get("ability_resolution_queue") is not None and len(state.get("ability_resolution_queue", [])) > 0:
        return

    n = len(state["players"])
    state["turn_count"] += 1
    state["current_player_idx"] = (state["current_player_idx"] + 1) % n
    if _check_game_over(state):
        return
    skips = 0
    while (
        all(c is not None and c["face_up"] for c in state["players"][state["current_player_idx"]]["cards"])
        and skips < n
    ):
        state["turn_count"] += 1
        state["current_player_idx"] = (state["current_player_idx"] + 1) % n
        skips += 1
        if _check_game_over(state):
            return

def _calculate_scores(state):
    scores = {p["name"]: 0 for p in state["players"]}

    use_resolution = (state.get("phase") in ("date_resolution", "end")
                      and "date_resolution_pts" in state)

    if use_resolution:
        for i, player in enumerate(state["players"]):
            scores[player["name"]] += state["date_resolution_pts"].get(str(i), 0)
    else:
        # Per-(ct, day) arrival scoring: arrivals keyed by "ct_day"
        for k, arr in state["arrivals"].items():
            n = len(arr)
            if n == 0:
                continue
            parts = str(k).split("_")
            ct = int(parts[0])
            day = int(parts[1])
            if n == 1:
                # Solo arrival penalty for specific locations (Cinema/Restaurant)
                if ct in CARD_SOLO_PENALTY_CTS:
                    pidx = arr[0]
                    scores[state["players"][pidx]["name"]] -= 1
            else:
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
    def sort_key(k):
        parts = str(k).split("_")
        return (int(parts[0]), int(parts[1])) if len(parts) == 2 else (int(k), 0)
    for k, arr in sorted(state["arrivals"].items(), key=lambda x: sort_key(x[0])):
        parts = str(k).split("_")
        ct, day = int(parts[0]), int(parts[1]) if len(parts) == 2 else 0
        rows.append({
            "card_type": ct,
            "day": day,
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
        "pocketed_abilities": [None] * n,  # one slot per player; None or {card_type, strength}
        "round_start_player": 0,           # rotates each round to determine arrival order
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
    # Set up hand_cards and empty board slots for each player
    for player in state["players"]:
        player["hand_cards"] = list(player.get("draft_cards", []))
        player["cards"] = [None] * 6  # all slots empty
        player["arranged"] = True     # skip arrangement phase
    state["phase"] = "choosing"
    state["current_player_idx"] = 0
    state["ability_resolution_queue"] = []
    state["ability_resolution_cards"] = {}

def _find_card_day(state, pidx, card_type):
    """Find which day slot a player's card is on."""
    for d, c in enumerate(state["players"][pidx]["cards"]):
        if c and c.get("card_type") == card_type:
            return d + 1
    return None


def _play_from_hand(state, pidx, card_type, day):
    """Remove card_type from player's hand, place face-up in day slot, register arrival."""
    player = state["players"][pidx]
    card_info = next((c for c in player["hand_cards"] if c["card_type"] == card_type), None)
    if card_info is None:
        return False
    player["hand_cards"] = [c for c in player["hand_cards"] if c["card_type"] != card_type]
    strength = card_info.get("strength", "normal")
    slot = day - 1
    player["cards"][slot] = {
        "card_type": card_type, "face_up": True, "arrival": 0,
        "strength": strength, "banked": False,
    }
    k = _key(day, card_type)
    state["arrivals"].setdefault(k, []).append(pidx)
    player["cards"][slot]["arrival"] = len(state["arrivals"][k])
    return True


def _setup_ability_for_player(state, pidx, ct, strength):
    """Set up pocket_choice pending action for a card just placed from hand."""
    would_be_action, would_be_msg, would_be_ctx = None, None, {}

    if ct == 1:
        would_be_action = "lock_pick_day"
        would_be_msg = f"Lock ({'strong' if strength == 'strong' else 'normal'}): Choose a day to lock."
        would_be_ctx = {"actor": pidx, "strength": strength}
    elif ct == 2:
        if strength == "strong":
            would_be_action, would_be_msg = "swap_own_1", "Swap Own (strong): Click one of your cards — first of two to swap."
        else:
            would_be_action, would_be_msg = "adj_swap_own", "Swap Own (normal): Click one of your cards to shift to an adjacent day."
        would_be_ctx = {"actor": pidx, "strength": strength}
    elif ct == 3:
        if strength == "strong":
            would_be_action, would_be_msg = "swap_other_1", "Swap Others (strong): Click an opponent's card — first of two to swap."
        else:
            would_be_action, would_be_msg = "adj_swap_other", "Swap Others (normal): Click an opponent's card to shift to an adjacent day."
        would_be_ctx = {"actor": pidx, "strength": strength}
    elif ct == 4:
        if strength == "strong":
            would_be_action, would_be_msg = "swap_own_1", "Restaurant Swap Own (strong): Click one of your cards — first of two to swap."
        else:
            would_be_action, would_be_msg = "adj_swap_own", "Restaurant Shift Own (normal): Click one of your cards to shift to an adjacent day."
        would_be_ctx = {"actor": pidx, "strength": strength}
    elif ct == 5:
        # Bank: set up bank_decision directly (no pocket_choice for bank)
        state["pending_action"] = "bank_decision"
        state["action_ctx"] = {"actor": pidx, "bank_day": _find_card_day(state, pidx, ct), "strength": strength}
        state["action_message"] = f"Beach played! Bank +{2 if strength == 'strong' else 1} pts now?"
        state["current_player_idx"] = pidx
        return True  # pending set, caller should not set pocket_choice
    elif ct == 6:
        if strength == "strong":
            would_be_action, would_be_msg = "flip_own_down", "Return to Hand (strong): Click one of YOUR face-up cards to return it to your hand."
        else:
            would_be_action, would_be_msg = "flip_other_down", "Return to Hand (normal): Click an OPPONENT'S face-up card to return it to their hand."
        would_be_ctx = {"actor": pidx, "strength": strength}

    if would_be_action:
        pocket_full = state["pocketed_abilities"][pidx] is not None
        state["pending_action"] = "pocket_choice"
        state["action_ctx"] = {
            "actor": pidx,
            "pocket_ct": ct,
            "pocket_strength": strength,
            "would_be_action": would_be_action,
            "would_be_ctx": would_be_ctx,
            "would_be_msg": would_be_msg,
            "pocket_full": pocket_full,
        }
        state["action_message"] = f"{LOCATION_NAMES[ct]} played! Use ability now, pocket it, or skip?"
        state["current_player_idx"] = pidx
        return True
    return False


def _advance_ability_queue(game):
    """Process the next player in the ability resolution queue, or return to choosing."""
    state = game["state"]
    queue = state.get("ability_resolution_queue", [])

    while queue:
        pidx = queue[0]
        card_info = state.get("ability_resolution_cards", {}).get(str(pidx))
        if card_info:
            ct = card_info["ct"]
            strength = card_info["strength"]
            had_pending = _setup_ability_for_player(state, pidx, ct, strength)
            if had_pending:
                return  # stop here, wait for player input
        # No ability for this player — pop and continue
        queue.pop(0)

    # Queue exhausted
    state["ability_resolution_queue"] = []
    state["ability_resolution_cards"] = {}
    state["pending_action"] = None
    state["action_ctx"] = {}
    state["action_message"] = None

    _advance_choosing_turn(state)
    if state["phase"] == "date_resolution":
        _process_date_ai_moves(game)


def _advance_choosing_turn(state):
    """After a player's turn completes, advance to the next player with actions."""
    n = len(state["players"])
    pockets = state.get("pocketed_abilities", [None] * n)
    current = state["current_player_idx"]
    for offset in range(1, n + 1):
        next_pidx = (current + offset) % n
        hand = state["players"][next_pidx].get("hand_cards", [])
        pocket = pockets[next_pidx] if next_pidx < len(pockets) else None
        if hand or pocket is not None:
            state["current_player_idx"] = next_pidx
            state["phase"] = "choosing"
            return
    # Nobody has actions left
    state["game_over"] = True
    _start_date_resolution(state)




def _ai_choose_play(state, pidx):
    """AI picks a card from hand and an empty day slot. Returns (card_type, day) or (None, None)."""
    player = state["players"][pidx]
    hand = player.get("hand_cards", [])
    if not hand:
        return None, None

    empty_days = [d + 1 for d, c in enumerate(player["cards"]) if c is None]
    if not empty_days:
        return None, None

    ai_diffs = state.get("ai_difficulties", {})
    difficulty = ai_diffs.get(str(pidx)) or state.get("ai_difficulty", "random") or "random"

    if difficulty == "random":
        return random.choice(hand)["card_type"], random.choice(empty_days)

    # Greedy for basic/mcts: score each (card, day) pair — prefer arrival value + day-match bonus
    best_score, best_ct, best_day = -999, None, None

    for card in hand:
        ct = card["card_type"]
        pts_arr = CARD_PTS[ct]

        for day in empty_days:
            n_arr = len(state["arrivals"].get(_key(day, ct), []))
            arrival_val = pts_arr[n_arr] if n_arr < len(pts_arr) else pts_arr[-1]
            day_match_bonus = 1 if day == ct else 0
            score = arrival_val + day_match_bonus
            if score > best_score:
                best_score, best_ct, best_day = score, ct, day

    return best_ct, best_day


def _process_ai_ability_queue(game):
    """While the current player in the ability queue is an AI, auto-resolve their ability."""
    state = game["state"]
    ai_set = set(state.get("ai_players", []))
    limit = 20
    i = 0
    while (state["phase"] == "game"
           and state.get("ability_resolution_queue")
           and state["current_player_idx"] in ai_set
           and i < limit):
        pidx = state["current_player_idx"]
        # Auto-resolve: use existing AI ability logic
        card_info = state.get("ability_resolution_cards", {}).get(str(pidx), {})
        ct = card_info.get("ct")
        strength = card_info.get("strength", "normal")
        if ct:
            # Find the day this card was placed
            day = _find_card_day(state, pidx, ct)
            ai_diffs = state.get("ai_difficulties", {})
            diff = ai_diffs.get(str(pidx)) or state.get("ai_difficulty", "random") or "random"
            _rollout_ability(state, pidx, ct, strength, diff, current_day=day)
            player = state["players"][pidx]
            _log(state, f"↳ {player['name']} ability auto-resolved ({LOCATION_NAMES.get(ct, ct)})")
        # Advance queue
        if state.get("ability_resolution_queue"):
            state["ability_resolution_queue"].pop(0)
        _advance_ability_queue(game)
        i += 1
    # Note: do NOT call _process_choosing_ai here — let the caller decide.
    # This prevents mutual recursion. Callers must call _process_choosing_ai after if needed.


def _process_choosing_ai(game):
    """Auto-play for each AI player whose turn it is (sequential model)."""
    state = game["state"]
    ai_set = set(state.get("ai_players", []))
    n = len(state["players"])
    limit = 50
    turns = 0

    while turns < limit:
        if state["phase"] != "choosing":
            break
        pidx = state["current_player_idx"]
        if pidx not in ai_set:
            break  # Human's turn — stop
        pockets = state.get("pocketed_abilities", [None] * n)
        hand = state["players"][pidx].get("hand_cards", [])
        pocket = pockets[pidx] if pidx < len(pockets) else None

        if not hand and pocket is None:
            _advance_choosing_turn(state)
            if state["phase"] == "date_resolution":
                _process_date_ai_moves(game)
                break
        elif not hand and pocket is not None:
            state["pocketed_abilities"][pidx] = None
            ct, strength = pocket["card_type"], pocket["strength"]
            _log(state, f"{state['players'][pidx]['name']} used pocketed {LOCATION_NAMES[ct]} ability")
            state["turn_count"] += 1
            state["phase"] = "game"
            state["ability_resolution_queue"] = [pidx]
            state["ability_resolution_cards"] = {str(pidx): {"ct": ct, "strength": strength}}
            _advance_ability_queue(game)
        else:
            ct, day = _ai_choose_play(state, pidx)
            if ct is not None and day is not None:
                card_info = next((c for c in hand if c["card_type"] == ct), None)
                strength = card_info.get("strength", "normal") if card_info else "normal"
                if _play_from_hand(state, pidx, ct, day):
                    arr_label = {1: "1st", 2: "2nd", 3: "3rd"}.get(
                        state["players"][pidx]["cards"][day - 1]["arrival"], "#?")
                    _log(state, f"{state['players'][pidx]['name']} played "
                         f"{('★' if strength == 'strong' else '')}{LOCATION_NAMES[ct]} on Day {day} — {arr_label} to arrive")
                    state["turn_count"] += 1
                    state["phase"] = "game"
                    state["ability_resolution_queue"] = [pidx]
                    state["ability_resolution_cards"] = {str(pidx): {"ct": ct, "strength": strength}}
                    _advance_ability_queue(game)
                else:
                    _advance_choosing_turn(state)
            else:
                _advance_choosing_turn(state)

        if state["phase"] == "date_resolution":
            _process_date_ai_moves(game)
            break
        if state["phase"] == "game" and state.get("ability_resolution_queue"):
            _process_ai_ability_queue(game)
        turns += 1


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
        elif state["phase"] in ("arrangement", "game", "end", "choosing"):
            # Always expose draft_cards for self (needed for arrangement screen)
            if i == my_pidx:
                p["draft_cards"] = player.get("draft_cards", [])

        # hand_cards: expose own hand fully only
        p["hand_cards"] = player.get("hand_cards", []) if i == my_pidx else []
        p["hand_cards_count"] = len(player.get("hand_cards", []))

        if state["phase"] == "arrangement":
            # Show own cards with strength, hide opponents
            for c in player["cards"]:
                if i == my_pidx or c["face_up"]:
                    card_copy = dict(c)
                    p["cards"].append(card_copy)
                else:
                    p["cards"].append({"card_type": None, "face_up": False, "arrival": 0, "strength": None})
        elif state["phase"] == "choosing":
            # In choosing phase, cards is a list of None or placed cards
            for c in player["cards"]:
                if c is None:
                    p["cards"].append(None)
                elif i == my_pidx or c.get("face_up"):
                    p["cards"].append(dict(c))
                else:
                    p["cards"].append({"card_type": None, "face_up": False, "arrival": 0, "strength": None, "banked": False})
        else:
            # game/end phase
            for d_idx, c in enumerate(player["cards"]):
                if c is None:
                    p["cards"].append(None)
                elif i == my_pidx or c["face_up"]:
                    p["cards"].append(dict(c))
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
    out["pocketed_ability"] = state.get("pocketed_abilities", [None] * len(state["players"]))[my_pidx]

    # Draft phase extras
    if state["phase"] == "draft":
        out["draft_pool"] = state.get("draft_pool", [])
        out["draft_order"] = state.get("draft_order", [])
        out["draft_pick_idx"] = state.get("draft_pick_idx", 0)

    if state["phase"] in ("game", "end", "date_resolution", "choosing"):
        out["scores"] = _calculate_scores(state)
        out["arrivals_display"] = _arrivals_display(state)

    if state["phase"] == "choosing":
        out["is_my_turn"] = (my_pidx == state["current_player_idx"])
        out["whose_turn_name"] = state["players"][state["current_player_idx"]]["name"]

    if state["phase"] in ("date_resolution", "end"):
        out["date_queue"] = state.get("date_queue", [])
        out["current_date_ct"] = state.get("current_date_ct")
        out["current_date_day"] = state.get("current_date_day")
        out["date_results"] = state.get("date_results", [])
        out["date_resolution_pts"] = state.get("date_resolution_pts", {})
        ct = state.get("current_date_ct")
        day = state.get("current_date_day")
        if ct is not None and day is not None:
            arr = state["arrivals"].get(_key(day, ct), [])
            participants = arr[:min(len(arr), 3)]
            out["my_date_move"] = state.get("date_moves", {}).get(str(my_pidx))
            out["i_am_in_date"] = my_pidx in participants
            submitted = sum(1 for pi in participants if str(pi) in state.get("date_moves", {}))
            out["date_moves_submitted"] = submitted
            out["date_moves_total"] = len(participants)
        else:
            out["my_date_move"] = None
            out["i_am_in_date"] = False
            out["date_moves_submitted"] = 0
            out["date_moves_total"] = 0

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

def _ai_draft_pick(state, pidx):
    """Choose a card type to draft using weighted random based on DRAFT_VALUES."""
    pool = state["draft_pool"]
    if not pool:
        return None
    # Get card types already drafted by opponents (to detect potential conflicts)
    opp_drafted = set()
    for i, p in enumerate(state["players"]):
        if i != pidx:
            for c in p.get("draft_cards", []):
                opp_drafted.add(c["card_type"])
    # Use squared weights for emphasis but not fully deterministic
    weights = []
    types = []
    for card in pool:
        ct = card["card_type"]
        val = DRAFT_VALUES.get(ct, 50)
        # Slight preference for types not yet taken (less competition)
        if ct not in opp_drafted:
            val = int(val * 1.1)
        weights.append(val * val)
        types.append(ct)
    total = sum(weights)
    r = random.random() * total
    cumulative = 0
    for ct, w in zip(types, weights):
        cumulative += w
        if r <= cumulative:
            return ct
    return types[-1]


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
        # AI picks using value-weighted draft selection
        pool = state["draft_pool"]
        if not pool:
            break
        ct = _ai_draft_pick(state, cur_drafter)
        _do_draft_pick(state, cur_drafter, ct)
        i += 1
    # If draft complete, assign normal cards and process AI arrangements or choosing
    if state["phase"] == "arrangement":
        _process_ai_arrangements(game)
    elif state["phase"] == "choosing":
        _process_choosing_ai(game)

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
    ai_diffs = state.get("ai_difficulties", {})
    n = len(state["players"])
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

    elif ct == 4:  # Swap own (same as type 2)
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

    elif ct == 5:  # Bank points (AI auto-decide)
        player_cards = state["players"][pidx]["cards"]
        for card in player_cards:
            if card and card.get("card_type") == 5 and card.get("face_up") and not card.get("banked"):
                bank_pts = 2 if strength == "strong" else 1
                card_day = next((d + 1 for d, c in enumerate(player_cards) if c and c.get("card_type") == 5), None)
                arr = state["arrivals"].get(_key(card_day or 1, 5), []) if card_day else []
                arrival_val = CARD_PTS[5][arr.index(pidx)] if pidx in arr else 0
                if bank_pts > arrival_val:
                    card["banked"] = True
                break

    elif ct == 6:  # Return to hand (play-from-hand mode)
        if strength == "strong":
            targets = [
                d + 1 for d, c in enumerate(state["players"][pidx]["cards"])
                if c and c["face_up"] and not _is_locked(state, pidx, d + 1)
                and (d + 1) != current_day
            ]
            if not targets:
                targets = [
                    d + 1 for d, c in enumerate(state["players"][pidx]["cards"])
                    if c and c["face_up"] and not _is_locked(state, pidx, d + 1)
                ]
            if targets:
                _return_to_hand(state, pidx, random.choice(targets))
        else:
            opp_targets = [
                (pi, d + 1) for pi in range(len(state["players"])) if pi != pidx
                for d, c in enumerate(state["players"][pi]["cards"])
                if c and c["face_up"] and not _is_locked(state, pi, d + 1)
            ]
            if opp_targets:
                tpi, td = random.choice(opp_targets)
                _return_to_hand(state, tpi, td)


def _rollout_take_turn(state):
    """Play one random turn in a rollout simulation (no logging)."""
    if state["phase"] != "game":
        return
    pidx = state["current_player_idx"]
    player = state["players"][pidx]
    candidates = [d + 1 for d, c in enumerate(player["cards"]) if c is not None and not c["face_up"]]
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


def _smart_rollout_turn(state):
    """Play one heuristic-guided turn in a rollout simulation (no logging)."""
    if state["phase"] != "game":
        return
    pidx = state["current_player_idx"]
    player = state["players"][pidx]
    candidates = [d + 1 for d, c in enumerate(player["cards"]) if c is not None and not c["face_up"]]
    if not candidates:
        _advance_turn(state)
        return
    # Use basic heuristic flip selection, fall back to random
    day = _ai_pick_flip(state, pidx, "basic")
    if day is None:
        day = random.choice(candidates)
    _flip_up(state, pidx, day)
    card = player["cards"][day - 1]
    ct = card["card_type"]
    strength = card.get("strength", "normal")
    _rollout_ability(state, pidx, ct, strength, "basic", current_day=day)
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


def _partial_smart_rollout(state, smart_pidx):
    """Rollout turn: heuristic for the MCTS player, random for all opponents.
    Models actual game correctly when opponents are random."""
    if state["phase"] != "game":
        return
    if state["current_player_idx"] == smart_pidx:
        _smart_rollout_turn(state)
    else:
        _rollout_take_turn(state)


def _mcts_rollout_score(sim, pidx, my_name, depth=60):
    """Complete a determinized game and return own_score − avg_opponent_score."""
    steps = 0
    while sim["phase"] == "game" and steps < depth:
        _partial_smart_rollout(sim, pidx)
        steps += 1
    all_scores = _calculate_scores(sim)
    my_score = all_scores.get(my_name, 0)
    opp_scores = [v for k, v in all_scores.items() if k != my_name]
    avg_opp = sum(opp_scores) / len(opp_scores) if opp_scores else 0
    return my_score - avg_opp


def _mcts_flip_decision(state, pidx, rollouts):
    """Flat Monte Carlo: score each candidate flip with rollouts. Returns best day.
    Uses _partial_smart_rollout so opponents are simulated as random (accurate
    when facing random players; conservative when facing smart players)."""
    player = state["players"][pidx]
    candidates = [d + 1 for d, c in enumerate(player["cards"]) if c is not None and not c["face_up"]]
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
            totals[d] += _mcts_rollout_score(sim, pidx, my_name)

    return max(candidates, key=lambda d: totals[d])


# ── MCTS ability-target evaluators ───────────────────────────────────────────

def _mcts_best_swap_own_strong(state, pidx, rollouts):
    """Enumerate all own-swap pairs; return (d1,d2) with highest MC value."""
    unlocked = [d + 1 for d in range(6) if not _is_locked(state, pidx, d + 1)]
    if len(unlocked) < 2:
        return None
    pairs = [(unlocked[i], unlocked[j])
             for i in range(len(unlocked)) for j in range(i + 1, len(unlocked))]
    if len(pairs) == 1:
        return pairs[0]
    my_name = state["players"][pidx]["name"]
    n_per = max(1, rollouts // len(pairs))
    totals = [0.0] * len(pairs)
    for i, (d1, d2) in enumerate(pairs):
        for _ in range(n_per):
            sim = _determinize_state(state, pidx)
            _swap_days(sim, pidx, d1, d2)
            _advance_turn(sim)
            totals[i] += _mcts_rollout_score(sim, pidx, my_name)
    return pairs[max(range(len(pairs)), key=lambda i: totals[i])]


def _mcts_best_lock_day(state, pidx, strength, rollouts):
    """Evaluate all 6 days as lock targets; return best day."""
    candidates = list(range(1, 7))
    n = len(state["players"])
    my_name = state["players"][pidx]["name"]
    n_per = max(1, rollouts // len(candidates))
    totals = {d: 0.0 for d in candidates}
    for d in candidates:
        for _ in range(n_per):
            sim = _determinize_state(state, pidx)
            if strength == "strong":
                for pi in range(n):
                    item = [pi, d - 1]
                    if item not in sim["locks"]:
                        sim["locks"].append(item)
            else:
                items = [[pi, d - 1] for pi in range(n)]
                for item in random.sample(items, min(2, len(items))):
                    if item not in sim["locks"]:
                        sim["locks"].append(item)
            _advance_turn(sim)
            totals[d] += _mcts_rollout_score(sim, pidx, my_name)
    return max(candidates, key=lambda d: totals[d])


def _mcts_best_flip_own_down(state, pidx, rollouts, exclude_day=None):
    """Evaluate each own face-up card as flip-down target; return best day."""
    targets = [d + 1 for d, c in enumerate(state["players"][pidx]["cards"])
               if c and c["face_up"] and not _is_locked(state, pidx, d + 1)
               and (d + 1) != exclude_day]
    if not targets:
        targets = [d + 1 for d, c in enumerate(state["players"][pidx]["cards"])
                   if c and c["face_up"] and not _is_locked(state, pidx, d + 1)]
    if not targets:
        return None
    if len(targets) == 1:
        return targets[0]
    my_name = state["players"][pidx]["name"]
    n_per = max(1, rollouts // len(targets))
    totals = {t: 0.0 for t in targets}
    for t in targets:
        for _ in range(n_per):
            sim = _determinize_state(state, pidx)
            _return_to_hand(sim, pidx, t)
            _advance_turn(sim)
            totals[t] += _mcts_rollout_score(sim, pidx, my_name)
    return max(targets, key=lambda t: totals[t])




def _mcts_best_swap_other_strong(state, pidx, rollouts):
    """ct=3 strong: MC-evaluate which opponent + which 2 days to swap. Returns (tpi, d1, d2)."""
    opponents = [pi for pi in range(len(state["players"])) if pi != pidx]
    my_name = state["players"][pidx]["name"]
    best_val, best_result = -999, None

    for tpi in opponents:
        unlocked = [d + 1 for d in range(6) if not _is_locked(state, tpi, d + 1)]
        if len(unlocked) < 2:
            continue
        pairs = [(unlocked[i], unlocked[j])
                 for i in range(len(unlocked)) for j in range(i + 1, len(unlocked))]
        n_per = max(1, rollouts // max(1, len(pairs)))
        for d1, d2 in pairs:
            total = 0.0
            for _ in range(n_per):
                sim = _determinize_state(state, pidx)
                _swap_days(sim, tpi, d1, d2)
                _advance_turn(sim)
                total += _mcts_rollout_score(sim, pidx, my_name)
            avg = total / n_per
            if avg > best_val:
                best_val, best_result = avg, (tpi, d1, d2)

    return best_result  # may be None → caller falls back to basic


# ── AI logic ──────────────────────────────────────────────────────────────────

def _ai_arrange(player_draft_cards, avoid_day_match=False, always_day_match=False):
    """Assign cards to days.

    always_day_match=True: place every card on its matching day (100%).
    Strong cards default: 80% chance of matching day placement.
    Normal cards default: 50% chance of matching day placement.
    Remaining slots are filled randomly.
    """
    cards_info = list(player_draft_cards)
    days = list(range(1, 7))

    assignment = {}
    taken_days = set()

    # Separate strong and normal cards
    strong_cards = [c for c in cards_info if c.get("strength") == "strong"]
    normal_cards = [c for c in cards_info if c.get("strength") != "strong"]

    strong_p = 1.0 if always_day_match else (0.0 if avoid_day_match else 0.8)
    normal_p = 1.0 if always_day_match else (0.0 if avoid_day_match else 0.5)

    # Process strong cards first
    for card in strong_cards:
        ct = card["card_type"]
        if ct not in taken_days and random.random() < strong_p:
            assignment[ct] = ct
            taken_days.add(ct)

    # Process normal cards
    for card in normal_cards:
        ct = card["card_type"]
        if ct not in assignment and ct not in taken_days and random.random() < normal_p:
            assignment[ct] = ct
            taken_days.add(ct)

    # Assign remaining cards randomly
    remaining_cards = [c["card_type"] for c in cards_info if c["card_type"] not in assignment]
    remaining_days = [d for d in days if d not in taken_days]
    random.shuffle(remaining_days)
    for ct, day in zip(remaining_cards, remaining_days):
        assignment[ct] = day

    return assignment


def _ai_pick_flip(state, pidx, difficulty):
    """Choose a face-down card to flip. Returns day number."""
    player = state["players"][pidx]
    candidates = [d + 1 for d, c in enumerate(player["cards"]) if c is not None and not c["face_up"]]
    if not candidates:
        return None
    if difficulty == "random":
        return random.choice(candidates)

    def ct(d): return _card_at(player, d)["card_type"]
    def n_arr(d): return len(state["arrivals"].get(_key(d, ct(d)), []))

    def arrival_val(d):
        """Expected value of flipping day d, based on current global arrival count."""
        c = ct(d)
        n = n_arr(d)
        pts = CARD_PTS[c]
        if n >= len(pts):
            return pts[-1]  # 3rd or worse
        return pts[n]  # n already in queue → we'd be (n+1)th

    # Hard-veto: would become 3rd at Beach (−4 pts — devastating)
    non_veto = [d for d in candidates if not (n_arr(d) >= 2 and ct(d) == 5)]
    pool = non_veto if non_veto else candidates

    # Greedily pick the day with highest arrival value
    best_val = max(arrival_val(d) for d in pool)
    best = [d for d in pool if arrival_val(d) == best_val]
    return random.choice(best)


# ── AI ability helpers for new card types ────────────────────────────────────

def _ai_lock_target(state, pidx, strength, difficulty):
    """Type 1 Lock: pick a day to lock. Returns day (1-6)."""
    if difficulty == "random":
        return random.randint(1, 6)
    # Basic: pick day that maximises (own face-up value × 2 + opponent cards on that day)
    # Protects own strong position AND limits opponent's ability options.
    player = state["players"][pidx]
    best_day, best_val = None, -999
    for d in range(6):
        day = d + 1
        c = player["cards"][d]
        own_val = 0
        if c and c["face_up"]:
            ct = c["card_type"]
            pts = CARD_PTS[ct]
            own_val = pts[c["arrival"] - 1] if 0 <= c["arrival"] - 1 < len(pts) else 0
        opp_cards = sum(
            1 for pi in range(len(state["players"])) if pi != pidx
            if (state["players"][pi]["cards"][d] or {}).get("face_up")
        )
        val = own_val * 2 + opp_cards
        if val > best_val:
            best_val, best_day = val, day
    return best_day if best_day else random.randint(1, 6)


def _ai_swap_own_adj_target(state, pidx, difficulty):
    """Type 2 normal: pick own card and adjacent day. Returns (day, tday).
    Basic mode: prefer swaps that move a card toward its matching day."""
    player = state["players"][pidx]
    candidates = [d + 1 for d in range(6) if not _is_locked(state, pidx, d + 1)]
    if not candidates:
        return None, None
    if difficulty == "random":
        day = random.choice(candidates)
        adj = [(day - 2) % 6 + 1, day % 6 + 1]
        ua = [a for a in adj if not _is_locked(state, pidx, a)]
        return (day, random.choice(ua)) if ua else (None, None)
    # Basic: find the (day, tday) pair with the greatest day-match improvement
    best_gain, best_pair = -999, None
    for day in candidates:
        ct_a = player["cards"][day - 1]["card_type"]
        adj = [(day - 2) % 6 + 1, day % 6 + 1]
        for tday in adj:
            if _is_locked(state, pidx, tday):
                continue
            ct_b = player["cards"][tday - 1]["card_type"]
            before = (1 if ct_a == day else 0) + (1 if ct_b == tday else 0)
            after  = (1 if ct_b == day else 0) + (1 if ct_a == tday else 0)
            if after - before > best_gain:
                best_gain, best_pair = after - before, (day, tday)
    if best_pair:
        return best_pair
    day = random.choice(candidates)
    adj = [(day - 2) % 6 + 1, day % 6 + 1]
    ua = [a for a in adj if not _is_locked(state, pidx, a)]
    return (day, random.choice(ua)) if ua else (None, None)


def _ai_swap_other_strong_target(state, pidx, difficulty):
    """Type 3 strong: disrupt the opponent with highest visible score."""
    opponents = [pi for pi in range(len(state["players"])) if pi != pidx]
    if not opponents:
        return None, None, None
    if difficulty == "random":
        tpi = random.choice(opponents)
        unlocked = [d + 1 for d in range(6) if not _is_locked(state, tpi, d + 1)]
        if len(unlocked) < 2:
            return None, None, None
        d1, d2 = random.sample(unlocked, 2)
        return tpi, d1, d2
    # Basic: target the opponent with the most points locked in face-up
    def opp_score(pi):
        total = 0
        for c in state["players"][pi]["cards"]:
            if c and c["face_up"] and 0 <= c["arrival"] - 1 < 3:
                total += CARD_PTS[c["card_type"]][c["arrival"] - 1]
        return total
    tpi = max(opponents, key=opp_score)
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
        pts = CARD_PTS[ct]
        val = pts[c["arrival"] - 1] if 0 < c.get("arrival", 0) <= len(pts) else 0
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
        day_to_lock = (
            _mcts_best_lock_day(state, pidx, strength, max(rollouts // 4, 20))
            if is_mcts else _ai_lock_target(state, pidx, strength, difficulty)
        )
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
            if is_mcts:
                best_pair = _mcts_best_swap_own_strong(state, pidx, max(rollouts // 3, 20))
                if best_pair:
                    d1, d2 = best_pair
                    _swap_days(state, pidx, d1, d2)
                    _log(state, f"↳ {pname} used Swap Own (strong): swapped Day {d1} ↔ Day {d2}")
            else:
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
            if is_mcts:
                result3 = _mcts_best_swap_other_strong(state, pidx, max(rollouts // 4, 20))
                if result3:
                    tpi, d1, d2 = result3
                else:
                    tpi, d1, d2 = _ai_swap_other_strong_target(state, pidx, difficulty)
            else:
                tpi, d1, d2 = _ai_swap_other_strong_target(state, pidx, difficulty)
            if tpi is not None:
                _swap_days(state, tpi, d1, d2)
                _log(state, f"↳ {pname} used Swap Others (strong): swapped {state['players'][tpi]['name']}'s Day {d1} ↔ Day {d2}")
        else:
            tpi, day_s, tday_s = _ai_swap_other_adj_target(state, pidx, difficulty)
            if tpi is not None:
                _swap_days(state, tpi, day_s, tday_s)
                _log(state, f"↳ {pname} used Swap Others (normal): shifted {state['players'][tpi]['name']}'s Day {day_s} → Day {tday_s}")

    elif ct == 4:  # Swap own (same mechanic as type 2)
        if strength == "strong":
            if is_mcts:
                best_pair = _mcts_best_swap_own_strong(state, pidx, max(rollouts // 3, 20))
                if best_pair:
                    d1, d2 = best_pair
                    _swap_days(state, pidx, d1, d2)
                    _log(state, f"↳ {pname} used Restaurant Swap Own (strong): swapped Day {d1} ↔ Day {d2}")
            else:
                unlocked = [d + 1 for d in range(6) if not _is_locked(state, pidx, d + 1)]
                if len(unlocked) >= 2:
                    d1, d2 = random.sample(unlocked, 2)
                    _swap_days(state, pidx, d1, d2)
                    _log(state, f"↳ {pname} used Restaurant Swap Own (strong): swapped Day {d1} ↔ Day {d2}")
        else:
            day_s, tday_s = _ai_swap_own_adj_target(state, pidx, difficulty)
            if day_s is not None:
                _swap_days(state, pidx, day_s, tday_s)
                _log(state, f"↳ {pname} used Restaurant Shift Own (normal): shifted Day {day_s} → Day {tday_s}")

    elif ct == 5:  # Bank points — AI auto-decide
        bank_pts = 2 if strength == "strong" else 1
        arr = state["arrivals"].get(str(5), [])
        arrival_val = CARD_PTS[5][arr.index(pidx)] if pidx in arr else 0
        if bank_pts > arrival_val:
            card["banked"] = True
            _log(state, f"↳ {pname} banked Beach card (+{bank_pts} pts)")
        else:
            card["banked"] = False
            _log(state, f"↳ {pname} kept Beach card for day-match bonus")

    elif ct == 6:  # Return to hand
        if strength == "strong":
            tday = (
                _mcts_best_flip_own_down(state, pidx, max(rollouts // 4, 20), exclude_day=day)
                if is_mcts else _ai_flip_down_strong_target(state, pidx, difficulty, exclude_day=day)
            )
            if tday is not None:
                tcard = _card_at(player, tday)
                tct = tcard["card_type"] if tcard else ct
                _return_to_hand(state, pidx, tday)
                _log(state, f"↳ {pname} used Return to Hand (strong): returned own {LOCATION_NAMES[tct]} (Day {tday}) to hand")
        else:
            result = _ai_flip_down_normal_target(state, pidx, difficulty)
            if result[0] is not None:
                tpi, tday = result
                tcard = _card_at(state["players"][tpi], tday)
                tct = tcard["card_type"] if tcard else ct
                _return_to_hand(state, tpi, tday)
                _log(state, f"↳ {pname} used Return to Hand (normal): returned {state['players'][tpi]['name']}'s {LOCATION_NAMES[tct]} (Day {tday}) to hand")

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
        and not state.get("ability_resolution_queue")
        and i < limit
    ):
        _ai_take_turn(game)
        i += 1
    if state["phase"] == "date_resolution":
        _process_date_ai_moves(game)
    # Handle ability queue for AI
    if state["phase"] == "game" and state.get("ability_resolution_queue"):
        _process_ai_ability_queue(game)
    # Handle choosing phase for AI
    if state["phase"] == "choosing":
        _process_choosing_ai(game)

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
    elif state["phase"] == "choosing":
        _process_choosing_ai(game)
    else:
        # Process any consecutive AI picks
        _process_draft_picks(game)
        if state["phase"] == "arrangement":
            _process_ai_arrangements(game)
            if state["phase"] == "game":
                _process_ai_turns(game)
        elif state["phase"] == "choosing":
            _process_choosing_ai(game)

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

@app.route("/api/game/<game_id>/<token>/choose_play", methods=["POST"])
def api_choose_play(game_id, token):
    """Play a card from hand immediately (sequential turn model)."""
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["phase"] != "choosing":
        return jsonify({"error": "Not in choosing phase"}), 400
    if pidx != state["current_player_idx"]:
        return jsonify({"error": "Not your turn"}), 400

    data = request.json or {}
    card_type = int(data.get("card_type", -1))
    day = int(data.get("day", -1))

    player = state["players"][pidx]
    hand = player.get("hand_cards", [])
    if not any(c["card_type"] == card_type for c in hand):
        return jsonify({"error": "Card not in hand"}), 400
    empty_days = [d + 1 for d, c in enumerate(player["cards"]) if c is None]
    if day not in empty_days:
        return jsonify({"error": "Day slot not available"}), 400

    card_info = next((c for c in hand if c["card_type"] == card_type), None)
    strength = card_info.get("strength", "normal") if card_info else "normal"

    if not _play_from_hand(state, pidx, card_type, day):
        return jsonify({"error": "Failed to play card"}), 400

    arr_label = {1: "1st", 2: "2nd", 3: "3rd"}.get(player["cards"][day - 1]["arrival"], "#?")
    _log(state, f"{player['name']} played {('★' if strength == 'strong' else '')}{LOCATION_NAMES[card_type]} on Day {day} — {arr_label} to arrive")

    state["turn_count"] += 1
    state["phase"] = "game"
    state["ability_resolution_queue"] = [pidx]
    state["ability_resolution_cards"] = {str(pidx): {"ct": card_type, "strength": strength}}

    _advance_ability_queue(game)

    if state["phase"] == "choosing":
        _process_choosing_ai(game)
    if state["phase"] == "game" and state.get("ability_resolution_queue"):
        _process_ai_ability_queue(game)
        if state["phase"] == "choosing":
            _process_choosing_ai(game)

    return jsonify(_state_for_player(game, pidx))


@app.route("/api/game/<game_id>/<token>/choose_pocket", methods=["POST"])
def api_choose_pocket(game_id, token):
    """Use pocketed ability as this turn's action (sequential turn model)."""
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["phase"] != "choosing":
        return jsonify({"error": "Not in choosing phase"}), 400
    if pidx != state["current_player_idx"]:
        return jsonify({"error": "Not your turn"}), 400
    hand = state["players"][pidx].get("hand_cards", [])
    if hand:
        return jsonify({"error": "Must play a card from your hand first"}), 400
    pockets = state.get("pocketed_abilities", [])
    pocket = pockets[pidx] if pidx < len(pockets) else None
    if pocket is None:
        return jsonify({"error": "No pocketed ability"}), 400

    state["pocketed_abilities"][pidx] = None
    ct, strength = pocket["card_type"], pocket["strength"]
    _log(state, f"{state['players'][pidx]['name']} used pocketed {LOCATION_NAMES[ct]} ability")

    state["turn_count"] += 1
    state["phase"] = "game"
    state["ability_resolution_queue"] = [pidx]
    state["ability_resolution_cards"] = {str(pidx): {"ct": ct, "strength": strength}}

    _advance_ability_queue(game)

    if state["phase"] == "choosing":
        _process_choosing_ai(game)
    if state["phase"] == "game" and state.get("ability_resolution_queue"):
        _process_ai_ability_queue(game)
        if state["phase"] == "choosing":
            _process_choosing_ai(game)

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
    # Determine what ability would fire
    would_be_action, would_be_msg, would_be_ctx = None, None, {}

    if ct == 1:  # Lock
        if strength == "strong":
            would_be_action = "lock_pick_day"
            would_be_msg = "Lock (strong): Choose a day — ALL cards on that day will be locked."
            would_be_ctx = {"actor": pidx, "strength": "strong"}
        else:
            would_be_action = "lock_pick_day"
            would_be_msg = "Lock (normal): Choose a day, then select 2 cards to lock."
            would_be_ctx = {"actor": pidx, "strength": "normal"}

    elif ct == 2:  # Swap own
        if strength == "strong":
            would_be_action = "swap_own_1"
            would_be_msg = "Swap Own (strong): Click one of your cards — first of two to swap."
            would_be_ctx = {"actor": pidx, "strength": "strong"}
        else:
            would_be_action = "adj_swap_own"
            would_be_msg = "Swap Own (normal): Click one of your cards to shift it to an adjacent day."
            would_be_ctx = {"actor": pidx, "strength": "normal"}

    elif ct == 3:  # Swap others
        if strength == "strong":
            would_be_action = "swap_other_1"
            would_be_msg = "Swap Others (strong): Click an opponent's card — first of two to swap."
            would_be_ctx = {"actor": pidx, "strength": "strong"}
        else:
            would_be_action = "adj_swap_other"
            would_be_msg = "Swap Others (normal): Click an opponent's card to shift it to an adjacent day."
            would_be_ctx = {"actor": pidx, "strength": "normal"}

    elif ct == 4:  # Swap own
        if strength == "strong":
            would_be_action = "swap_own_1"
            would_be_msg = "Restaurant Swap Own (strong): Click one of your cards — first of two to swap."
            would_be_ctx = {"actor": pidx, "strength": "strong"}
        else:
            would_be_action = "adj_swap_own"
            would_be_msg = "Restaurant Shift Own (normal): Click one of your cards to shift to an adjacent day."
            would_be_ctx = {"actor": pidx, "strength": "normal"}

    elif ct == 5:  # Bank points — immediate decision, no pocketing
        state["action_ctx"] = {"actor": pidx, "bank_day": day, "strength": strength}
        state["pending_action"] = "bank_decision"
        bank_pts = 2 if strength == "strong" else 1
        state["action_message"] = f"Beach card flipped! Bank +{bank_pts} pts now, or keep for day-matching bonus?"
        return jsonify(_state_for_player(game, pidx))

    elif ct == 6:  # Return to hand
        if strength == "strong":
            would_be_action = "flip_own_down"
            would_be_msg = "Return to Hand (strong): Click one of YOUR face-up cards to return it to your hand."
            would_be_ctx = {"actor": pidx, "strength": "strong"}
        else:
            would_be_action = "flip_other_down"
            would_be_msg = "Return to Hand (normal): Click an OPPONENT'S face-up card to return it to their hand."
            would_be_ctx = {"actor": pidx, "strength": "normal"}

    if would_be_action:
        pocket_full = state["pocketed_abilities"][pidx] is not None
        state["pending_action"] = "pocket_choice"
        state["action_ctx"] = {
            "actor": pidx,
            "pocket_ct": ct,
            "pocket_strength": strength,
            "would_be_action": would_be_action,
            "would_be_ctx": would_be_ctx,
            "would_be_msg": would_be_msg,
            "pocket_full": pocket_full,
        }
        state["action_message"] = (
            f"{LOCATION_NAMES[ct]} ability ready! Use now, pocket for later, or skip?"
        )
    else:
        _advance_turn(state)
        _process_ai_turns(game)

    return jsonify(_state_for_player(game, pidx))

@app.route("/api/game/<game_id>/<token>/make_move", methods=["POST"])
def api_make_move(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["phase"] != "date_resolution":
        return jsonify({"error": "Not in date resolution phase"}), 400

    ct = state.get("current_date_ct")
    day = state.get("current_date_day")
    if ct is None or day is None:
        return jsonify({"error": "No active date"}), 400

    arr = state["arrivals"].get(_key(day, ct), [])
    participants = arr[:min(len(arr), 3)]

    if pidx not in participants:
        return jsonify({"error": "You are not in this date"}), 400
    if str(pidx) in state.get("date_moves", {}):
        return jsonify({"error": "Already decided for this date"}), 400

    make_move = bool(request.json.get("make_move", False))
    state.setdefault("date_moves", {})[str(pidx)] = make_move

    move_word = "made a move" if make_move else "played it safe"
    _log(state, f"{state['players'][pidx]['name']} {move_word} at {LOCATION_NAMES[ct]} (hidden until reveal)")

    _process_date_ai_moves(game)

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
    if state.get("ability_resolution_queue") is not None and len(state.get("ability_resolution_queue", [])) > 0:
        # Hand mode: pop current player from queue and advance
        state["ability_resolution_queue"].pop(0)
        _advance_ability_queue(game)
        _process_ai_ability_queue(game)
        if state["phase"] == "choosing":
            _process_choosing_ai(game)
    else:
        _advance_turn(state)
        _process_ai_turns(game)
    return jsonify(_state_for_player(game, pidx))

@app.route("/api/game/<game_id>/<token>/use_pocket", methods=["POST"])
def api_use_pocket(game_id, token):
    """Use the player's pocketed ability instead of flipping a card this turn."""
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["phase"] != "game" or state["pending_action"]:
        return jsonify({"error": "Cannot use pocketed ability now"}), 400
    if pidx != state["current_player_idx"]:
        return jsonify({"error": "Not your turn"}), 400

    pocket = state["pocketed_abilities"][pidx]
    if pocket is None:
        return jsonify({"error": "No pocketed ability"}), 400

    ct = pocket["card_type"]
    strength = pocket["strength"]
    state["pocketed_abilities"][pidx] = None

    pending, msg = None, None

    if ct == 1:
        pending = "lock_pick_day"
        msg = f"Pocketed Lock ({'strong' if strength == 'strong' else 'normal'}): Choose a day to lock."
        state["action_ctx"] = {"actor": pidx, "strength": strength}
    elif ct == 2:
        if strength == "strong":
            pending = "swap_own_1"
            msg = "Pocketed Swap Own (strong): Click one of your cards — first of two to swap."
        else:
            pending = "adj_swap_own"
            msg = "Pocketed Swap Own (normal): Click one of your cards to shift to an adjacent day."
        state["action_ctx"] = {"actor": pidx, "strength": strength}
    elif ct == 3:
        if strength == "strong":
            pending = "swap_other_1"
            msg = "Pocketed Swap Others (strong): Click an opponent's card — first of two to swap."
        else:
            pending = "adj_swap_other"
            msg = "Pocketed Swap Others (normal): Click an opponent's card to shift to an adjacent day."
        state["action_ctx"] = {"actor": pidx, "strength": strength}
    elif ct == 4:
        if strength == "strong":
            pending = "swap_own_1"
            msg = "Pocketed Restaurant Swap Own (strong): Click one of your cards — first of two to swap."
        else:
            pending = "adj_swap_own"
            msg = "Pocketed Restaurant Shift Own (normal): Click one of your cards to shift to an adjacent day."
        state["action_ctx"] = {"actor": pidx, "strength": strength}
    elif ct == 6:
        if strength == "strong":
            pending = "flip_own_down"
            msg = "Banked Return to Hand (strong): Click one of YOUR face-up cards to return it to your hand."
        else:
            pending = "flip_other_down"
            msg = "Banked Return to Hand (normal): Click an OPPONENT'S face-up card to return it to their hand."
        state["action_ctx"] = {"actor": pidx, "strength": strength}

    _log(state, f"{state['players'][pidx]['name']} used pocketed {LOCATION_NAMES[ct]} ability")

    if pending:
        state["pending_action"] = pending
        state["action_message"] = msg
    else:
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
                f"Selected your Day {tday}. Now click another one of your days (can be empty) to swap."
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
                f"Selected Day {tday}. Now click an adjacent day (Day {adj[0]} or Day {adj[1]}) — can be empty."
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
                "Now click another of their days (can be empty) to swap."
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
                f"Now click their adjacent day (Day {adj[0]} or Day {adj[1]}) — can be empty."
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

    # ── Pocket choice ─────────────────────────────────────────────────────────
    elif action == "pocket_choice":
        choice = data.get("choice")
        if choice == "use_now":
            state["pending_action"] = ctx["would_be_action"]
            state["action_ctx"] = dict(ctx["would_be_ctx"])
            state["action_message"] = ctx.get("would_be_msg", "")
            resp = _state_for_player(game, pidx)
            resp["action_result"] = {"error": None, "done": False}
            return jsonify(resp)
        elif choice == "use_banked":
            # Use the banked ability, bank this card's ability in its place
            banked = state["pocketed_abilities"][pidx]
            if not banked:
                err = "No banked ability to use."
            else:
                # Bank the current card's ability
                state["pocketed_abilities"][pidx] = {
                    "card_type": ctx["pocket_ct"], "strength": ctx["pocket_strength"]
                }
                _log(state, f"{state['players'][pidx]['name']} used banked {LOCATION_NAMES[banked['card_type']]} ability (banked {LOCATION_NAMES[ctx['pocket_ct']]})")
                # Execute the banked ability
                bct, bstrength = banked["card_type"], banked["strength"]
                pending_b, msg_b, ctx_b = None, None, {}
                if bct == 1:
                    pending_b = "lock_pick_day"
                    msg_b = f"Banked Lock ({'strong' if bstrength == 'strong' else 'normal'}): Choose a day to lock."
                    ctx_b = {"actor": pidx, "strength": bstrength}
                elif bct == 2:
                    if bstrength == "strong":
                        pending_b, msg_b = "swap_own_1", "Banked Swap Own (strong): Click one of your cards — first of two to swap."
                    else:
                        pending_b, msg_b = "adj_swap_own", "Banked Swap Own (normal): Click one of your cards to shift to an adjacent day."
                    ctx_b = {"actor": pidx, "strength": bstrength}
                elif bct == 3:
                    if bstrength == "strong":
                        pending_b, msg_b = "swap_other_1", "Banked Swap Others (strong): Click an opponent's card — first of two to swap."
                    else:
                        pending_b, msg_b = "adj_swap_other", "Banked Swap Others (normal): Click an opponent's card to shift to an adjacent day."
                    ctx_b = {"actor": pidx, "strength": bstrength}
                elif bct == 4:
                    if bstrength == "strong":
                        pending_b, msg_b = "swap_own_1", "Banked Restaurant Swap Own (strong): Click one of your cards — first of two to swap."
                    else:
                        pending_b, msg_b = "adj_swap_own", "Banked Restaurant Shift Own (normal): Click one of your cards to shift to an adjacent day."
                    ctx_b = {"actor": pidx, "strength": bstrength}
                elif bct == 6:
                    if bstrength == "strong":
                        pending_b, msg_b = "flip_own_down", "Banked Return to Hand (strong): Click one of YOUR face-up cards."
                    else:
                        pending_b, msg_b = "flip_other_down", "Banked Return to Hand (normal): Click an OPPONENT'S face-up card."
                    ctx_b = {"actor": pidx, "strength": bstrength}
                if pending_b:
                    state["pending_action"] = pending_b
                    state["action_ctx"] = ctx_b
                    state["action_message"] = msg_b
                    resp = _state_for_player(game, pidx)
                    resp["action_result"] = {"error": None, "done": False}
                    return jsonify(resp)
                else:
                    done = True
        elif choice == "bank":
            state["pocketed_abilities"][pidx] = {
                "card_type": ctx["pocket_ct"], "strength": ctx["pocket_strength"]
            }
            _log(state, f"{state['players'][pidx]['name']} banked {LOCATION_NAMES[ctx['pocket_ct']]} ability")
            done = True
        else:  # "skip"
            _log(state, f"{state['players'][pidx]['name']} skipped {LOCATION_NAMES[ctx['pocket_ct']]} ability")
            done = True



    # ── Return to hand (type 6) ───────────────────────────────────────────────
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
                ct_name = LOCATION_NAMES[card["card_type"]]
                _return_to_hand(state, tpi, tday)
                success_msg = f"Returned {state['players'][tpi]['name']}'s {ct_name} to their hand!"
                _log(state, f"↳ {state['players'][actor]['name']} used Return to Hand (normal): returned {state['players'][tpi]['name']}'s {ct_name} (Day {tday}) to hand")
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
                ct_name = LOCATION_NAMES[card["card_type"]]
                _return_to_hand(state, tpi, tday)
                success_msg = f"Returned your {ct_name} (Day {tday}) to your hand!"
                _log(state, f"↳ {state['players'][actor]['name']} used Return to Hand (strong): returned own {ct_name} (Day {tday}) to hand")
                done = True

    if done:
        state["pending_action"] = None
        state["action_ctx"] = {}
        state["action_message"] = None
        if state.get("ability_resolution_queue") is not None and len(state.get("ability_resolution_queue", [])) > 0:
            # Hand mode: pop current player from queue and advance
            state["ability_resolution_queue"].pop(0)
            _advance_ability_queue(game)
            _process_ai_ability_queue(game)
            if state["phase"] == "choosing":
                _process_choosing_ai(game)
        else:
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
    if state.get("ability_resolution_queue") is not None and len(state.get("ability_resolution_queue", [])) > 0:
        # Hand mode: pop current player from queue and advance
        state["ability_resolution_queue"].pop(0)
        _advance_ability_queue(game)
        _process_ai_ability_queue(game)
        if state["phase"] == "choosing":
            _process_choosing_ai(game)
    else:
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

        # Process AI draft picks, arrangements, and choosing phase
        _process_draft_picks(game)
        if state["phase"] == "game":
            _process_ai_turns(game)
        elif state["phase"] == "choosing":
            _process_choosing_ai(game)

        for i, rp in enumerate(room["players"]):
            rp["game_token"] = game_tokens[i]
        room["game_id"] = game_id
        room["status"] = "started"
        room["version"] += 1

    return jsonify(_room_view(room, lobby_token))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
