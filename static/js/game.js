/* ── per-card scoring text (Rules 2, 3, 4) ──────────────────────────────── */
const CARD_SCORING = {
  1: "2♥ 1st+1 · 2nd+2<br>3♥ 3rd−1",
  2: "2♥ 1st+1 · 2nd+2<br>3♥ 3rd−1",
  3: "2♥ 1st+2 · 2nd+1<br>3♥ 3rd−1",
  4: "2♥ 1st+4 · 2nd+2<br>3♥ 3rd−2 🔥",
  5: "2♥ 1st+3 · 2nd+3<br>3♥ 3rd−2 · solo−1",
  6: "2♥ 1st+1 · 2nd+1<br>3♥ no penalty",
};

/* ── api ─────────────────────────────────────────────────────────────────── */
async function apiGet(url) {
  const r = await fetch(url);
  return r.json();
}
async function apiPost(url, data = {}) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return r.json();
}

function gameUrl(path) {
  return `/api/game/${GAME_ID}/${TOKEN}/${path}`;
}

/* ── game state ──────────────────────────────────────────────────────────── */
let G = null;
let pollTimer = null;
let lastRenderKey = null;
let msgTimer = null;

function renderKey(s) {
  return `${s.phase}|${s.turn_count}|${s.pending_action}|${(s.players||[]).map(p=>p.arranged).join(",")}|${(s.move_log||[]).length}`;
}

/* ── room state (persisted across refreshes) ─────────────────────────────── */
let ROOM_CODE   = localStorage.getItem("dtbtw_room_code");
let LOBBY_TOKEN = localStorage.getItem("dtbtw_lobby_token");
let ROOM        = null;
let roomPollTimer = null;
let roomVersion   = -1;

function saveRoom(code, token) {
  ROOM_CODE = code; LOBBY_TOKEN = token;
  localStorage.setItem("dtbtw_room_code", code);
  localStorage.setItem("dtbtw_lobby_token", token);
}
function clearRoom() {
  ROOM_CODE = null; LOBBY_TOKEN = null;
  localStorage.removeItem("dtbtw_room_code");
  localStorage.removeItem("dtbtw_lobby_token");
}

/* ── entry ───────────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", async () => {
  if (GAME_ID && TOKEN) {
    // Landed on /game/<id>/<token> — normal game flow
    G = await apiGet(gameUrl("state"));
    render(G);
    startPolling();
  } else if (ROOM_CODE && LOBBY_TOKEN) {
    // Reconnect to a room in progress
    try {
      const room = await apiGet(`/api/rooms/${ROOM_CODE}?t=${LOBBY_TOKEN}`);
      if (room.error) { clearRoom(); renderRoomLobby(); }
      else if (room.my_game_url) { window.location.href = room.my_game_url; }
      else { ROOM = room; roomVersion = room.version; renderWaitingRoom(room); startRoomPolling(); }
    } catch (_) { clearRoom(); renderRoomLobby(); }
  } else {
    renderRoomLobby();
  }
});

/* ── polling ─────────────────────────────────────────────────────────────── */
function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(async () => {
    if (!GAME_ID || !TOKEN) return;
    const s = await apiGet(gameUrl("state"));
    const key = renderKey(s);
    if (key !== lastRenderKey) {
      G = s;
      render(G);
    }
  }, 2000);
}
function stopPolling() {
  clearInterval(pollTimer);
  pollTimer = null;
}

/* ── room polling ────────────────────────────────────────────────────────── */
function startRoomPolling() {
  if (roomPollTimer) return;
  roomPollTimer = setInterval(async () => {
    if (!ROOM_CODE || !LOBBY_TOKEN) return;
    try {
      const room = await apiGet(`/api/rooms/${ROOM_CODE}?t=${LOBBY_TOKEN}`);
      if (room.error) { stopRoomPolling(); clearRoom(); renderRoomLobby(); return; }
      if (room.my_game_url) { stopRoomPolling(); window.location.href = room.my_game_url; return; }
      if (room.version !== roomVersion) {
        ROOM = room; roomVersion = room.version; renderWaitingRoom(room);
      }
    } catch (_) { /* network hiccup — keep polling */ }
  }, 2000);
}
function stopRoomPolling() { clearInterval(roomPollTimer); roomPollTimer = null; }

/* ══ ROOM LOBBY ═════════════════════════════════════════════════════════════ */
function renderRoomLobby() {
  stopRoomPolling();
  document.getElementById("app").innerHTML = `
<div class="screen lobby-screen">
  <h1 class="title">Don't Be the Third Wheel!</h1>
  <p class="subtitle">Play with friends online — create a room or join one with a 3-digit code</p>

  <div class="lobby-cards">
    <div class="lobby-card">
      <h2 class="lobby-card-title">Create a Room</h2>
      <p class="lobby-card-desc">Generate a code and share it with your friends.</p>
      <div class="form-group">
        <label>Your name</label>
        <input class="player-name-input" id="create-name" value="Player 1" />
      </div>
      <button id="btn-create" class="btn btn-primary" style="width:100%">Create Room →</button>
    </div>

    <div class="lobby-divider"><span>or</span></div>

    <div class="lobby-card">
      <h2 class="lobby-card-title">Join a Room</h2>
      <p class="lobby-card-desc">Enter the 3-digit code from the room host.</p>
      <div class="form-group">
        <label>Room code</label>
        <input class="room-code-input" id="join-code" placeholder="e.g. 472" maxlength="3" />
      </div>
      <div class="form-group">
        <label>Your name</label>
        <input class="player-name-input" id="join-name" value="Player 2" />
      </div>
      <button id="btn-join" class="btn btn-primary" style="width:100%">Join Room →</button>
    </div>
  </div>

  <div id="lobby-err" class="lobby-err hidden"></div>

  <div class="rules-grid">
    <div class="rules-box">
      <h3>Card Abilities</h3>
      ${Object.entries(CARD_ABILITIES).map(([ct, ab]) => `
        <div class="rule-row">
          <span class="card-badge ct-${ct}">${ct}</span>
          <span class="loc-name">${LOCATION_NAMES[ct]}</span>: ${ab}
        </div>`).join("")}
    </div>
    <div class="rules-box">
      <h3>Scoring</h3>
      ${Object.entries(CARD_SCORING).map(([ct, sc]) => `
        <div class="rule-row">
          <span class="card-badge ct-${ct}">${ct}</span>
          <span class="loc-name">${LOCATION_NAMES[ct]}</span>: ${sc.replace(/<br>/g, " / ")}
        </div>`).join("")}
      <div class="rule-row" style="margin-top:6px;color:#FFCCAA">Alone at Beach → −1 pt</div>
    </div>
  </div>
</div>`;

  document.getElementById("btn-create").addEventListener("click", async () => {
    const name = document.getElementById("create-name").value.trim() || "Player 1";
    const res = await apiPost("/api/rooms/create", { name });
    if (res.error) { lobbyErr(res.error); return; }
    saveRoom(res.room_code, res.lobby_token);
    ROOM = res; roomVersion = res.version;
    renderWaitingRoom(res); startRoomPolling();
  });

  document.getElementById("btn-join").addEventListener("click", async () => {
    const code = document.getElementById("join-code").value.trim();
    const name = document.getElementById("join-name").value.trim() || "Player";
    if (!/^\d{3}$/.test(code)) { lobbyErr("Please enter a valid 3-digit room code."); return; }
    const res = await apiPost("/api/rooms/join", { code, name });
    if (res.error) { lobbyErr(res.error); return; }
    saveRoom(res.room_code, res.lobby_token);
    ROOM = res; roomVersion = res.version;
    renderWaitingRoom(res); startRoomPolling();
  });

  document.getElementById("join-code").addEventListener("keydown", e => {
    if (e.key === "Enter") document.getElementById("btn-join").click();
  });
}

function lobbyErr(msg) {
  const el = document.getElementById("lobby-err");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 4000);
}

/* ══ WAITING ROOM ═══════════════════════════════════════════════════════════ */
function renderWaitingRoom(room) {
  const isHost  = room.is_host;
  const players = room.players;
  const canStart = isHost && players.length >= 2;
  const canAddAI = isHost && players.length < 3;

  const aiBadge = p => {
    if (!p.is_ai) return "";
    const label = {random:"🎲 Random", basic:"🤖 Strategic", mcts:"🧠 MCTS"}[p.ai_type] || "🎲 Random";
    const extra = p.ai_type === "mcts" ? ` (${p.ai_rollouts})` : "";
    return `<span class="ai-badge">${label}${extra}</span>`;
  };

  document.getElementById("app").innerHTML = `
<div class="screen waiting-room">
  <h1 class="title" style="font-size:1.6rem">Don't Be the Third Wheel!</h1>

  <div class="room-code-banner">
    <span class="room-code-label">Room Code</span>
    <span class="room-code-value" id="room-code-val">${room.room_code}</span>
    <button class="copy-btn" id="copy-code-btn">Copy</button>
  </div>
  <p class="room-code-hint">${isHost
    ? "Share this code with friends so they can join."
    : "Waiting for the host to start the game…"}</p>

  <div class="waiting-players">
    <div class="waiting-section-title">Players <span class="dim">(turn order)</span></div>
    <div id="player-list">
      ${players.map((p, i) => `
        <div class="player-row ${p.is_me ? "is-me" : ""}">
          <span class="player-order">${i + 1}.</span>
          <span class="player-row-name">
            ${p.name}
            ${p.is_me ? '<span class="you-tag">(you)</span>' : ""}
            ${i === 0 ? '<span class="host-tag">★ host</span>' : ""}
          </span>
          ${aiBadge(p)}
          ${isHost ? `<span class="player-controls">
            <button class="icon-btn" onclick="roomMove('${p.player_id}','up')" ${i===0?"disabled":""}>↑</button>
            <button class="icon-btn" onclick="roomMove('${p.player_id}','down')" ${i===players.length-1?"disabled":""}>↓</button>
            ${p.is_me ? "" : `<button class="icon-btn danger" onclick="roomRemove('${p.player_id}')">✕</button>`}
          </span>` : ""}
        </div>`).join("")}
    </div>

    ${canAddAI ? `
    <div class="add-ai-wrap" id="add-ai-wrap">
      <button class="btn btn-outline" id="btn-show-ai">+ Add AI Player</button>
      <div class="add-ai-form hidden" id="add-ai-form">
        <input class="player-name-input" id="ai-name-inp" value="Bot ${players.filter(p=>p.is_ai).length+1}" style="width:110px" />
        <select class="ai-type-select" id="ai-type-sel">
          <option value="random">🎲 Random</option>
          <option value="basic">🤖 Strategic</option>
          <option value="mcts">🧠 MCTS</option>
        </select>
        <span class="mcts-row hidden" id="mcts-row">
          <input type="number" class="rollout-input" id="ai-rollouts-inp" value="50" min="1" max="500" />
          <span class="dim" style="font-size:.8rem">rollouts</span>
        </span>
        <button class="btn btn-primary ai-add-btn" id="btn-add-ai">Add</button>
        <button class="btn btn-cancel ai-add-btn" id="btn-cancel-ai">✕</button>
      </div>
    </div>` : ""}

    <div class="start-section">
      ${isHost ? `
        <button class="btn btn-primary start-btn" id="btn-start" ${canStart?"":"disabled"}>▶ Start Game</button>
        ${players.length < 2 ? '<p class="start-hint">Need at least 2 players.</p>' : ""}
      ` : `<div class="spinner"></div><p class="dim">Waiting for host to start…</p>`}
      <button class="btn btn-cancel" id="btn-leave" style="margin-left:10px;padding:8px 14px;font-size:.85rem">Leave Room</button>
    </div>
  </div>
</div>`;

  document.getElementById("copy-code-btn").addEventListener("click", () => {
    navigator.clipboard.writeText(room.room_code).then(() => {
      const b = document.getElementById("copy-code-btn");
      b.textContent = "Copied!";
      setTimeout(() => b.textContent = "Copy", 2000);
    });
  });

  document.getElementById("btn-leave").addEventListener("click", () => {
    clearRoom(); stopRoomPolling(); renderRoomLobby();
  });

  if (isHost) {
    document.getElementById("btn-start")?.addEventListener("click", async () => {
      const res = await apiPost(`/api/rooms/${room.room_code}/start`, { t: LOBBY_TOKEN });
      if (res.error) { alert(res.error); return; }
      if (res.my_game_url) { stopRoomPolling(); window.location.href = res.my_game_url; }
    });

    if (canAddAI) {
      document.getElementById("btn-show-ai").addEventListener("click", () => {
        document.getElementById("add-ai-form").classList.remove("hidden");
        document.getElementById("btn-show-ai").style.display = "none";
      });
      document.getElementById("btn-cancel-ai").addEventListener("click", () => {
        document.getElementById("add-ai-form").classList.add("hidden");
        document.getElementById("btn-show-ai").style.display = "";
      });
      document.getElementById("ai-type-sel").addEventListener("change", () => {
        document.getElementById("mcts-row").classList.toggle(
          "hidden", document.getElementById("ai-type-sel").value !== "mcts");
      });
      document.getElementById("btn-add-ai").addEventListener("click", async () => {
        const name = document.getElementById("ai-name-inp").value.trim()
                     || `Bot ${players.filter(p=>p.is_ai).length+1}`;
        const ai_type = document.getElementById("ai-type-sel").value;
        const ai_rollouts = ai_type === "mcts"
          ? Math.max(1, Math.min(500, parseInt(document.getElementById("ai-rollouts-inp").value)||50))
          : 50;
        const res = await apiPost(`/api/rooms/${room.room_code}/add_ai`,
          { t: LOBBY_TOKEN, name, ai_type, ai_rollouts });
        if (res.error) { alert(res.error); return; }
        ROOM = res; roomVersion = res.version; renderWaitingRoom(res); startRoomPolling();
      });
    }
  }
}

async function roomMove(playerId, direction) {
  const res = await apiPost(`/api/rooms/${ROOM_CODE}/move_player`,
    { t: LOBBY_TOKEN, player_id: playerId, direction });
  if (res.error) { alert(res.error); return; }
  ROOM = res; roomVersion = res.version; renderWaitingRoom(res);
}
async function roomRemove(playerId) {
  if (!confirm("Remove this player?")) return;
  const res = await apiPost(`/api/rooms/${ROOM_CODE}/remove_player`,
    { t: LOBBY_TOKEN, player_id: playerId });
  if (res.error) { alert(res.error); return; }
  ROOM = res; roomVersion = res.version; renderWaitingRoom(res);
}

/* ── render dispatch ─────────────────────────────────────────────────────── */
function render(state) {
  G = state;
  lastRenderKey = renderKey(state);
  const app = document.getElementById("app");

  if (!GAME_ID) {
    renderRoomLobby(); return;
  }
  if (state.phase === "arrangement") {
    const me = state.players[MY_IDX];
    if (!me.arranged) {
      app.innerHTML = arrangeHTML(state);
      bindArrange(state);
    } else {
      app.innerHTML = waitingHTML(state);
    }
  } else if (state.phase === "game") {
    app.innerHTML = gameHTML(state);
    bindGame(state);
  } else if (state.phase === "end") {
    stopPolling();
    app.innerHTML = endHTML(state);
    bindEnd();
  }
}

function showMsg(msg, cls = "") {
  const el = document.getElementById("action-msg");
  if (!el) return;
  if (msgTimer) clearTimeout(msgTimer);
  el.textContent = msg;
  el.className = "action-msg " + cls;
  if (cls === "success") msgTimer = setTimeout(() => { el.textContent = ""; el.className = "action-msg"; }, 3000);
}

/* ══ ARRANGEMENT ════════════════════════════════════════════════════════════ */
function arrangeHTML(state) {
  const me = state.players[MY_IDX];
  return `
<div class="arrange-screen">
  <h1 class="title" style="font-size:1.7rem">Schedule Your Dates!</h1>
  <p class="subtitle">
    <strong style="color:#80FFCC">${me.name}</strong> —
    assign each location to a Day. Only you can see this screen.
  </p>

  <p style="text-align:center;font-weight:700;color:#CC99FF;margin-bottom:6px">Location Cards</p>
  <div class="loc-cards" id="loc-cards">
    ${[1,2,3,4,5,6].map(ct => `
      <button class="loc-btn" id="loc-${ct}" style="background:${LOC_COLORS[ct]};border-color:${LOC_COLORS[ct]}">
        <span class="lnum">${ct}</span>
        <span class="lname">${LOCATION_NAMES[ct]}</span>
        <span class="labil">${CARD_ABILITIES[ct]}</span>
      </button>`).join("")}
  </div>

  <p style="text-align:center;font-weight:700;color:#CC99FF;margin-bottom:6px">Day Slots</p>
  <div class="day-slots" id="day-slots">
    ${[1,2,3,4,5,6].map(d => `
      <div class="day-slot" id="slot-${d}">
        <span class="dlabel">Day ${d}</span>
        <span class="dct"></span>
        <span class="dname" style="color:#8870aa">(empty)</span>
      </div>`).join("")}
  </div>

  <p class="arrange-status" id="arr-status">Select a location card to begin.</p>
  <button id="arr-confirm" class="btn btn-primary arrange-confirm" disabled>Lock In My Schedule →</button>
</div>`;
}

function bindArrange(state) {
  let selCt = 0;
  const assigned = {};
  const dayTaken = {};

  function setStatus(msg) { document.getElementById("arr-status").textContent = msg; }

  document.querySelectorAll(".loc-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const ct = +btn.id.split("-")[1];
      if (assigned[ct]) { setStatus(`Card ${ct} already placed on Day ${assigned[ct]}!`); return; }
      selCt = ct;
      document.querySelectorAll(".loc-btn").forEach(b => b.classList.remove("selected"));
      btn.classList.add("selected");
      setStatus(`Selected: ${ct} – ${LOCATION_NAMES[ct]}. Now click a Day slot.`);
    });
  });

  document.querySelectorAll(".day-slot").forEach(slot => {
    slot.addEventListener("click", () => {
      const day = +slot.id.split("-")[1];
      if (!selCt) { setStatus("Select a location card first!"); return; }
      if (assigned[selCt]) { setStatus(`Card ${selCt} already placed!`); return; }
      if (dayTaken[day]) { setStatus(`Day ${day} is taken! Choose another.`); return; }

      assigned[selCt] = day;
      dayTaken[day] = selCt;
      slot.classList.add("filled");
      slot.style.background = LOC_COLORS[selCt];
      slot.querySelector(".dct").textContent = selCt;
      slot.querySelector(".dname").textContent = LOCATION_NAMES[selCt];
      slot.querySelector(".dname").style.color = "";
      document.getElementById(`loc-${selCt}`).disabled = true;
      document.getElementById(`loc-${selCt}`).classList.remove("selected");
      selCt = 0;
      const rem = 6 - Object.keys(assigned).length;
      if (rem === 0) {
        setStatus("All cards placed! Click Lock In to continue.");
        document.getElementById("arr-confirm").disabled = false;
      } else {
        setStatus(`${rem} card(s) still to place.`);
      }
    });
  });

  document.getElementById("arr-confirm").addEventListener("click", async () => {
    G = await apiPost(gameUrl("arrange"), { arrangement: assigned });
    render(G);
  });
}

function waitingHTML(state) {
  const waiting = state.players.filter(p => !p.arranged).map(p => p.name);
  return `
<div class="screen center">
  <h1 class="title" style="font-size:1.6rem">Schedule Locked In!</h1>
  <div class="waiting-box">
    <h3>Waiting for other players…</h3>
    <div class="spinner"></div>
    ${waiting.map(n => `<p>${n} is still arranging</p>`).join("")}
    <p style="margin-top:12px;font-size:.82rem;color:#8870aa">
      This page will advance automatically when everyone is ready.
    </p>
  </div>
</div>`;
}

/* ══ GAME SCREEN ════════════════════════════════════════════════════════════ */
function gameHTML(state) {
  const cur = state.current_player_idx;
  const isMyTurn = cur === MY_IDX;
  const scores = state.scores || {};
  const turnPlayerName = state.players[cur].name;

  return `
<div class="game-wrap">
  <div class="topbar">
    <span class="topbar-title">Don't Be the Third Wheel!</span>
    <span class="topbar-turn">
      Turn ${state.turn_count + 1} —
      ${isMyTurn ? "<strong style='color:#FFD700'>Your turn!</strong>" : `<strong>${turnPlayerName}</strong>'s turn`}
    </span>
    <div class="topbar-btns">
      <button class="btn btn-green" id="btn-scores">Scores</button>
      <button class="btn btn-red"   id="btn-end">End Game</button>
    </div>
  </div>

  <div class="action-strip">
    <span class="action-msg ${isMyTurn && state.pending_action ? "" : isMyTurn ? "" : "waiting"}" id="action-msg">
      ${state.pending_action && isMyTurn
        ? state.action_message || ""
        : isMyTurn
          ? "Your turn — click one of your face-down cards to flip it."
          : `Waiting for ${turnPlayerName} to play…`}
    </span>
    ${isMyTurn && state.pending_action
      ? `<button class="btn btn-cancel" id="btn-cancel">✕ Cancel</button>`
      : ""}
  </div>

  <div class="board-container">
    <div class="board">
      <div class="board-corner"></div>
      ${[1,2,3,4,5,6].map(d => `<div class="board-day-header">Day ${d}</div>`).join("")}
      ${state.players.map((player, pi) => boardRowHTML(state, pi, player)).join("")}
    </div>
  </div>

  <div class="score-strip">
    ${state.players.map(p =>
      `<span class="score-item"><strong>${p.name}</strong>: ${
        scores[p.name] !== undefined ? (scores[p.name] >= 0 ? "+" : "") + scores[p.name] : 0
      } pts</span>`
    ).join("")}
  </div>
  <div class="move-log-panel">
    <div class="move-log-title">Move Log</div>
    <div class="move-log-list">
      ${(state.move_log || []).length === 0
        ? '<div class="log-entry log-empty">No moves yet.</div>'
        : (state.move_log || []).map(e =>
            `<div class="log-entry${e.startsWith("↳") ? " log-ability" : ""}">${e}</div>`
          ).join("")}
    </div>
  </div>
</div>`;
}

function boardRowHTML(state, pi, player) {
  const isMe = pi === MY_IDX;
  const isActive = pi === state.current_player_idx;
  const isAI = (state.ai_players || []).includes(pi);
  const labelCls = [isMe ? "is-me" : "", isActive ? "is-active" : ""].filter(Boolean).join(" ");
  let aiTag = "";
  if (isAI) {
    const diffs = state.ai_difficulties || {};
    const diff = diffs[String(pi)] || state.ai_difficulty || "random";
    if (diff.startsWith("mcts:")) {
      const n = diff.split(":")[1];
      aiTag = ` <span class="ai-badge mcts-badge">🧠 MCTS-${n}</span>`;
    } else if (diff === "basic") {
      aiTag = ` <span class="ai-badge">🤖 Strategic</span>`;
    } else {
      aiTag = ` <span class="ai-badge">🎲 Random</span>`;
    }
  }
  return `
    <div class="board-player-label ${labelCls}">
      ${isActive ? "▶ " : ""}${player.name}${isMe ? " (you)" : ""}${aiTag}
    </div>
    ${player.cards.map((card, di) => cardHTML(state, pi, di + 1, card)).join("")}`;
}

function cardHTML(state, pi, day, card) {
  const isMe = pi === MY_IDX;
  const isMyTurn = state.current_player_idx === MY_IDX;
  const action = state.pending_action;
  const ctx = state.action_ctx || {};
  const isActive = pi === state.current_player_idx;
  const arrivals = state.arrivals || {};

  // Decide visual state class
  let stateCls = "";
  if (!action) {
    if (isActive && !card.face_up && isMyTurn) stateCls = "flippable";
  } else if (isMyTurn) {
    const isOther = !isMe;
    const isOwn   = isMe;
    let valid = false;

    if (action === "flip_other_down")  valid = isOther && card.face_up;
    if (action === "flip_own_down")    valid = isOwn && card.face_up;
    if (action === "swap_other_1")     valid = isOther;
    if (action === "swap_other_2") {
      if (pi === ctx.first_pi && day === ctx.first_day) stateCls = "selected-first";
      else valid = pi === ctx.first_pi && day !== ctx.first_day;
    }
    if (action === "swap_own_1")  valid = isOwn;
    if (action === "swap_own_2") {
      if (isOwn && day === ctx.first_day) stateCls = "selected-first";
      else valid = isOwn && day !== ctx.first_day;
    }
    if (action === "change_arr_other") {
      const k = `${day},${card.card_type}`;
      valid = isOther && card.face_up && (arrivals[k] || []).length >= 2;
    }
    if (action === "change_arr_own") {
      const k = `${day},${card.card_type}`;
      valid = isOwn && card.face_up && (arrivals[k] || []).length >= 2;
    }
    if (action === "set_arrival") valid = false;

    if (!stateCls) stateCls = valid ? "target-valid" : "dimmed";
  }

  // Opponent face-down: mystery card
  if (!card.face_up && !isMe) {
    return `
<button class="card face-down other ${stateCls}"
        data-pi="${pi}" data-day="${day}" ${stateCls === "dimmed" ? "disabled" : ""}>
  <span class="mystery-symbol">?</span>
  <span class="mystery-label">face down</span>
</button>`;
  }

  // Own face-down: show full card info, styled differently
  if (!card.face_up && isMe) {
    const ct = card.card_type;
    return `
<button class="card face-down own ct-${ct} ${stateCls}"
        data-pi="${pi}" data-day="${day}">
  <span class="card-face-down-badge">face down</span>
  <div class="card-header">
    <span class="card-num">${ct}</span>
    <span class="card-name">${LOCATION_NAMES[ct]}</span>
  </div>
  <hr class="card-divider"/>
  <div class="card-ability">${CARD_ABILITIES[ct]}</div>
  <div class="card-scoring">${CARD_SCORING[ct] || "2♥ 1st+1 · 2nd+2<br>3♥ 3rd−1"}</div>
</button>`;
  }

  // Face-up card (anyone's)
  const ct = card.card_type;
  const arrLabel = { 1: "▲ 1st arrival", 2: "■ 2nd arrival", 3: "▼ 3rd arrival" };
  return `
<button class="card face-up ct-${ct} ${stateCls}"
        data-pi="${pi}" data-day="${day}" ${stateCls === "dimmed" ? "disabled" : ""}>
  <div class="card-header">
    <span class="card-num">${ct}</span>
    <span class="card-name">${LOCATION_NAMES[ct]}</span>
  </div>
  ${card.arrival ? `<div class="card-arrival">${arrLabel[card.arrival] || `#${card.arrival}`}</div>` : ""}
  <hr class="card-divider"/>
  <div class="card-ability">${CARD_ABILITIES[ct]}</div>
  <div class="card-scoring">${CARD_SCORING[ct] || "2♥ 1st+1 · 2nd+2<br>3♥ 3rd−1"}</div>
</button>`;
}

function bindGame(state) {
  document.querySelectorAll(".card").forEach(btn => {
    if (!btn.disabled) {
      btn.addEventListener("click", () => handleCardClick(+btn.dataset.pi, +btn.dataset.day));
    }
  });

  document.getElementById("btn-cancel")?.addEventListener("click", async () => {
    G = await apiPost(gameUrl("cancel"));
    render(G);
  });
  document.getElementById("btn-scores").addEventListener("click", () => showScoresModal(G));
  document.getElementById("btn-end").addEventListener("click", async () => {
    if (confirm("End the game now and see final scores?")) {
      G = await apiPost(gameUrl("end_game"));
      render(G);
    }
  });
}

async function handleCardClick(pi, day) {
  if (MY_IDX !== G.current_player_idx && !G.pending_action) {
    return; // not our turn, ignore
  }
  if (G.pending_action) {
    const resp = await apiPost(gameUrl("action"), { player_idx: pi, day });
    const result = resp.action_result || {};
    if (result.error) { showMsg(result.error, "error"); return; }
    if (result.needs_position && result.arrival_info) {
      G = resp; render(G);
      showArrivalModal(result.arrival_info);
      return;
    }
    G = resp; render(G);
    if (result.message) showMsg(result.message, "success");
  } else {
    if (pi !== MY_IDX) return;
    const resp = await apiPost(gameUrl("flip"), { day });
    G = resp; render(G);
    if (G.action_message) showMsg(G.action_message);
  }
}

/* ── arrival picker modal ────────────────────────────────────────────────── */
function showArrivalModal(info) {
  document.getElementById("modal-title").textContent =
    `${info.player_name}'s ${info.location} on Day ${info.day}`;
  document.getElementById("modal-sub").textContent =
    `Current arrival: #${info.current} of ${info.num}. Select new position:`;

  const labels = { 1: "1st  (above the line)", 2: "2nd  (in line)", 3: "3rd  (below the line)" };
  const opts = document.getElementById("modal-options");
  opts.innerHTML = "";
  for (let i = 1; i <= info.num; i++) {
    const lbl = document.createElement("label");
    lbl.className = "modal-radio";
    lbl.innerHTML = `<input type="radio" name="arrival" value="${i}" ${i === info.current ? "checked" : ""}> ${labels[i] || `#${i}`}`;
    opts.appendChild(lbl);
  }

  document.getElementById("modal-overlay").classList.remove("hidden");
  document.getElementById("modal-confirm").style.display = "";
  document.getElementById("modal-cancel").textContent = "Cancel";

  document.getElementById("modal-confirm").onclick = async () => {
    const sel = document.querySelector('input[name="arrival"]:checked');
    if (!sel) return;
    closeModal();
    const resp = await apiPost(gameUrl("set_arrival"), { new_pos: +sel.value });
    const result = resp.action_result || {};
    G = resp; render(G);
    if (result.message) showMsg(result.message, "success");
  };
  document.getElementById("modal-cancel").onclick = async () => {
    closeModal();
    G = await apiPost(gameUrl("cancel"));
    render(G);
  };
}

function showScoresModal(state) {
  const scores = state.scores || {};
  const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const arrivals = state.arrivals_display || [];

  document.getElementById("modal-title").textContent = "Current Scores";
  document.getElementById("modal-sub").textContent = "";
  document.getElementById("modal-options").innerHTML = `
    <div style="margin-bottom:12px">
      ${ranked.map(([name, pts]) =>
        `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #2a1a4a">
          <span>${name}</span>
          <strong style="color:${pts >= 0 ? "#80FF80" : "#FF8080"}">${pts >= 0 ? "+" : ""}${pts} pts</strong>
        </div>`).join("")}
    </div>
    <div style="font-size:.78rem;color:#CCAAFF;font-weight:700;margin-bottom:5px">Breakdown:</div>
    ${arrivals.map(r => {
      const note = r.n === 1 ? "solo" : r.n === 2 ? "1st+1, 2nd+2" : "3rd −1";
      return `<div style="font-size:.76rem;color:#CCCCFF;padding:2px 0">
        Day ${r.day} – ${r.location}: ${r.players.join(" → ")} [${note}]
      </div>`;
    }).join("")}`;

  document.getElementById("modal-overlay").classList.remove("hidden");
  document.getElementById("modal-confirm").style.display = "none";
  document.getElementById("modal-cancel").textContent = "Close";
  document.getElementById("modal-cancel").onclick = closeModal;
}

function closeModal() {
  document.getElementById("modal-overlay").classList.add("hidden");
}

/* ══ END SCREEN ═════════════════════════════════════════════════════════════ */
function endHTML(state) {
  const scores   = state.scores || {};
  const ranked   = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const medals   = ["🥇", "🥈", "🥉"];
  const arrivals = state.arrivals_display || [];

  return `
<div class="end-screen">
  <h1>Game Over!</h1>
  <div class="podium">
    ${ranked.map(([name, pts], i) => `
      <div class="podium-row ${i === 0 ? "rank-1" : ""}">
        <span class="podium-medal">${medals[i] || `#${i+1}`}</span>
        <span class="podium-name">${name}</span>
        <span class="podium-score">${pts >= 0 ? "+" : ""}${pts} pts</span>
      </div>`).join("")}
  </div>
  <div class="breakdown">
    <h3>Date Results</h3>
    ${arrivals.map(r => {
      const pts = ({1:[1,2,-1],2:[1,2,-1],3:[2,1,-1],4:[4,2,-2],5:[3,3,-2],6:[1,1,0]})[r.card_type] || [1,2,-1];
      let note, cls;
      if (r.n === 1) {
        const solo = r.card_type === 5;
        note = solo ? "solo — −1 pt (Beach penalty)" : "solo — no points";
        cls  = solo ? "bad" : "neutral";
      } else if (r.n === 2) {
        note = `1st: ${pts[0]>=0?"+":""}${pts[0]} · 2nd: ${pts[1]>=0?"+":""}${pts[1]}`;
        cls  = "good";
      } else {
        note = `3rd wheel: ${pts[2]}`;
        cls  = "bad";
      }
      return `<div class="breakdown-row">
        <span class="bday">Day ${r.day}</span>
        <span class="bloc">${r.location}</span>
        <span class="bplrs">${r.players.join(" → ")}</span>
        <span class="bscore ${cls}">${note}</span>
      </div>`;
    }).join("")}
  </div>
  <button id="play-again" class="btn btn-primary">▶ Play Again</button>
  ${(state.move_log || []).length > 0 ? `
  <div class="move-log-panel end-log">
    <div class="move-log-title">Move Log</div>
    <div class="move-log-list">
      ${state.move_log.map(e =>
          `<div class="log-entry${e.startsWith("↳") ? " log-ability" : ""}">${e}</div>`
        ).join("")}
    </div>
  </div>` : ""}
</div>`;
}

function bindEnd() {
  document.getElementById("play-again").addEventListener("click", () => {
    clearRoom();
    window.location.href = "/";
  });
}
