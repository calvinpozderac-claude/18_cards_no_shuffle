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

/* ── state ───────────────────────────────────────────────────────────────── */
let G = null;
let pollTimer = null;
let lastRenderKey = null;  // avoid thrashing on unchanged state
let msgTimer = null;

function renderKey(s) {
  return `${s.phase}|${s.turn_count}|${s.pending_action}|${(s.players||[]).map(p=>p.arranged).join(",")}|${(s.move_log||[]).length}`;
}

/* ── entry ───────────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", async () => {
  if (GAME_ID && TOKEN) {
    G = await apiGet(gameUrl("state"));
    render(G);
    startPolling();
  } else {
    renderSetup();
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

/* ── render dispatch ─────────────────────────────────────────────────────── */
function render(state) {
  G = state;
  lastRenderKey = renderKey(state);
  const app = document.getElementById("app");

  if (!GAME_ID) {
    renderSetup(); return;
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

/* ══ SETUP SCREEN (host — no GAME_ID yet) ═══════════════════════════════════ */
function renderSetup() {
  document.getElementById("app").innerHTML = `
<div class="screen">
  <h1 class="title">Don't Be the Third Wheel!</h1>
  <p class="subtitle">A romantic scheduling strategy game for 2–3 players</p>

  <div class="setup-form">
    <div class="form-group">
      <label>Game Mode</label>
      <div class="radio-group">
        <label><input type="radio" name="mode" value="multi" checked> Multiplayer</label>
        <label><input type="radio" name="mode" value="ai"> 1 Player vs 2 AI Bots</label>
      </div>
    </div>

    <div id="multi-opts">
      <div class="form-group">
        <label>Number of Players</label>
        <div class="radio-group">
          <label><input type="radio" name="np" value="2"> 2 Players</label>
          <label><input type="radio" name="np" value="3" checked> 3 Players</label>
        </div>
      </div>
      <div class="form-group">
        <label>Player Names</label>
        <div class="name-fields">
          ${[1,2,3].map(i => `
            <div class="player-name-row" id="nr${i}">
              <span class="pnum">P${i}</span>
              <input class="player-name-input" id="pn${i}" value="Player ${i}" />
            </div>`).join("")}
        </div>
      </div>
    </div>

    <div id="ai-opts" style="display:none">
      <div class="form-group">
        <label>Your Name</label>
        <div class="name-fields">
          <div class="player-name-row">
            <span class="pnum">You</span>
            <input class="player-name-input" id="ai-name" value="Player 1" />
          </div>
        </div>
      </div>
      <div class="form-group">
        <label>AI Opponents</label>
        <div class="bot-config-list">
          ${[1, 2].map(i => `
          <div class="bot-config-row">
            <span class="bot-label">Bot ${i}</span>
            <select class="bot-type-select" id="bot-type-${i}">
              <option value="random">🎲 Random</option>
              <option value="basic">🤖 Strategic</option>
              <option value="mcts">🧠 MCTS</option>
            </select>
            <div class="mcts-rollout-group" id="mcts-grp-${i}" style="display:none">
              <label class="rollout-label">Rollouts</label>
              <input type="number" class="rollout-input" id="bot-rollouts-${i}" value="50" min="1" max="500" />
            </div>
          </div>`).join("")}
        </div>
        <div class="bot-type-hints">
          <div>🎲 <strong>Random</strong> — flips and uses abilities completely at random</div>
          <div>🤖 <strong>Strategic</strong> — avoids penalties, targets good positions, disrupts opponents</div>
          <div>🧠 <strong>MCTS</strong> — simulates many random game continuations to pick the best flip</div>
        </div>
      </div>
    </div>

    <button id="create-btn" class="btn btn-primary">Create Game →</button>
  </div>

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
      <div class="rule-row" style="margin-top:6px;color:#FFCCAA">
        Alone at Beach → −1 pt (solo penalty)
      </div>
    </div>
  </div>
</div>`;

  document.querySelectorAll('input[name="mode"]').forEach(r => r.addEventListener("change", () => {
    const isAI = document.querySelector('input[name="mode"]:checked').value === "ai";
    document.getElementById("multi-opts").style.display = isAI ? "none" : "";
    document.getElementById("ai-opts").style.display   = isAI ? ""     : "none";
  }));

  [1, 2].forEach(i => {
    const sel = document.getElementById(`bot-type-${i}`);
    if (sel) sel.addEventListener("change", () => {
      document.getElementById(`mcts-grp-${i}`).style.display =
        sel.value === "mcts" ? "flex" : "none";
    });
  });

  const updateRows = () => {
    const n = +document.querySelector('input[name="np"]:checked').value;
    document.getElementById("nr3").style.display = n >= 3 ? "" : "none";
  };
  document.querySelectorAll('input[name="np"]').forEach(r => r.addEventListener("change", updateRows));
  updateRows();

  document.getElementById("create-btn").addEventListener("click", async () => {
    const mode = document.querySelector('input[name="mode"]:checked').value;
    if (mode === "ai") {
      const humanName = document.getElementById("ai-name").value.trim() || "Player 1";
      const bots = [1, 2].map(i => {
        const type = document.getElementById(`bot-type-${i}`).value;
        if (type === "mcts") {
          const rollouts = Math.max(1, Math.min(500, parseInt(document.getElementById(`bot-rollouts-${i}`).value) || 50));
          return { type: "mcts", rollouts };
        }
        return { type };
      });
      const res = await apiPost("/api/create", { vs_ai: true, human_name: humanName, bots });
      window.location.href = res.player_url;
    } else {
      const n = +document.querySelector('input[name="np"]:checked').value;
      const names = [1,2,3].map(i => document.getElementById(`pn${i}`).value.trim());
      const res = await apiPost("/api/create", { num_players: n, names });
      renderLobby(res);
    }
  });
}

/* ── lobby (after creating a game) ──────────────────────────────────────────── */
function renderLobby(res) {
  const { game_id, tokens, player_names } = res;
  const base = window.location.origin;

  document.getElementById("app").innerHTML = `
<div class="screen">
  <h1 class="title" style="font-size:1.7rem">Game Created!</h1>
  <p class="subtitle">Share each player's link below, then open your own.</p>

  <div class="lobby-box">
    <p style="color:#CCAAFF;margin-bottom:14px;font-size:.9rem">
      Each player opens their own link on their own device.
      Arrangement happens simultaneously — no passing required.
    </p>
    ${player_names.map((name, i) => `
      <div class="player-link-card">
        <span class="plname">${name}</span>
        <span class="plurl" id="url${i}">${base}/game/${game_id}/${tokens[i]}</span>
        <button class="copy-btn" onclick="copyLink('url${i}', this)">Copy link</button>
      </div>`).join("")}
  </div>
</div>`;
}

function copyLink(elId, btn) {
  const url = document.getElementById(elId).textContent;
  navigator.clipboard.writeText(url).then(() => {
    btn.textContent = "Copied!";
    setTimeout(() => btn.textContent = "Copy link", 2000);
  });
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
    window.location.href = "/";
  });
}
