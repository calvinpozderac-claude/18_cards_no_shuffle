import uuid
import random
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
app.secret_key = "dtbtw-ai-secret-2024"

GAMES = {}

LOCATION_NAMES = {
    1: "Coffee Shop",
    2: "Park",
    3: "Cinema",
    4: "Restaurant",
    5: "Beach",
    6: "Museum",
}

CARD_ABILITIES = {
    1: "Flip an opponent's face-up card face down",
    2: "Flip one of your own face-up cards face down",
    3: "Swap the day slots of 2 of another player's cards",
    4: "Swap the day slots of 2 of your own cards",
    5: "Change the arrival order of an opponent's face-up card",
    6: "Change the arrival order of one of your own face-up cards",
}

# ── core game logic ───────────────────────────────────────────────────────────

def _card_at(player, day):
    return player["cards"][day - 1] if 1 <= day <= 6 else None

def _key(day, ct):
    return f"{day},{ct}"

def _renumber(state, day, ct):
    for i, pidx in enumerate(state["arrivals"].get(_key(day, ct), [])):
        _card_at(state["players"][pidx], day)["arrival"] = i + 1

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
    k = _key(day, card["card_type"])
    arr = state["arrivals"].get(k, [])
    if pidx in arr:
        arr.remove(pidx)
        state["arrivals"][k] = arr
        _renumber(state, day, card["card_type"])
    card["face_up"] = False
    card["arrival"] = 0
    return True

def _swap_days(state, pidx, day1, day2):
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
    for k, arr in state["arrivals"].items():
        n = len(arr)
        if n == 2:
            scores[state["players"][arr[0]]["name"]] += 1
            scores[state["players"][arr[1]]["name"]] += 2
        elif n >= 3:
            scores[state["players"][arr[2]]["name"]] -= 1
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
    return {
        "phase": "arrangement",
        "players": [{"name": n, "cards": [], "arranged": False} for n in player_names],
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
    }

def _state_for_player(game, my_pidx):
    state = game["state"]
    players_out = []
    for i, player in enumerate(state["players"]):
        p = {"name": player["name"], "arranged": player["arranged"],
             "is_me": i == my_pidx, "cards": []}
        for c in player["cards"]:
            if i == my_pidx or c["face_up"]:
                p["cards"].append(dict(c))
            else:
                p["cards"].append({"card_type": None, "face_up": False, "arrival": 0})
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
        "move_log": state.get("move_log", []),
    }
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

# ── AI logic ──────────────────────────────────────────────────────────────────

def _ai_arrange():
    """Random card-to-day assignment."""
    days = list(range(1, 7))
    random.shuffle(days)
    return {ct: days[ct - 1] for ct in range(1, 7)}


def _ai_pick_flip(state, pidx, difficulty):
    """Choose a face-down card to flip. Returns day number."""
    player = state["players"][pidx]
    candidates = [d + 1 for d, c in enumerate(player["cards"]) if not c["face_up"]]
    if not candidates:
        return None
    if difficulty == "random":
        return random.choice(candidates)

    # Basic: prefer 2nd arrival (+2 pts), then avoid 3rd (−1 pt)
    second = [d for d in candidates
              if len(state["arrivals"].get(_key(d, _card_at(player, d)["card_type"]), [])) == 1]
    if second:
        return random.choice(second)

    safe = [d for d in candidates
            if len(state["arrivals"].get(_key(d, _card_at(player, d)["card_type"]), [])) < 2]
    return random.choice(safe) if safe else random.choice(candidates)


def _ai_flip_other_target(state, pidx, difficulty):
    """Card 1: pick which opponent face-up card to flip down. Returns (tpi, tday)."""
    targets = [
        (pi, d + 1, c)
        for pi, p in enumerate(state["players"]) if pi != pidx
        for d, c in enumerate(p["cards"]) if c["face_up"]
    ]
    if not targets:
        return None, None
    if difficulty == "random":
        t = random.choice(targets)
        return t[0], t[1]

    # Basic: target the opponent scoring the most (2nd arrival = +2)
    best, best_val = None, -1
    for tpi, tday, card in targets:
        k = _key(tday, card["card_type"])
        arr = state["arrivals"].get(k, [])
        val = {(2, 2): 2, (2, 1): 1}.get((len(arr), card["arrival"]), 0)
        if val > best_val:
            best_val, best = val, (tpi, tday)
    return best or (targets[0][0], targets[0][1])


def _ai_flip_own_target(state, pidx, difficulty):
    """Card 2: pick which of own face-up cards to flip down. Returns tday."""
    targets = [d + 1 for d, c in enumerate(state["players"][pidx]["cards"]) if c["face_up"]]
    if not targets:
        return None
    if difficulty == "random":
        return random.choice(targets)

    # Basic: escape 3rd-wheel (-1) first, then 1st arrival on a solo day
    player = state["players"][pidx]
    for d, c in enumerate(player["cards"]):
        if c["face_up"] and c["arrival"] == 3:
            return d + 1
    for d, c in enumerate(player["cards"]):
        if c["face_up"] and c["arrival"] == 1:
            if len(state["arrivals"].get(_key(d + 1, c["card_type"]), [])) == 1:
                return d + 1
    return random.choice(targets)


def _ai_swap_other_targets(state, pidx, difficulty):
    """Card 3: pick two of an opponent's cards to swap. Returns (tpi, day1, day2)."""
    opponents = [pi for pi in range(len(state["players"])) if pi != pidx]
    if not opponents:
        return None, None, None
    tpi = random.choice(opponents)
    days = random.sample(range(1, 7), 2)
    return tpi, days[0], days[1]


def _ai_swap_own_targets(state, pidx, difficulty):
    """Card 4: pick two of own cards to swap. Returns (day1, day2)."""
    if difficulty == "random":
        return random.sample(range(1, 7), 2)

    # Basic: try to put a face-down card onto a day where an opponent has the same type
    player = state["players"][pidx]
    for d, c in enumerate(player["cards"]):
        if c["face_up"]:
            continue
        ct, my_day = c["card_type"], d + 1
        for pi, p in enumerate(state["players"]):
            if pi == pidx:
                continue
            for d2, c2 in enumerate(p["cards"]):
                target_day = d2 + 1
                if c2["face_up"] and c2["card_type"] == ct and target_day != my_day:
                    # Swap my_day with whatever is at target_day in my hand
                    return my_day, target_day
    return random.sample(range(1, 7), 2)


def _ai_change_arr_other_target(state, pidx, difficulty):
    """Card 5: pick opponent card + new arrival position. Returns (tpi, tday, new_pos)."""
    candidates = [
        (pi, d + 1, c, state["arrivals"].get(_key(d + 1, c["card_type"]), []))
        for pi, p in enumerate(state["players"]) if pi != pidx
        for d, c in enumerate(p["cards"])
        if c["face_up"] and len(state["arrivals"].get(_key(d + 1, c["card_type"]), [])) >= 2
    ]
    if not candidates:
        return None, None, None
    if difficulty == "random":
        tpi, tday, card, arr = random.choice(candidates)
        return tpi, tday, random.randint(1, len(arr))

    # Basic: make opponent 3rd wheel if possible; otherwise knock 2nd to 1st
    best, best_gain = None, 0
    for tpi, tday, card, arr in candidates:
        n = len(arr)
        if n == 3 and card["arrival"] < 3:
            if 3 > best_gain:
                best_gain, best = 3, (tpi, tday, 3)
        elif n == 2 and card["arrival"] == 2:
            gain = 2 if (pidx in arr and arr[0] == pidx) else 1
            if gain > best_gain:
                best_gain, best = gain, (tpi, tday, 1)
    if best:
        return best
    tpi, tday, _, arr = random.choice(candidates)
    return tpi, tday, 1


def _ai_change_arr_own_target(state, pidx, difficulty):
    """Card 6: pick own card + new arrival position. Returns (tday, new_pos)."""
    player = state["players"][pidx]
    candidates = [
        (d + 1, c, state["arrivals"].get(_key(d + 1, c["card_type"]), []))
        for d, c in enumerate(player["cards"])
        if c["face_up"] and len(state["arrivals"].get(_key(d + 1, c["card_type"]), [])) >= 2
    ]
    if not candidates:
        return None, None
    if difficulty == "random":
        tday, card, arr = random.choice(candidates)
        return tday, random.randint(1, len(arr))

    # Basic: move to 2nd position (best score on a 2-player day)
    for tday, card, arr in candidates:
        if len(arr) >= 2 and card["arrival"] != 2:
            return tday, min(2, len(arr))
    tday, _, arr = random.choice(candidates)
    return tday, min(2, len(arr))


def _ai_take_turn(game):
    """Execute one complete AI turn: flip + resolve ability in one shot."""
    state = game["state"]
    pidx = state["current_player_idx"]
    difficulty = state.get("ai_difficulty", "random")
    player = state["players"][pidx]
    pname = player["name"]

    day = _ai_pick_flip(state, pidx, difficulty)
    if day is None:
        _advance_turn(state)
        return

    _flip_up(state, pidx, day)
    ct = player["cards"][day - 1]["card_type"]
    arr_label = {1: "1st", 2: "2nd", 3: "3rd"}.get(player["cards"][day - 1]["arrival"], f"#{player['cards'][day - 1]['arrival']}")
    _log(state, f"{pname} flipped {LOCATION_NAMES[ct]} on Day {day} — {arr_label} to arrive")

    if ct == 1:
        tpi, tday = _ai_flip_other_target(state, pidx, difficulty)
        if tpi is not None:
            tcard = _card_at(state["players"][tpi], tday)
            tct = tcard["card_type"] if tcard else ct
            _flip_down(state, tpi, tday)
            _log(state, f"↳ {pname} used Coffee Shop: flipped {state['players'][tpi]['name']}'s {LOCATION_NAMES[tct]} (Day {tday}) face down")

    elif ct == 2:
        tday = _ai_flip_own_target(state, pidx, difficulty)
        if tday is not None:
            tcard = _card_at(player, tday)
            tct = tcard["card_type"] if tcard else ct
            _flip_down(state, pidx, tday)
            _log(state, f"↳ {pname} used Park: flipped own {LOCATION_NAMES[tct]} (Day {tday}) face down")

    elif ct == 3:
        tpi, d1, d2 = _ai_swap_other_targets(state, pidx, difficulty)
        if tpi is not None:
            _swap_days(state, tpi, d1, d2)
            _log(state, f"↳ {pname} used Cinema: swapped {state['players'][tpi]['name']}'s Day {d1} ↔ Day {d2}")

    elif ct == 4:
        d1, d2 = _ai_swap_own_targets(state, pidx, difficulty)
        if d1 is not None and d1 != d2:
            _swap_days(state, pidx, d1, d2)
            _log(state, f"↳ {pname} used Restaurant: swapped own Day {d1} ↔ Day {d2}")

    elif ct == 5:
        tpi, tday, new_pos = _ai_change_arr_other_target(state, pidx, difficulty)
        if tpi is not None:
            tcard = _card_at(state["players"][tpi], tday)
            tct = tcard["card_type"] if tcard else ct
            _change_arrival(state, tpi, tday, new_pos)
            _log(state, f"↳ {pname} used Beach: {state['players'][tpi]['name']}'s {LOCATION_NAMES[tct]} arrival → #{new_pos}")

    elif ct == 6:
        tday, new_pos = _ai_change_arr_own_target(state, pidx, difficulty)
        if tday is not None:
            tcard = _card_at(player, tday)
            tct = tcard["card_type"] if tcard else ct
            _change_arrival(state, pidx, tday, new_pos)
            _log(state, f"↳ {pname} used Museum: own {LOCATION_NAMES[tct]} arrival → #{new_pos}")

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

@app.route("/api/create", methods=["POST"])
def api_create():
    data = request.json
    vs_ai = data.get("vs_ai", False)

    if vs_ai:
        human_name = str(data.get("human_name", "Player 1")).strip() or "Player 1"
        difficulty = data.get("ai_difficulty", "random")
        label = "Random" if difficulty == "random" else "Strategic"
        player_names = [human_name, f"Bot 1 ({label})", f"Bot 2 ({label})"]

        game_id = uuid.uuid4().hex[:10]
        tokens = [uuid.uuid4().hex for _ in range(3)]
        state = _new_state(player_names)
        state["ai_players"] = [1, 2]
        state["ai_difficulty"] = difficulty

        # Pre-arrange both AI players
        for ai_pidx in [1, 2]:
            cards = [None] * 6
            for ct, day in _ai_arrange().items():
                cards[day - 1] = {"card_type": ct, "face_up": False, "arrival": 0}
            state["players"][ai_pidx]["cards"] = cards
            state["players"][ai_pidx]["arranged"] = True

        GAMES[game_id] = {"state": state, "tokens": tokens}
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

@app.route("/api/game/<game_id>/<token>/arrange", methods=["POST"])
def api_arrange(game_id, token):
    game, pidx = _resolve(game_id, token)
    if game is None or pidx is None:
        return jsonify({"error": "not found"}), 404
    state = game["state"]
    if state["phase"] != "arrangement" or state["players"][pidx]["arranged"]:
        return jsonify({"error": "Cannot arrange now"}), 400
    cards = [None] * 6
    for ct_str, day in request.json.get("arrangement", {}).items():
        cards[int(day) - 1] = {"card_type": int(ct_str), "face_up": False, "arrival": 0}
    state["players"][pidx]["cards"] = cards
    state["players"][pidx]["arranged"] = True
    if all(p["arranged"] for p in state["players"]):
        state["phase"] = "game"
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
    arr_label = {1: "1st", 2: "2nd", 3: "3rd"}.get(card["arrival"], f"#{card['arrival']}")
    _log(state, f"{player['name']} flipped {LOCATION_NAMES[ct]} on Day {day} — {arr_label} to arrive")
    pending, msg = None, None

    if ct == 1:
        if any(c["face_up"] for pi, p in enumerate(state["players"])
               if pi != pidx for c in p["cards"]):
            pending = "flip_other_down"
            msg = f"Card 1 – {LOCATION_NAMES[1]}: Click an opponent's face-up card to flip it face down."
    elif ct == 2:
        if any(c["face_up"] for c in player["cards"]):
            pending = "flip_own_down"
            msg = f"Card 2 – {LOCATION_NAMES[2]}: Click one of your face-up cards to flip it face down."
    elif ct == 3:
        pending = "swap_other_1"
        msg = f"Card 3 – {LOCATION_NAMES[3]}: Click another player's card — first of two to swap days."
    elif ct == 4:
        pending = "swap_own_1"
        msg = f"Card 4 – {LOCATION_NAMES[4]}: Click one of your cards — first of two to swap days."
    elif ct == 5:
        if any(
            c["face_up"] and len(state["arrivals"].get(_key(d+1, c["card_type"]), [])) >= 2
            for pi, p in enumerate(state["players"]) if pi != pidx
            for d, c in enumerate(p["cards"])
        ):
            pending = "change_arr_other"
            msg = f"Card 5 – {LOCATION_NAMES[5]}: Click an opponent's face-up card to change its arrival order."
    elif ct == 6:
        if any(
            c["face_up"] and len(state["arrivals"].get(_key(d+1, c["card_type"]), [])) >= 2
            for d, c in enumerate(player["cards"])
        ):
            pending = "change_arr_own"
            msg = f"Card 6 – {LOCATION_NAMES[6]}: Click one of your face-up cards to change its arrival order."

    if pending:
        state["pending_action"] = pending
        state["action_ctx"] = {"actor": pidx}
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

    if action == "flip_other_down":
        if tpi == actor:
            err = "Must target an opponent's card."
        else:
            card = _card_at(state["players"][tpi], tday)
            if not card or not card["face_up"]:
                err = "Must target a face-up card."
            else:
                _flip_down(state, tpi, tday)
                success_msg = f"Flipped {state['players'][tpi]['name']}'s {LOCATION_NAMES[card['card_type']]} (Day {tday}) face down!"
                _log(state, f"↳ {state['players'][actor]['name']} used Coffee Shop: flipped {state['players'][tpi]['name']}'s {LOCATION_NAMES[card['card_type']]} (Day {tday}) face down")
                done = True

    elif action == "flip_own_down":
        if tpi != actor:
            err = "Must target your own card."
        else:
            card = _card_at(state["players"][tpi], tday)
            if not card or not card["face_up"]:
                err = "Must target a face-up card."
            else:
                _flip_down(state, tpi, tday)
                success_msg = f"Flipped your {LOCATION_NAMES[card['card_type']]} (Day {tday}) face down!"
                _log(state, f"↳ {state['players'][actor]['name']} used Park: flipped own {LOCATION_NAMES[card['card_type']]} (Day {tday}) face down")
                done = True

    elif action == "swap_other_1":
        if tpi == actor:
            err = "Must target another player's card."
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
        else:
            _swap_days(state, tpi, ctx["first_day"], tday)
            success_msg = f"Swapped {state['players'][tpi]['name']}'s Day {ctx['first_day']} and Day {tday}!"
            _log(state, f"↳ {state['players'][actor]['name']} used Cinema: swapped {state['players'][tpi]['name']}'s Day {ctx['first_day']} ↔ Day {tday}")
            done = True

    elif action == "swap_own_1":
        if tpi != actor:
            err = "Must target your own card."
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
        else:
            _swap_days(state, actor, ctx["first_day"], tday)
            success_msg = f"Swapped your Day {ctx['first_day']} and Day {tday}!"
            _log(state, f"↳ {state['players'][actor]['name']} used Restaurant: swapped own Day {ctx['first_day']} ↔ Day {tday}")
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
    ability_name = ctx.get("ability", "Beach/Museum")
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

if __name__ == "__main__":
    app.run(debug=True, port=5000)
