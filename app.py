from flask import Flask, session, request, jsonify, render_template

app = Flask(__name__)
app.secret_key = "dtbtw-v2-2024"

# ── card definitions ───────────────────────────────────────────────────────────

CARD_INFO = {
    1: {
        "type": "bonus",
        "action": "Switch any two date piles",
        "modifier": "+1 point at end of game",
        "modifier_type": "global_plus",
    },
    2: {
        "type": "bonus",
        "action": "Swap the arrival order of any two cards in a date pile",
        "modifier": "If third wheel in MM+MM+MM: score 0 instead of −2",
        "modifier_type": "tw_protect",
    },
    3: {
        "type": "bonus",
        "action": "Deactivate an opponent's active bonus, or activate an opponent's avoided debuff",
        "modifier": "Peek at one other player's move before choosing yours this date",
        "modifier_type": "peek",
    },
    4: {
        "type": "debuff",
        "action": "Switch any two date piles",
        "modifier": "−1 point at end of game",
        "modifier_type": "global_minus",
    },
    5: {
        "type": "debuff",
        "action": "Swap the arrival order of any two cards in a date pile",
        "modifier": "If third wheel in MM+MM+MM: score −4 instead of −2",
        "modifier_type": "tw_double",
    },
    6: {
        "type": "debuff",
        "action": "Deactivate an opponent's active bonus, or activate an opponent's avoided debuff",
        "modifier": "Must show your move to one player before they choose this date",
        "modifier_type": "show",
    },
}

PLAYER_COLORS = ["#E05555", "#5578E0", "#3DC470"]
PLAYER_DARK  = ["#8B2020", "#203070", "#1A7035"]
PLAYER_LIGHT = ["#FFCCCC", "#CCE0FF", "#C8FFDC"]


# ── state helpers ──────────────────────────────────────────────────────────────

def _new_state():
    return {
        "phase": "setup",
        "players": [],
        "stacks": [],
        "next_stack_id": 0,
        "current_player_idx": 0,
        "turn_count": 0,
        "pending_action": None,
        "action_ctx": {},
        "action_message": None,
        "date_phase_idx": 0,
        "date_submission_order": [],
        "date_submitted_count": 0,
        "date_peek_info": None,
        "date_show_info": None,
        "total_scores": [0, 0, 0],
        "game_over": False,
    }


def _gs():
    if "game" not in session:
        session["game"] = _new_state()
    return session["game"]


def _save(s):
    session["game"] = s
    session.modified = True


def _card_type(n):
    return "bonus" if n <= 3 else "debuff"


def _modifier_initial(card_num, used_action):
    if _card_type(card_num) == "bonus":
        return not used_action   # bonus active iff action NOT used
    else:
        return used_action       # debuff active iff action WAS used


def _get_played_cards(state, pidx):
    return [p["card_num"]
            for s in state["stacks"]
            for p in s["plays"]
            if p["player_idx"] == pidx]


def _get_stack_by_id(state, sid):
    for s in state["stacks"]:
        if s["id"] == sid:
            return s
    return None


def _tw_pos(date_idx):
    """Arrival-list index of the third wheel for a given date (0-indexed)."""
    if date_idx < 2:  return 2   # dates 1-2: 3rd arrival is third wheel
    if date_idx < 4:  return 1   # dates 3-4: 2nd arrival
    return 0                      # dates 5-6: 1st arrival


def _score_date(state, di):
    stack = state["stacks"][di]
    plays = stack["plays"]
    if len(plays) != 3:
        return {}

    twp = _tw_pos(di)
    tw = plays[twp]["player_idx"]
    normals = [plays[i]["player_idx"] for i in range(3) if i != twp]
    n0, n1 = normals[0], normals[1]

    m  = stack["date_moves"]
    tm = m.get(str(tw), "PS")
    m0 = m.get(str(n0),  "PS")
    m1 = m.get(str(n1),  "PS")

    if tm == "PS":
        if   m0 == "PS" and m1 == "PS": base = {tw: 0, n0:  1, n1:  1}
        elif m0 == "MM" and m1 == "PS": base = {tw: 0, n0: -1, n1:  1}
        elif m0 == "PS" and m1 == "MM": base = {tw: 0, n0:  1, n1: -1}
        else:                           base = {tw: 0, n0:  2, n1:  2}
    else:                                # tw == "MM"
        if   m0 == "PS" and m1 == "PS": base = {tw: -2, n0: 1, n1: 1}
        elif m0 == "MM" and m1 == "PS": base = {tw:  2, n0: 2, n1: 0}
        elif m0 == "PS" and m1 == "MM": base = {tw:  2, n0: 0, n1: 2}
        else:                            # MM, MM, MM — check tw modifiers
            tw_score = -2
            for play in plays:
                if play["player_idx"] == tw and play["modifier_active"]:
                    if   play["card_num"] == 2: tw_score = 0
                    elif play["card_num"] == 5: tw_score = -4
            base = {tw: tw_score, n0: 2, n1: 2}

    return base


def _calc_final_scores(state):
    scores = list(state["total_scores"])
    for stack in state["stacks"]:
        for play in stack["plays"]:
            if play["modifier_active"]:
                pi = play["player_idx"]
                if   play["card_num"] == 1: scores[pi] += 1
                elif play["card_num"] == 4: scores[pi] -= 1
    return scores


def _all_played(state):
    return (sum(len(s["plays"]) for s in state["stacks"]) == 18
            and len(state["stacks"]) == 6)


def _setup_date(state, di):
    if di >= len(state["stacks"]):
        state["phase"] = "end"
        state["game_over"] = True
        return

    stack = state["stacks"][di]
    plays = stack["plays"]
    twp   = _tw_pos(di)
    tw    = plays[twp]["player_idx"]

    peek_player = None
    show_player = None
    for play in plays:
        if play["modifier_active"]:
            if   play["card_num"] == 3: peek_player = play["player_idx"]
            elif play["card_num"] == 6: show_player = play["player_idx"]

    order = [plays[0]["player_idx"], plays[1]["player_idx"], plays[2]["player_idx"]]
    if show_player is not None and show_player in order:
        order.remove(show_player)
        order.insert(0, show_player)
    if peek_player is not None and peek_player in order:
        order.remove(peek_player)
        order.append(peek_player)

    state["date_phase_idx"]       = di
    state["date_submission_order"] = order
    state["date_submitted_count"]  = 0
    stack["date_moves"]            = {}
    stack["date_scores"]           = {}
    state["date_peek_info"] = {"player": peek_player, "peek_target": None} if peek_player else None
    state["date_show_info"] = {"player": show_player, "reveal_to":   None} if show_player else None


def _advance_card_turn(state):
    if _all_played(state):
        state["phase"] = "date_phase"
        _setup_date(state, 0)
    else:
        n = len(state["players"])
        state["current_player_idx"] = (state["current_player_idx"] + 1) % n
    state["pending_action"] = None
    state["action_ctx"]     = {}


def _enrich(state):
    s = dict(state)
    s["card_info"]      = CARD_INFO
    s["player_colors"]  = PLAYER_COLORS
    s["player_dark"]    = PLAYER_DARK
    s["player_light"]   = PLAYER_LIGHT
    if state["phase"] == "end":
        s["final_scores"] = _calc_final_scores(state)
    if state["phase"] == "date_phase":
        di = state["date_phase_idx"]
        if di < len(state["stacks"]):
            plays = state["stacks"][di]["plays"]
            if len(plays) == 3:
                twp = _tw_pos(di)
                s["current_date_tw"]      = plays[twp]["player_idx"]
                s["current_date_normals"] = [plays[i]["player_idx"] for i in range(3) if i != twp]
    return s


# ── routes ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    return jsonify(_enrich(_gs()))


@app.route("/api/setup", methods=["POST"])
def api_setup():
    data  = request.json or {}
    state = _new_state()
    names = data.get("names", [])
    for i in range(3):
        raw  = names[i] if i < len(names) else ""
        name = str(raw).strip() or f"Player {i + 1}"
        state["players"].append({"name": name, "cards_played_to": []})
    state["phase"] = "card_playing"
    _save(state)
    return jsonify(_enrich(state))


@app.route("/api/play_card", methods=["POST"])
def api_play_card():
    data  = request.json or {}
    state = _gs()
    if state["phase"] != "card_playing" or state["pending_action"]:
        return jsonify({"error": "Cannot play a card right now"}), 400

    pidx     = state["current_player_idx"]
    player   = state["players"][pidx]
    card_num = int(data.get("card_num", 0))
    target   = data.get("stack_target")  # stack id (int) | "new_left" | "new_right"
    use_act  = bool(data.get("use_action", False))

    # --- validate card ---
    played = _get_played_cards(state, pidx)
    if card_num < 1 or card_num > 6 or card_num in played:
        return jsonify({"error": "Invalid card selection"}), 400

    # --- resolve stack ---
    if target == "new_left":
        if len(state["stacks"]) >= 6:
            return jsonify({"error": "Maximum 6 stacks already exist"}), 400
        sid = state["next_stack_id"]
        state["next_stack_id"] += 1
        state["stacks"].insert(0, {
            "id": sid, "plays": [],
            "date_resolved": False, "date_moves": {}, "date_scores": {}
        })
        actual_sid = sid
    elif target == "new_right":
        if len(state["stacks"]) >= 6:
            return jsonify({"error": "Maximum 6 stacks already exist"}), 400
        sid = state["next_stack_id"]
        state["next_stack_id"] += 1
        state["stacks"].append({
            "id": sid, "plays": [],
            "date_resolved": False, "date_moves": {}, "date_scores": {}
        })
        actual_sid = sid
    else:
        actual_sid = int(target)
        if not any(s["id"] == actual_sid for s in state["stacks"]):
            return jsonify({"error": "Stack not found"}), 400

    if actual_sid in player["cards_played_to"]:
        return jsonify({"error": "Already played to this stack"}), 400

    stack = _get_stack_by_id(state, actual_sid)
    if stack is None:
        return jsonify({"error": "Stack not found"}), 400

    # --- add play ---
    play = {
        "player_idx":      pidx,
        "card_num":        card_num,
        "used_action":     use_act,
        "modifier_active": _modifier_initial(card_num, use_act),
    }
    stack["plays"].append(play)
    player["cards_played_to"].append(actual_sid)

    # --- setup pending action ---
    pending = None
    msg     = None
    ctx     = {"actor": pidx}

    if use_act:
        if card_num in (1, 4):
            if len(state["stacks"]) >= 2:
                pending = "switch_piles"
                msg     = (f"Card {card_num} — Switch Piles: "
                           "Select any two date piles to swap their positions.")
        elif card_num in (2, 5):
            has_valid = any(len(s["plays"]) >= 2 for s in state["stacks"])
            if has_valid:
                pending = "swap_order"
                msg     = (f"Card {card_num} — Swap Order: "
                           "Select a pile with 2+ cards, then pick two cards to swap.")
        elif card_num in (3, 6):
            has_target = any(
                p["player_idx"] != pidx and not p["used_action"]
                for s in state["stacks"] for p in s["plays"]
            )
            if has_target:
                pending = "deact_act"
                msg     = (f"Card {card_num} — Deactivate/Activate: "
                           "Select an opponent's card that was played WITHOUT action.")

    if pending:
        state["pending_action"] = pending
        state["action_ctx"]     = ctx
        state["action_message"] = msg
    else:
        state["action_message"] = None
        _advance_card_turn(state)

    _save(state)
    return jsonify(_enrich(state))


@app.route("/api/resolve_action", methods=["POST"])
def api_resolve_action():
    data   = request.json or {}
    state  = _gs()
    action = state["pending_action"]
    if not action:
        return jsonify({"error": "No pending action"}), 400

    actor = state["action_ctx"].get("actor", 0)
    err   = None
    msg   = None

    if action == "switch_piles":
        id1 = int(data.get("stack1_id", -1))
        id2 = int(data.get("stack2_id", -1))
        i1  = next((i for i, s in enumerate(state["stacks"]) if s["id"] == id1), -1)
        i2  = next((i for i, s in enumerate(state["stacks"]) if s["id"] == id2), -1)
        if i1 == -1 or i2 == -1:
            err = "Stack not found."
        elif i1 == i2:
            err = "Must select two different piles."
        else:
            state["stacks"][i1], state["stacks"][i2] = state["stacks"][i2], state["stacks"][i1]
            msg = f"Switched pile positions {i1 + 1} and {i2 + 1}!"

    elif action == "swap_order":
        si  = int(data.get("stack_idx",  -1))
        pi1 = int(data.get("play_idx1", -1))
        pi2 = int(data.get("play_idx2", -1))
        if si < 0 or si >= len(state["stacks"]):
            err = "Invalid pile."
        else:
            plays = state["stacks"][si]["plays"]
            if not (0 <= pi1 < len(plays) and 0 <= pi2 < len(plays) and pi1 != pi2):
                err = "Invalid card indices."
            else:
                plays[pi1], plays[pi2] = plays[pi2], plays[pi1]
                msg = f"Swapped arrival order in pile {si + 1}!"

    elif action == "deact_act":
        si = int(data.get("stack_idx", -1))
        pi = int(data.get("play_idx",  -1))
        if si < 0 or si >= len(state["stacks"]):
            err = "Invalid pile."
        else:
            plays = state["stacks"][si]["plays"]
            if pi < 0 or pi >= len(plays):
                err = "Invalid card."
            else:
                tp = plays[pi]
                if tp["player_idx"] == actor:
                    err = "Cannot target your own card."
                elif tp["used_action"]:
                    err = "Target must be a card played WITHOUT action."
                else:
                    tp["modifier_active"] = not tp["modifier_active"]
                    tname = state["players"][tp["player_idx"]]["name"]
                    ct    = _card_type(tp["card_num"])
                    if ct == "bonus":
                        msg = f"Deactivated {tname}'s Card {tp['card_num']} bonus!"
                    else:
                        msg = f"Activated {tname}'s Card {tp['card_num']} debuff!"

    if err:
        return jsonify({"error": err, **_enrich(state)})

    state["action_message"] = msg
    _advance_card_turn(state)
    _save(state)
    return jsonify(_enrich(state))


@app.route("/api/cancel_action", methods=["POST"])
def api_cancel_action():
    state = _gs()
    state["action_message"] = "Action skipped."
    _advance_card_turn(state)
    _save(state)
    return jsonify(_enrich(state))


@app.route("/api/set_show_target", methods=["POST"])
def api_set_show_target():
    data  = request.json or {}
    state = _gs()
    if state["phase"] != "date_phase" or not state["date_show_info"]:
        return jsonify({"error": "No show modifier active"}), 400
    state["date_show_info"]["reveal_to"] = int(data.get("target_player", -1))
    _save(state)
    return jsonify(_enrich(state))


@app.route("/api/set_peek_target", methods=["POST"])
def api_set_peek_target():
    data  = request.json or {}
    state = _gs()
    if state["phase"] != "date_phase" or not state["date_peek_info"]:
        return jsonify({"error": "No peek modifier active"}), 400
    state["date_peek_info"]["peek_target"] = int(data.get("target_player", -1))
    _save(state)
    return jsonify(_enrich(state))


@app.route("/api/submit_move", methods=["POST"])
def api_submit_move():
    data  = request.json or {}
    state = _gs()
    if state["phase"] != "date_phase":
        return jsonify({"error": "Not in date phase"}), 400

    di    = state["date_phase_idx"]
    stack = state["stacks"][di]
    order = state["date_submission_order"]
    count = state["date_submitted_count"]

    if count >= len(order):
        return jsonify({"error": "All moves already submitted"}), 400

    expected = order[count]
    pidx     = int(data.get("player_idx", -1))
    if pidx != expected:
        return jsonify({
            "error": f"It is {state['players'][expected]['name']}'s turn to submit"
        }), 400

    move = str(data.get("move", "")).upper()
    if move not in ("MM", "PS"):
        return jsonify({"error": "Move must be MM or PS"}), 400

    stack["date_moves"][str(pidx)] = move
    state["date_submitted_count"] += 1

    if state["date_submitted_count"] >= 3:
        scores = _score_date(state, di)
        stack["date_scores"]   = {str(k): v for k, v in scores.items()}
        stack["date_resolved"] = True
        for pi, sc in scores.items():
            state["total_scores"][pi] += sc

        next_di = di + 1
        if next_di >= 6:
            state["phase"]     = "end"
            state["game_over"] = True
        else:
            _setup_date(state, next_di)

    _save(state)
    return jsonify(_enrich(state))


@app.route("/api/reset", methods=["POST"])
def api_reset():
    session.pop("game", None)
    return jsonify(_enrich(_new_state()))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
