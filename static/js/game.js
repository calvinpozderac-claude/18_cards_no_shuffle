/* ── per-card scoring text ────────────────────────────────────────────────── */
const CARD_SCORING = {
  1: "1st+1 · 2nd+2 · 3rd−1",
  2: "1st+1 · 2nd+2 · 3rd−1",
  3: "1st+3 · 2nd+1 · 3rd−2",
  4: "1st−1 · 2nd+1 · 3rd+3",
  5: "1st+5 · 2nd+3 · 3rd−4",
  6: "1st+3 · 2nd+1 · 3rd±0",
};

const DAY_MATCH_HINT = "Day-matching bonus: if type N on day N — +2 (normal) or +1 (strong) if 2+ players; −1 if alone";

/* ── theme ───────────────────────────────────────────────────────────────── */
function currentTheme() {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}
function applyTheme(theme) {
  if (theme === "light") document.documentElement.setAttribute("data-theme", "light");
  else document.documentElement.removeAttribute("data-theme");
  localStorage.setItem("dtbtw_theme", theme);
  document.querySelectorAll(".theme-toggle-btn, .topbar-theme-btn").forEach(el => {
    el.textContent = theme === "light" ? "🌙" : "☀️";
    el.title = theme === "light" ? "Switch to dark mode" : "Switch to light mode";
  });
}
function toggleTheme() { applyTheme(currentTheme() === "light" ? "dark" : "light"); }

/* ── card change tracking (for animations) ───────────────────────────────── */
function snapshotCards(state) {
  const snap = {};
  (state.players || []).forEach((p, pi) => {
    (p.cards || []).forEach((c, di) => {
      if (!c) return;  // null guard for empty slots
      snap[`${pi}-${di + 1}`] = { face_up: c.face_up, card_type: c.card_type };
    });
  });
  return snap;
}

function animateCardChanges(prev, state) {
  if (!prev) return;
  document.querySelectorAll(".card[data-pi][data-day]").forEach(el => {
    const pi  = +el.dataset.pi;
    const day = +el.dataset.day;
    const old = prev[`${pi}-${day}`];
    if (!old) return;
    const cur = (state.players[pi] || {}).cards?.[day - 1];
    if (!cur) return;
    if (old.face_up !== cur.face_up) {
      el.classList.add("card-anim-flip");
    } else if (old.card_type !== cur.card_type) {
      el.classList.add("card-anim-swap");
    }
  });
}

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
  return `${s.phase}|${s.turn_count}|${s.pending_action}|${(s.players||[]).map(p=>p.arranged).join(",")}|${(s.move_log||[]).length}|${s.draft_pick_idx||0}|${s.current_date_ct||''}|${(s.date_results||[]).length}|${s.my_date_move}|${s.round_choices_submitted||0}|${s.i_have_chosen}`;
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
  // Inject floating theme toggle (persists across all screen renders)
  const themeBtn = document.createElement("button");
  themeBtn.className = "theme-toggle-btn";
  themeBtn.addEventListener("click", toggleTheme);
  document.body.appendChild(themeBtn);
  applyTheme(currentTheme()); // sync button label to current theme

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
      <h3>Card Abilities (Strong / Normal)</h3>
      ${Object.entries(CARD_ABILITIES).map(([ct, ab]) => `
        <div class="rule-row">
          <span class="card-badge ct-${ct}">${ct}</span>
          <span class="loc-name">${LOCATION_NAMES[ct]}</span>:
          <span style="font-size:.75rem"><strong>S:</strong> ${ab.strong}<br><strong>N:</strong> ${ab.normal}</span>
        </div>`).join("")}
    </div>
    <div class="rules-box">
      <h3>Scoring</h3>
      ${Object.entries(CARD_SCORING).map(([ct, sc]) => `
        <div class="rule-row">
          <span class="card-badge ct-${ct}">${ct}</span>
          <span class="loc-name">${LOCATION_NAMES[ct]}</span>: ${sc}
        </div>`).join("")}
      <div class="rule-row" style="margin-top:6px;color:#FFCCAA;font-size:.75rem">${DAY_MATCH_HINT}</div>
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
          <input type="number" class="rollout-input" id="ai-rollouts-inp" value="50" min="1" />
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
          ? Math.max(1, parseInt(document.getElementById("ai-rollouts-inp").value)||50)
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
  const prevSnap = (G && G.phase === "game" && state.phase === "game") ? snapshotCards(G) : null;
  G = state;
  lastRenderKey = renderKey(state);
  const app = document.getElementById("app");

  if (!GAME_ID) {
    renderRoomLobby(); return;
  }
  if (state.phase === "draft") {
    app.innerHTML = draftHTML(state);
    bindDraft(state);
  } else if (state.phase === "arrangement") {
    const me = state.players[MY_IDX];
    if (!me.arranged) {
      app.innerHTML = arrangeHTML(state);
      bindArrange(state);
    } else {
      app.innerHTML = waitingHTML(state);
    }
  } else if (state.phase === "choosing") {
    app.innerHTML = choosingHTML(state);
    bindChoosing(state);
  } else if (state.phase === "game") {
    app.innerHTML = gameHTML(state);
    bindGame(state, prevSnap);
  } else if (state.phase === "date_resolution") {
    app.innerHTML = dateResolutionHTML(state);
    bindDateResolution(state);
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

/* ══ DRAFT SCREEN ═══════════════════════════════════════════════════════════ */
function draftHTML(state) {
  const draftOrder = state.draft_order || [];
  const pickIdx = state.draft_pick_idx || 0;
  const pool = state.draft_pool || [];
  const myDraftCards = (state.players[MY_IDX] || {}).draft_cards || [];
  const isMyDraftTurn = pickIdx < draftOrder.length && draftOrder[pickIdx] === MY_IDX;
  const currentDrafter = pickIdx < draftOrder.length
    ? (state.players[draftOrder[pickIdx]] || {}).name || "?"
    : "Draft complete";

  // Build snake order visualization
  const snakeViz = draftOrder.map((pidx, i) => {
    const isCurrent = i === pickIdx;
    const isPast = i < pickIdx;
    const pname = (state.players[pidx] || {}).name || `P${pidx+1}`;
    return `<span class="draft-order-item ${isCurrent ? "draft-order-current" : ""} ${isPast ? "draft-order-past" : ""}"
      title="${pname}">${i+1}. ${pname.slice(0,6)}</span>`;
  }).join("");

  return `
<div class="screen draft-screen">
  <h1 class="title" style="font-size:1.7rem">Snake Draft Phase</h1>
  <p class="subtitle">Draft 2 strong cards. Everyone gets 1 normal card for each type they didn't draft.</p>

  <div class="draft-status-bar">
    ${isMyDraftTurn
      ? `<span class="draft-your-turn">It's YOUR turn to pick! (Pick ${pickIdx + 1} of ${draftOrder.length})</span>`
      : pickIdx < draftOrder.length
        ? `<span class="draft-waiting">Waiting for <strong>${currentDrafter}</strong> to pick (Pick ${pickIdx + 1} of ${draftOrder.length})</span>`
        : `<span class="draft-done">Draft complete! Proceeding to arrangement…</span>`}
  </div>

  <div class="draft-snake-order">${snakeViz}</div>

  <div class="draft-my-picks">
    <span class="draft-section-label">Your strong picks:</span>
    ${myDraftCards.filter(c => c.strength === "strong").map(c => `
      <span class="draft-picked-card ct-${c.card_type}">
        ${LOCATION_NAMES[c.card_type]} (★ Strong)
      </span>`).join("")}
    ${myDraftCards.filter(c => c.strength === "strong").length === 0
      ? '<span class="draft-none">None yet</span>' : ""}
  </div>

  <p style="text-align:center;font-weight:700;color:#CC99FF;margin:12px 0 6px">Draft Pool — Available Strong Cards</p>
  <div class="draft-pool-grid">
    ${[1,2,3,4,5,6].map(ct => {
      const inPool = pool.some(c => c.card_type === ct);
      const picked = myDraftCards.some(c => c.card_type === ct && c.strength === "strong");
      return `
      <button class="draft-card ct-${ct} ${!inPool ? "draft-card-taken" : ""} ${isMyDraftTurn && inPool ? "draft-card-selectable" : ""}"
              id="draftcard-${ct}" ${!isMyDraftTurn || !inPool ? "disabled" : ""}
              data-ct="${ct}">
        <div class="draft-card-strength">★ Strong</div>
        <div class="draft-card-num">${ct}</div>
        <div class="draft-card-name">${LOCATION_NAMES[ct]}</div>
        <div class="draft-card-ability-s">${CARD_ABILITIES[ct].strong}</div>
        <hr class="card-divider" style="margin:4px 0"/>
        <div class="draft-card-normal-hint">Normal: ${CARD_ABILITIES[ct].normal}</div>
        <div class="draft-card-score">${CARD_SCORING[ct]}</div>
        <div class="draft-card-matchday">Match Day ${ct} for bonus</div>
        ${!inPool ? '<div class="draft-card-taken-label">TAKEN</div>' : ""}
      </button>`;
    }).join("")}
  </div>

  <p style="text-align:center;font-size:.78rem;color:#8870aa;margin-top:12px">${DAY_MATCH_HINT}</p>
</div>`;
}

function bindDraft(state) {
  const pool = state.draft_pool || [];
  const pickIdx = state.draft_pick_idx || 0;
  const draftOrder = state.draft_order || [];
  const isMyDraftTurn = pickIdx < draftOrder.length && draftOrder[pickIdx] === MY_IDX;

  if (!isMyDraftTurn) return;

  document.querySelectorAll(".draft-card-selectable").forEach(btn => {
    btn.addEventListener("click", async () => {
      const ct = parseInt(btn.dataset.ct);
      G = await apiPost(gameUrl("draft_pick"), { card_type: ct });
      render(G);
    });
  });
}

/* ══ ARRANGEMENT ════════════════════════════════════════════════════════════ */
function arrangeHTML(state) {
  const me = state.players[MY_IDX];
  const myDraftCards = me.draft_cards || [];

  return `
<div class="arrange-screen">
  <h1 class="title" style="font-size:1.7rem">Schedule Your Dates!</h1>
  <p class="subtitle">
    <strong style="color:#80FFCC">${me.name}</strong> —
    assign each location to a Day. Only you can see this screen.
  </p>
  <p style="text-align:center;font-size:.78rem;color:#FFCCAA;margin-bottom:8px">${DAY_MATCH_HINT}</p>

  <p style="text-align:center;font-weight:700;color:#CC99FF;margin-bottom:6px">Your Cards</p>
  <div class="loc-cards" id="loc-cards">
    ${myDraftCards.map(card => `
      <button class="loc-btn" id="loc-${card.card_type}" style="background:${LOC_COLORS[card.card_type]};border-color:${LOC_COLORS[card.card_type]}">
        <span class="lnum">${card.card_type}</span>
        <span class="strength-badge ${card.strength === 'strong' ? 'strength-strong' : 'strength-normal'}">
          ${card.strength === 'strong' ? '★ Strong' : 'Normal'}
        </span>
        <span class="lname">${LOCATION_NAMES[card.card_type]}</span>
        <span class="labil">${card.strength === 'strong' ? CARD_ABILITIES[card.card_type].strong : CARD_ABILITIES[card.card_type].normal}</span>
        <span class="lmatch" style="font-size:.6rem;opacity:.7">Match Day ${card.card_type} for bonus</span>
      </button>`).join("")}
  </div>

  <p style="text-align:center;font-weight:700;color:#CC99FF;margin-bottom:6px">Day Slots</p>
  <div class="day-slots" id="day-slots">
    ${[1,2,3,4,5,6].map(d => `
      <div class="day-slot" id="slot-${d}">
        <span class="dlabel">Day ${d}</span>
        <span class="dct"></span>
        <span class="dname" style="color:#8870aa">(empty)</span>
        <span class="dmatch" style="font-size:.6rem;color:#5a8a5a">(match for type ${d})</span>
      </div>`).join("")}
  </div>

  <p class="arrange-status" id="arr-status">Select a card to begin.</p>
  <button id="arr-confirm" class="btn btn-primary arrange-confirm" disabled>Lock In My Schedule →</button>
</div>`;
}

function bindArrange(state) {
  const me = state.players[MY_IDX];
  const myDraftCards = me.draft_cards || [];
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
      const card = myDraftCards.find(c => c.card_type === ct);
      const s = card ? card.strength : "normal";
      setStatus(`Selected: ${ct} – ${LOCATION_NAMES[ct]} (${s === 'strong' ? '★ Strong' : 'Normal'}). Now click a Day slot.`);
    });
  });

  document.querySelectorAll(".day-slot").forEach(slot => {
    slot.addEventListener("click", () => {
      const day = +slot.id.split("-")[1];
      if (!selCt) { setStatus("Select a card first!"); return; }
      if (assigned[selCt]) { setStatus(`Card ${selCt} already placed!`); return; }
      if (dayTaken[day]) { setStatus(`Day ${day} is taken! Choose another.`); return; }

      assigned[selCt] = day;
      dayTaken[day] = selCt;
      const card = myDraftCards.find(c => c.card_type === selCt);
      const s = card ? card.strength : "normal";
      slot.classList.add("filled");
      slot.style.background = LOC_COLORS[selCt];
      slot.querySelector(".dct").textContent = selCt;
      slot.querySelector(".dname").textContent = LOCATION_NAMES[selCt] + (s === "strong" ? " ★" : "");
      slot.querySelector(".dname").style.color = "";
      slot.querySelector(".dmatch").style.display = (day === selCt) ? "" : "none";
      document.getElementById(`loc-${selCt}`).disabled = true;
      document.getElementById(`loc-${selCt}`).classList.remove("selected");
      selCt = 0;
      const rem = myDraftCards.length - Object.keys(assigned).length;
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

/* ══ CHOOSING SCREEN ════════════════════════════════════════════════════════ */
function choosingHTML(state) {
  const me = state.players[MY_IDX];
  const hand = me.hand_cards || [];
  const submitted = state.round_choices_submitted || 0;
  const total = state.round_choices_total || state.players.length;
  const iHaveChosen = state.i_have_chosen;
  const banked = state.pocketed_ability;
  const locks = state.locks || [];
  const scores = state.scores || {};
  // Round number = number of cards placed so far on my board + 1
  const cardsPlaced = (me.cards || []).filter(c => c !== null && c !== undefined).length;
  const round = cardsPlaced + 1;

  const statusMsg = iHaveChosen
    ? `Waiting for others… (${submitted}/${total} ready)`
    : `Select a card below, then click an empty Day slot in your row.`;

  const handHTML = hand.length === 0
    ? `<div style="color:#8870aa;font-style:italic;padding:12px">No cards left in hand…</div>`
    : hand.map(c => {
        const ct = c.card_type, s = c.strength || "normal", isStrong = s === "strong";
        return `<button class="hand-card ct-${ct}" data-ct="${ct}" ${iHaveChosen ? "disabled" : ""}>
          <div class="hand-card-inner">
            <span class="card-num">${ct}</span>
            <span class="card-name">${LOCATION_NAMES[ct]}</span>
            <div class="strength-badge-card ${isStrong ? "strength-strong" : "strength-normal"}">${isStrong ? "★ Strong" : "Normal"}</div>
            <div class="card-ability" style="font-size:.6rem">${CARD_ABILITIES[ct] ? (isStrong ? CARD_ABILITIES[ct].strong : CARD_ABILITIES[ct].normal) : ""}</div>
            <div class="card-scoring" style="font-size:.6rem">${CARD_SCORING[ct]}</div>
          </div>
        </button>`;
      }).join("");

  return `
<div class="screen choosing-screen">
  <div class="topbar">
    <span class="topbar-title">Don't Be the Third Wheel!</span>
    <span class="topbar-turn">Round ${round} — ${iHaveChosen ? `Waiting (${submitted}/${total})` : "Choose Your Card!"}</span>
    <div class="topbar-btns">
      <button class="topbar-theme-btn" id="btn-theme" onclick="toggleTheme()"></button>
      <button class="btn btn-green" id="btn-scores-ch">Scores</button>
    </div>
  </div>

  <div class="action-strip">
    <span class="action-msg ${iHaveChosen ? "waiting" : ""}" id="action-msg">${statusMsg}</span>
    ${banked ? `<span class="banked-pill">💰 Banked: ${LOCATION_NAMES[banked.card_type]}${banked.strength === "strong" ? " ★" : ""}</span>` : ""}
  </div>

  <div class="board-container">
    <div class="board">
      <div class="board-corner"></div>
      ${[1,2,3,4,5,6].map(d => {
        const hasLock = locks.some(l => l[1] === d - 1);
        return `<div class="board-day-header ${hasLock ? "day-has-lock" : ""}">Day ${d}${hasLock ? " 🔒" : ""}</div>`;
      }).join("")}
      ${state.players.map((player, pi) => boardRowHTML(state, pi, player)).join("")}
    </div>
  </div>

  <div class="hand-row">
    <div class="hand-row-label">${iHaveChosen ? "Waiting for others…" : "Your Hand — pick a card, then click an empty slot above ↑"}</div>
    <div class="hand-row-cards" id="hand-row-cards">${handHTML}</div>
    ${banked && !iHaveChosen ? `
    <div class="pocket-use-row" style="padding:8px 12px;border-top:1px solid #2a1a4a">
      <button class="btn btn-pocket" id="btn-use-pocket-choosing">
        💰 Use pocketed ${LOCATION_NAMES[banked.card_type]}${banked.strength === "strong" ? " ★" : ""} instead of playing a card
      </button>
    </div>` : ""}
  </div>

  <div class="score-strip">
    ${state.players.map(p =>
      `<span class="score-item"><strong>${p.name}</strong>: ${scores[p.name] !== undefined ? (scores[p.name] >= 0 ? "+" : "") + scores[p.name] : 0} pts</span>`
    ).join("")}
  </div>
  <div class="move-log-panel">
    <div class="move-log-title">Move Log</div>
    <div class="move-log-list">
      ${(state.move_log || []).length === 0
        ? '<div class="log-entry log-empty">No moves yet.</div>'
        : (state.move_log || []).map(e => `<div class="log-entry${e.startsWith("↳") ? " log-ability" : ""}">${e}</div>`).join("")}
    </div>
  </div>
</div>`;
}

function bindChoosing(state) {
  applyTheme(currentTheme());
  document.getElementById("btn-scores-ch")?.addEventListener("click", () => showScoresModal(G));
  if (state.i_have_chosen) return;

  document.getElementById("btn-use-pocket-choosing")?.addEventListener("click", async () => {
    const resp = await apiPost(gameUrl("choose_pocket"));
    if (resp.error) { showMsg(resp.error, "error"); return; }
    G = resp; render(G);
    if (G.action_message) showMsg(G.action_message);
  });

  let selectedCt = null;

  document.querySelectorAll(".hand-card").forEach(btn => {
    btn.addEventListener("click", () => {
      selectedCt = parseInt(btn.dataset.ct);
      document.querySelectorAll(".hand-card").forEach(b => b.classList.remove("selected"));
      btn.classList.add("selected");
      document.querySelectorAll(".card.empty-slot.target-slot").forEach(s => s.classList.add("ready"));
      showMsg(`${LOCATION_NAMES[selectedCt]} selected — click an empty Day slot in your row above.`);
    });
  });

  document.querySelectorAll(".card.empty-slot.target-slot").forEach(slot => {
    slot.addEventListener("click", async () => {
      if (!selectedCt) { showMsg("Pick a card from your hand first.", "error"); return; }
      const day = parseInt(slot.dataset.day);
      const resp = await apiPost(gameUrl("choose_play"), { card_type: selectedCt, day });
      if (resp.error) { showMsg(resp.error, "error"); return; }
      G = resp; render(G);
    });
  });
}

/* ══ GAME SCREEN ════════════════════════════════════════════════════════════ */
function gameHTML(state) {
  const cur = state.current_player_idx;
  const isMyTurn = cur === MY_IDX;
  const scores = state.scores || {};
  const turnPlayerName = state.players[cur].name;
  const locks = state.locks || [];
  const banked = state.pocketed_ability;
  const me = state.players[MY_IDX];
  const hand = me.hand_cards || [];

  // Build bank decision modal if pending
  const bankModal = (state.pending_action === "bank_decision" && isMyTurn)
    ? buildBankModal(state) : "";

  // Determine status message for the action strip
  let actionMsg;
  if (state.pending_action && isMyTurn) {
    actionMsg = state.action_message || "";
  } else if (isMyTurn) {
    actionMsg = "Resolving abilities — your opponents are taking their turns…";
  } else {
    actionMsg = `Waiting for <strong>${turnPlayerName}</strong> to resolve their ability…`;
  }

  // Hand row: show hand cards (greyed out — can't play during ability resolution)
  const handHTML = hand.length === 0
    ? `<div style="color:#8870aa;font-style:italic;padding:12px">No cards left in hand</div>`
    : hand.map(c => {
        const ct = c.card_type, s = c.strength || "normal", isStrong = s === "strong";
        return `<button class="hand-card ct-${ct}" data-ct="${ct}" disabled style="opacity:0.45;cursor:default">
          <div class="hand-card-inner">
            <span class="card-num">${ct}</span>
            <span class="card-name">${LOCATION_NAMES[ct]}</span>
            <div class="strength-badge-card ${isStrong ? "strength-strong" : "strength-normal"}">${isStrong ? "★ Strong" : "Normal"}</div>
            <div class="card-ability" style="font-size:.6rem">${CARD_ABILITIES[ct] ? (isStrong ? CARD_ABILITIES[ct].strong : CARD_ABILITIES[ct].normal) : ""}</div>
            <div class="card-scoring" style="font-size:.6rem">${CARD_SCORING[ct]}</div>
          </div>
        </button>`;
      }).join("");

  return `
<div class="screen choosing-screen">
  <div class="topbar">
    <span class="topbar-title">Don't Be the Third Wheel!</span>
    <span class="topbar-turn">
      Round ${state.turn_count} —
      ${isMyTurn ? "<strong style='color:#FFD700'>Resolve your ability!</strong>" : `<strong>${turnPlayerName}</strong> resolving ability`}
    </span>
    <div class="topbar-btns">
      <button class="topbar-theme-btn" id="btn-theme" onclick="toggleTheme()"></button>
      <button class="btn btn-green" id="btn-scores">Scores</button>
      <button class="btn btn-red"   id="btn-end">End Game</button>
    </div>
  </div>

  <div class="action-strip">
    <span class="action-msg ${isMyTurn && state.pending_action ? "" : "waiting"}" id="action-msg">${actionMsg}</span>
    ${isMyTurn && state.pending_action && state.pending_action !== "bank_decision" && state.pending_action !== "pocket_choice"
      ? `<button class="btn btn-cancel" id="btn-cancel">✕ Cancel</button>`
      : ""}
    ${banked ? `<span class="banked-pill">💰 Banked: ${LOCATION_NAMES[banked.card_type]}${banked.strength === "strong" ? " ★" : ""}</span>` : ""}
  </div>

  ${bankModal}

  ${buildPocketChoiceModal(state)}

  ${buildLockDayPicker(state)}

  <div class="board-container">
    <div class="board">
      <div class="board-corner"></div>
      ${[1,2,3,4,5,6].map(d => {
        const hasLock = locks.some(l => l[1] === d - 1);
        return `<div class="board-day-header ${hasLock ? 'day-has-lock' : ''}">Day ${d}${hasLock ? ' 🔒' : ''}</div>`;
      }).join("")}
      ${state.players.map((player, pi) => boardRowHTML(state, pi, player)).join("")}
    </div>
  </div>

  <div class="hand-row">
    <div class="hand-row-label">Your Hand — abilities resolving, next round starts soon</div>
    <div class="hand-row-cards">${handHTML}</div>
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

function buildBankModal(state) {
  const ctx = state.action_ctx || {};
  const strength = ctx.strength || "normal";
  const pts = strength === "strong" ? 2 : 1;
  return `
<div class="bank-modal-overlay" id="bank-modal">
  <div class="bank-modal">
    <h3 class="bank-modal-title">Beach Card Flipped!</h3>
    <p class="bank-modal-desc">
      Bank <strong style="color:#FFD700">+${pts} pts</strong> now (immediate, but lose day-matching bonus).<br>
      Or keep eligible for day-matching bonus (risky if flipped down later).
    </p>
    <div class="bank-modal-btns">
      <button class="btn btn-primary" id="btn-bank-yes">Bank (+${pts} pts)</button>
      <button class="btn btn-outline" id="btn-bank-no">Don't Bank (day-match)</button>
    </div>
  </div>
</div>`;
}

function buildPocketChoiceModal(state) {
  if (state.pending_action !== "pocket_choice") return "";
  if (state.current_player_idx !== MY_IDX) return "";
  const ctx = state.action_ctx || {};
  const ct = ctx.pocket_ct;
  const s = ctx.pocket_strength;
  const banked = state.pocketed_ability;
  const abilityName = CARD_ABILITIES[ct] ? (s === "strong" ? CARD_ABILITIES[ct].strong : CARD_ABILITIES[ct].normal) : "";

  const bankedSection = banked
    ? `<div class="bank-stored-row">
        <span class="bank-stored-label">Banked:</span>
        <span class="bank-stored-card" style="color:${LOC_COLORS[banked.card_type]}">
          ${LOCATION_NAMES[banked.card_type]}${banked.strength === 'strong' ? ' ★' : ''}
        </span>
        <span class="bank-stored-ability">${CARD_ABILITIES[banked.card_type] ? (banked.strength === 'strong' ? CARD_ABILITIES[banked.card_type].strong : CARD_ABILITIES[banked.card_type].normal) : ''}</span>
      </div>`
    : `<div class="bank-stored-row bank-stored-empty">No banked action</div>`;

  const buttons = banked ? `
    <button class="btn btn-primary" id="btn-pocket-use-now">▶ Use card action</button>
    <button class="btn btn-pocket" id="btn-pocket-use-banked">🔄 Use banked (bank this one)</button>
    <button class="btn btn-cancel" id="btn-pocket-skip">✕ Skip</button>
  ` : `
    <button class="btn btn-primary" id="btn-pocket-use-now">▶ Use action</button>
    <button class="btn btn-pocket" id="btn-pocket-save">💰 Bank for later</button>
    <button class="btn btn-cancel" id="btn-pocket-skip">✕ Skip</button>
  `;

  return `
<div class="bank-modal-overlay" id="pocket-modal">
  <div class="bank-modal">
    <h3 class="bank-modal-title">${LOCATION_NAMES[ct]}${s === 'strong' ? ' ★' : ''} played</h3>
    <div class="bank-card-action">${abilityName}</div>
    <div class="bank-divider"></div>
    ${bankedSection}
    <div class="bank-modal-btns" style="flex-direction:column;gap:8px;margin-top:12px">
      ${buttons}
    </div>
  </div>
</div>`;
}


function buildLockDayPicker(state) {
  if (!state.pending_action || state.current_player_idx !== MY_IDX) return "";
  if (state.pending_action !== "lock_pick_day") return "";
  const strength = (state.action_ctx || {}).strength || "normal";
  return `
<div class="lock-day-picker" id="lock-day-picker">
  <span class="lock-day-label">Lock which day? ${strength === 'strong' ? '(ALL cards on that day)' : '(choose 2 cards after)'}</span>
  ${[1,2,3,4,5,6].map(d =>
    `<button class="btn lock-day-btn" data-day="${d}">Day ${d}</button>`
  ).join("")}
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
  if (card === null || card === undefined) {
    const isMe = pi === MY_IDX;
    if (isMe && state.phase === "choosing" && !state.i_have_chosen) {
      return `<button class="card empty-slot target-slot" data-pi="${pi}" data-day="${day}">
        <span class="card-num" style="opacity:.2">${day}</span>
        <span class="mystery-label">empty</span>
      </button>`;
    }
    return `<div class="card empty-slot" style="background:rgba(255,255,255,.03);border:1px dashed #2a1a4a" data-pi="${pi}" data-day="${day}">
      <span class="card-num" style="opacity:.12">${day}</span>
    </div>`;
  }

  const isMe = pi === MY_IDX;
  const isMyTurn = state.current_player_idx === MY_IDX;
  const action = state.pending_action;
  const ctx = state.action_ctx || {};
  const isActive = pi === state.current_player_idx;
  const arrivals = state.arrivals || {};
  const locks = state.locks || [];
  const isLocked = locks.some(l => l[0] === pi && l[1] === day - 1);

  // Decide visual state class
  let stateCls = "";
  if (!action || action === "bank_decision" || action === "lock_pick_day") {
    if (action === "bank_decision") {
      stateCls = "dimmed";
    } else if (!action && isActive && !card.face_up && isMyTurn) {
      stateCls = "flippable";
    }
  } else if (isMyTurn) {
    const isOther = !isMe;
    const isOwn   = isMe;
    let valid = false;

    if (action === "flip_other_down")  valid = isOther && card.face_up && !isLocked;
    if (action === "flip_own_down")    valid = isOwn && card.face_up && !isLocked;

    if (action === "swap_own_1")       valid = isOwn && !isLocked;
    if (action === "swap_own_2") {
      if (isOwn && day === ctx.first_day) stateCls = "selected-first";
      else valid = isOwn && day !== ctx.first_day && !isLocked;
    }

    if (action === "adj_swap_own") valid = isOwn && !isLocked;
    if (action === "adj_swap_own_dir") {
      const src = ctx.adj_day;
      if (isOwn && day === src) stateCls = "selected-first";
      else {
        const adj = [(src - 2) % 6 + 1, src % 6 + 1];
        valid = isOwn && adj.includes(day) && !isLocked;
      }
    }

    if (action === "swap_other_1")    valid = isOther && !isLocked;
    if (action === "swap_other_2") {
      if (pi === ctx.first_pi && day === ctx.first_day) stateCls = "selected-first";
      else valid = pi === ctx.first_pi && day !== ctx.first_day && !isLocked;
    }

    if (action === "adj_swap_other") valid = isOther && !isLocked;
    if (action === "adj_swap_other_dir") {
      const srcPi = ctx.adj_pi;
      const src = ctx.adj_day;
      if (pi === srcPi && day === src) stateCls = "selected-first";
      else {
        const adj = [(src - 2) % 6 + 1, src % 6 + 1];
        valid = pi === srcPi && adj.includes(day) && !isLocked;
      }
    }

    if (action === "lock_pick_2") {
      const lockDay = ctx.lock_day;
      const picks = ctx.lock_picks || [];
      const alreadyPicked = picks.some(p => p[0] === pi && p[1] === day - 1);
      if (alreadyPicked) stateCls = "selected-first";
      else valid = day === lockDay && !isLocked;
    }

    if (action === "set_arrival") valid = false;

    if (!stateCls) stateCls = valid ? "target-valid" : "dimmed";
  }

  // Lock indicator
  const lockBadge = isLocked ? '<span class="lock-badge">🔒</span>' : "";

  // Opponent face-down: mystery card
  if (!card.face_up && !isMe) {
    return `
<button class="card face-down other ${stateCls}"
        data-pi="${pi}" data-day="${day}" ${stateCls === "dimmed" ? "disabled" : ""}>
  ${lockBadge}
  <span class="mystery-symbol">?</span>
  <span class="mystery-label">face down</span>
</button>`;
  }

  // Own face-down: show full card info
  if (!card.face_up && isMe) {
    const ct = card.card_type;
    const strength = card.strength || "normal";
    const isStrong = strength === "strong";
    const abilityText = isStrong ? CARD_ABILITIES[ct].strong : CARD_ABILITIES[ct].normal;
    return `
<button class="card face-down own ct-${ct} ${stateCls}"
        data-pi="${pi}" data-day="${day}">
  ${lockBadge}
  <span class="card-face-down-badge">face down</span>
  <div class="card-header">
    <span class="card-num">${ct}</span>
    <span class="card-name">${LOCATION_NAMES[ct]}</span>
  </div>
  <div class="strength-badge-card ${isStrong ? 'strength-strong' : 'strength-normal'}">${isStrong ? '★ Strong' : 'Normal'}</div>
  <hr class="card-divider"/>
  <div class="card-ability">${abilityText}</div>
  <div class="card-scoring">${CARD_SCORING[ct]}</div>
  ${day === ct ? '<div class="match-day-hint">✓ Match Day!</div>' : ''}
</button>`;
  }

  // Face-up card (anyone's)
  const ct = card.card_type;
  const strength = card.strength || "normal";
  const isStrong = strength === "strong";
  const isBanked = card.banked || false;
  const abilityText = isStrong ? CARD_ABILITIES[ct].strong : CARD_ABILITIES[ct].normal;
  const arrLabel = { 1: "▲ 1st arrival", 2: "■ 2nd arrival", 3: "▼ 3rd arrival" };
  return `
<button class="card face-up ct-${ct} ${stateCls}"
        data-pi="${pi}" data-day="${day}" ${stateCls === "dimmed" ? "disabled" : ""}>
  ${lockBadge}
  ${isBanked ? '<span class="bank-badge">💰 Banked</span>' : ""}
  <div class="card-header">
    <span class="card-num">${ct}</span>
    <span class="card-name">${LOCATION_NAMES[ct]}</span>
  </div>
  <div class="strength-badge-card ${isStrong ? 'strength-strong' : 'strength-normal'}">${isStrong ? '★ Strong' : 'Normal'}</div>
  ${card.arrival ? `<div class="card-arrival">${arrLabel[card.arrival] || `#${card.arrival}`}</div>` : ""}
  <hr class="card-divider"/>
  <div class="card-ability">${abilityText}</div>
  <div class="card-scoring">${CARD_SCORING[ct]}</div>
  ${day === ct ? '<div class="match-day-hint">✓ Match Day!</div>' : ''}
</button>`;
}

function bindGame(state, prevSnap = null) {
  applyTheme(currentTheme()); // sync topbar theme btn label after render
  animateCardChanges(prevSnap, state);

  // Bank decision buttons
  if (state.pending_action === "bank_decision" && state.current_player_idx === MY_IDX) {
    document.getElementById("btn-bank-yes")?.addEventListener("click", async () => {
      G = await apiPost(gameUrl("bank_decision"), { bank: true });
      render(G);
    });
    document.getElementById("btn-bank-no")?.addEventListener("click", async () => {
      G = await apiPost(gameUrl("bank_decision"), { bank: false });
      render(G);
    });
  }

  // Lock day picker buttons
  if (state.pending_action === "lock_pick_day" && state.current_player_idx === MY_IDX) {
    document.querySelectorAll(".lock-day-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const day = parseInt(btn.dataset.day);
        const resp = await apiPost(gameUrl("action"), { day });
        const result = resp.action_result || {};
        if (result.error) { showMsg(result.error, "error"); return; }
        G = resp; render(G);
        if (result.message) showMsg(result.message, "success");
      });
    });
  }

  // Banking modal (pocket_choice)
  if (state.pending_action === "pocket_choice" && state.current_player_idx === MY_IDX) {
    document.getElementById("btn-pocket-use-now")?.addEventListener("click", async () => {
      const resp = await apiPost(gameUrl("action"), { choice: "use_now" });
      G = resp; render(G);
      if (G.action_message) showMsg(G.action_message);
    });
    document.getElementById("btn-pocket-save")?.addEventListener("click", async () => {
      const resp = await apiPost(gameUrl("action"), { choice: "bank" });
      const result = resp.action_result || {};
      if (result.error) { showMsg(result.error, "error"); return; }
      G = resp; render(G);
      showMsg("Action banked for later!", "success");
    });
    document.getElementById("btn-pocket-use-banked")?.addEventListener("click", async () => {
      const resp = await apiPost(gameUrl("action"), { choice: "use_banked" });
      const result = resp.action_result || {};
      if (result.error) { showMsg(result.error, "error"); return; }
      G = resp; render(G);
      if (G.action_message) showMsg(G.action_message);
    });
    document.getElementById("btn-pocket-skip")?.addEventListener("click", async () => {
      const resp = await apiPost(gameUrl("action"), { choice: "skip" });
      G = resp; render(G);
    });
  }

  // Use pocketed ability button
  document.getElementById("btn-use-pocket")?.addEventListener("click", async () => {
    G = await apiPost(gameUrl("use_pocket"));
    render(G);
    if (G.action_message) showMsg(G.action_message);
  });

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
  const action = G.pending_action;

  if (action === "bank_decision") return; // handled by bank buttons
  if (action === "lock_pick_day") return; // handled by day picker buttons

  if (!action && MY_IDX !== G.current_player_idx) {
    return; // not our turn, ignore
  }

  if (action) {
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
    if (G.action_message && G.pending_action && G.pending_action !== "bank_decision") {
      showMsg(G.action_message);
    }
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
      const note = r.n === 1 ? "solo" : r.n === 2 ? "1st+pts, 2nd+pts" : "3rd penalty";
      return `<div style="font-size:.76rem;color:#CCCCFF;padding:2px 0">
        ${r.location}: ${r.players.join(" → ")} [${note}]
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

/* ══ DATE RESOLUTION SCREEN ══════════════════════════════════════════════════ */
function dateResolutionHTML(state) {
  const ct = state.current_date_ct;
  const day = state.current_date_day;
  const arrivals = state.arrivals || {};
  const arr = (ct && day) ? (arrivals[`${ct}_${day}`] || []) : [];
  const participants = arr.slice(0, 3);
  const iAmIn = state.i_am_in_date;
  const myMove = state.my_date_move;
  const submitted = state.date_moves_submitted || 0;
  const total = state.date_moves_total || 0;
  const results = state.date_results || [];
  const queue = state.date_queue || [];
  const scores = state.scores || {};
  const CARD_PTS_JS = {1:[1,2,-1],2:[1,2,-1],3:[3,1,-2],4:[-1,1,3],5:[5,3,-4],6:[3,1,0]};
  const pts = ct ? (CARD_PTS_JS[ct] || []) : [];

  let currentSection = "";
  if (ct) {
    const stakeRows = participants.map((pi, i) => {
      const name = state.players[pi].name;
      const isMe = pi === MY_IDX;
      const p = pts[i] !== undefined ? pts[i] : 0;
      return `<div class="date-stake-row ${isMe ? 'is-me' : ''}">
        <span class="date-arrival-pos">${['1st','2nd','3rd'][i]}</span>
        <span class="date-player-name">${name}${isMe ? ' (you)' : ''}</span>
        <span class="date-stake-pts" style="color:${p >= 0 ? '#80FF80' : '#FF8080'}">${p >= 0 ? '+' : ''}${p} pts at stake</span>
      </div>`;
    }).join("");

    let decisionArea = "";
    if (!iAmIn) {
      decisionArea = `<div class="date-not-in">You're not at this location — watching…</div>`;
    } else if (myMove === null || myMove === undefined) {
      decisionArea = `
<div class="date-decision">
  <p class="date-decision-hint">Choose secretly — all decisions reveal at once!</p>
  <div class="date-decision-btns">
    <button class="btn btn-primary date-btn-move" id="btn-make-move">🎯 Make a Move</button>
    <button class="btn btn-outline date-btn-safe" id="btn-play-safe">🛡️ Play it Safe</button>
  </div>
</div>`;
    } else {
      decisionArea = `<div class="date-waiting">
        <span style="color:#FFD700;font-size:1rem">${myMove ? '🎯 You made a move' : '🛡️ You played it safe'}</span>
        <div class="spinner" style="margin:8px auto"></div>
        <p style="font-size:.8rem;color:#8870aa">${submitted}/${total} decided — waiting for reveal…</p>
      </div>`;
    }

    currentSection = `
<div class="date-current">
  <div class="date-location-header" style="background:${LOC_COLORS[ct]}18;border-color:${LOC_COLORS[ct]}">
    <span class="date-loc-num" style="color:${LOC_COLORS[ct]};font-size:1.4rem;font-weight:900">${ct}</span>
    <span class="date-loc-name">${LOCATION_NAMES[ct]}</span>
    <span class="date-loc-queue" style="font-size:.75rem;color:#8870aa">Date ${queue.indexOf(`${ct}_${day}`)+1} of ${queue.length}</span>
  </div>
  <div class="date-stakes">${stakeRows}</div>
  ${decisionArea}
</div>`;
  }

  const pastResults = results.length > 0 ? `
<div class="date-history">
  <h3 style="color:#CC99FF;margin:16px 0 8px">Resolved Dates</h3>
  ${[...results].reverse().map((r, ri) => {
    const isLatest = ri === 0;
    return `<div class="date-result-card ${isLatest ? 'date-result-latest' : ''}">
      <div class="date-result-header">
        <span style="color:${LOC_COLORS[r.ct]};font-weight:700">${r.location}</span>
        <span class="date-result-outcome">${r.outcome}</span>
      </div>
      ${r.pidxs.map((pi, i) => {
        const moved = r.moves[String(pi)];
        const rpts = r.result_pts[String(pi)];
        const npts = r.normal_pts[String(pi)];
        const changed = rpts !== npts;
        return `<div class="date-result-row">
          <span>${moved ? '🎯' : '🛡️'} ${r.players[i]}</span>
          <span style="color:${rpts>=0?'#80FF80':'#FF8080'};font-weight:${changed?700:400}">
            ${rpts>=0?'+':''}${rpts}${changed ? ` (was ${npts>=0?'+':''}${npts})` : ''}
          </span>
        </div>`;
      }).join("")}
    </div>`;
  }).join("")}
</div>` : "";

  return `
<div class="screen date-resolution-screen">
  <div class="topbar">
    <span class="topbar-title">Don't Be the Third Wheel!</span>
    <span class="topbar-turn" style="color:#FFD700">📅 Having the Dates…</span>
    <div class="topbar-btns">
      <button class="topbar-theme-btn" id="btn-theme" onclick="toggleTheme()"></button>
    </div>
  </div>
  <div style="max-width:580px;margin:0 auto;padding:16px">
    ${currentSection}
    <div class="score-strip">
      ${state.players.map(p =>
        `<span class="score-item"><strong>${p.name}</strong>: ${
          scores[p.name] !== undefined ? (scores[p.name] >= 0 ? '+' : '') + scores[p.name] : 0
        } pts</span>`
      ).join("")}
    </div>
    ${pastResults}
  </div>
</div>`;
}

function bindDateResolution(state) {
  applyTheme(currentTheme());
  document.getElementById("btn-make-move")?.addEventListener("click", async () => {
    G = await apiPost(gameUrl("make_move"), { make_move: true });
    render(G);
  });
  document.getElementById("btn-play-safe")?.addEventListener("click", async () => {
    G = await apiPost(gameUrl("make_move"), { make_move: false });
    render(G);
  });
}

/* ══ END SCREEN ═════════════════════════════════════════════════════════════ */
function endHTML(state) {
  const scores   = state.scores || {};
  const ranked   = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const medals   = ["🥇", "🥈", "🥉"];
  const arrivals = state.arrivals_display || [];
  const locks    = state.locks || [];

  // Compute day-match bonuses for display
  const dayMatchRows = [];
  for (let ct = 1; ct <= 6; ct++) {
    const matching = state.players
      .map((p, pi) => {
        const card = p.cards && p.cards[ct - 1];
        if (card && card.card_type === ct && card.face_up && !card.banked) {
          return { name: p.name, strength: card.strength || "normal" };
        }
        return null;
      })
      .filter(Boolean);
    if (matching.length === 1) {
      dayMatchRows.push({ ct, players: matching, bonus: -1, note: `−1 (alone on Day ${ct})` });
    } else if (matching.length >= 2) {
      dayMatchRows.push({
        ct, players: matching,
        note: matching.map(m => `${m.name}: ${m.strength === 'strong' ? '+1' : '+2'}`).join(", ")
      });
    }
  }

  // Compute bank rows
  const bankRows = [];
  state.players.forEach(p => {
    (p.cards || []).forEach(card => {
      if (card && card.banked && card.face_up) {
        const pts = card.strength === "strong" ? 2 : 1;
        bankRows.push({ name: p.name, ct: card.card_type, pts });
      }
    });
  });

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
    ${(state.date_results && state.date_results.length > 0)
      ? state.date_results.map(r => `
        <div style="border-bottom:1px solid #2a1a4a;padding:8px 0">
          <div style="display:flex;justify-content:space-between;margin-bottom:4px">
            <span class="bloc" style="color:${LOC_COLORS[r.ct]}">${r.location}</span>
            <span style="font-size:.72rem;color:#CCAAFF">${r.outcome}</span>
          </div>
          ${r.pidxs.map((pi, i) => {
            const moved = r.moves[String(pi)];
            const rpts = r.result_pts[String(pi)];
            const npts = r.normal_pts[String(pi)];
            return `<div class="breakdown-row" style="border:none;padding:2px 0">
              <span class="bplrs">${moved ? '🎯' : '🛡️'} ${r.players[i]}</span>
              <span class="bscore ${rpts >= 0 ? 'good' : 'bad'}">${rpts>=0?'+':''}${rpts}${rpts!==npts?` (was ${npts>=0?'+':''}${npts})`:''}</span>
            </div>`;
          }).join("")}
        </div>`).join("")
      : arrivals.map(r => {
          const pts = ({1:[1,2,-1],2:[1,2,-1],3:[3,1,-2],4:[-1,1,3],5:[5,3,-4],6:[3,1,0]})[r.card_type] || [1,2,-1];
          const note = r.n === 1 ? "solo — no pts" : r.n === 2
            ? `1st:${pts[0]>=0?'+':''}${pts[0]} · 2nd:${pts[1]>=0?'+':''}${pts[1]}`
            : `1st:+${pts[0]} 2nd:+${pts[1]} 3rd:${pts[2]}`;
          return `<div class="breakdown-row">
            <span class="bloc">${r.location}</span>
            <span class="bplrs">${r.players.join(" → ")}</span>
            <span class="bscore ${r.n===1?'neutral':r.n===2?'good':'bad'}">${note}</span>
          </div>`;
        }).join("")}
  </div>

  ${dayMatchRows.length > 0 ? `
  <div class="breakdown" style="margin-top:16px">
    <h3>Day-Matching Bonuses</h3>
    ${dayMatchRows.map(r => `
      <div class="breakdown-row">
        <span class="bday">Type ${r.ct}</span>
        <span class="bloc">Day ${r.ct}</span>
        <span class="bplrs">${r.players.map(m=>m.name).join(", ")}</span>
        <span class="bscore ${r.bonus === -1 ? 'bad' : 'good'}">${r.note}</span>
      </div>`).join("")}
  </div>` : ""}

  ${bankRows.length > 0 ? `
  <div class="breakdown" style="margin-top:16px">
    <h3>Banked Points</h3>
    ${bankRows.map(r => `
      <div class="breakdown-row">
        <span class="bday">${r.name}</span>
        <span class="bloc">${LOCATION_NAMES[r.ct]}</span>
        <span class="bplrs">Beach card banked</span>
        <span class="bscore good">+${r.pts} pts</span>
      </div>`).join("")}
  </div>` : ""}

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
