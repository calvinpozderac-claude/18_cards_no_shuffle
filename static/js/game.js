/* ── api helpers ─────────────────────────────────────────────────────────── */
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

/* ── global state ────────────────────────────────────────────────────────── */
let G = null;           // current game state from server
let msgTimer = null;    // clears transient success messages

/* ── entry point ─────────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", async () => {
  G = await apiGet("/api/state");
  render(G);
});

/* ── main render dispatch ─────────────────────────────────────────────────── */
function render(state) {
  G = state;
  const app = document.getElementById("app");
  if      (state.phase === "setup")       app.innerHTML = setupHTML();
  else if (state.phase === "arrangement") app.innerHTML = arrangeHTML(state);
  else if (state.phase === "game")        app.innerHTML = gameHTML(state);
  else if (state.phase === "end")         app.innerHTML = endHTML(state);
  bindAll(state);
}

function showMsg(msg, cls = "") {
  const el = document.getElementById("action-msg");
  if (!el) return;
  if (msgTimer) clearTimeout(msgTimer);
  el.textContent = msg;
  el.className = "action-msg " + cls;
  if (cls === "success") msgTimer = setTimeout(() => { el.textContent = ""; el.className = "action-msg"; }, 2500);
}

/* ── SETUP ───────────────────────────────────────────────────────────────── */
function setupHTML() {
  return `
<div class="screen">
  <h1 class="title">Don't Be the Third Wheel!</h1>
  <p class="subtitle">A romantic scheduling strategy game for 2–3 players</p>

  <div class="setup-form">
    <div class="form-group">
      <label>Number of Players</label>
      <div class="radio-group">
        <label><input type="radio" name="np" value="2" id="np2"> 2 Players</label>
        <label><input type="radio" name="np" value="3" id="np3" checked> 3 Players</label>
      </div>
    </div>
    <div class="form-group">
      <label>Player Names</label>
      <div class="name-fields">
        ${[1,2,3].map(i => `
          <div class="player-name-row" id="name-row-${i}">
            <span class="pnum">P${i}</span>
            <input class="player-name-input" id="pname${i}" placeholder="Player ${i}" value="Player ${i}" />
          </div>`).join("")}
      </div>
    </div>
    <button id="start-btn" class="btn btn-primary">▶ Start Game</button>
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
      <div class="rule-row">2 players same card on same day → 1st arrival: +1 pt,  2nd arrival: +2 pts</div>
      <div class="rule-row">3 players same card on same day → 1st: 0,  2nd: 0,  3rd (third wheel!): −1 pt</div>
      <div class="rule-row">1 player alone on a day → no points</div>
    </div>
  </div>
</div>`;
}

function bindSetup() {
  // toggle third name row based on player count
  const updateRows = () => {
    const n = +document.querySelector('input[name="np"]:checked').value;
    document.getElementById("name-row-3").style.display = n >= 3 ? "" : "none";
  };
  document.querySelectorAll('input[name="np"]').forEach(r => r.addEventListener("change", updateRows));
  updateRows();

  document.getElementById("start-btn").addEventListener("click", async () => {
    const n = +document.querySelector('input[name="np"]:checked').value;
    const names = [1, 2, 3].map(i => document.getElementById(`pname${i}`).value.trim());
    G = await apiPost("/api/setup", { num_players: n, names });
    render(G);
  });
}

/* ── ARRANGEMENT ──────────────────────────────────────────────────────────── */
function arrangeHTML(state) {
  const pidx = state.arrange_idx;
  const player = state.players[pidx];
  const total = state.players.length;

  return `
<div class="arrange-screen">
  <h1 class="title" style="font-size:1.8rem">Schedule Your Dates!</h1>
  <p class="subtitle">
    ${pidx > 0 ? `<strong style="color:#FFD700">Pass the device to ${player.name}.</strong><br>` : ""}
    Player <strong>${pidx + 1} / ${total}</strong>: <strong style="color:#FFD700">${player.name}</strong>
    — assign each location to a Day (others can't see your choices).
  </p>

  <div class="rules-box" style="max-width:500px;margin:0 auto 16px;font-size:.82rem">
    <strong style="color:#CCAAFF">How to arrange:</strong>
    Click a location card to select it, then click a Day slot to place it.
    Each location goes to exactly one day.
  </div>

  <p style="text-align:center;font-weight:700;color:#CC99FF;margin-bottom:8px">Location Cards</p>
  <div class="loc-cards" id="loc-cards">
    ${[1,2,3,4,5,6].map(ct => `
      <button class="loc-btn ct-${ct}" id="loc-${ct}"
              style="background:${LOC_COLORS[ct]};border-color:${LOC_COLORS[ct]}">
        <span class="num">${ct}</span>
        <span class="name">${LOCATION_NAMES[ct]}</span>
      </button>`).join("")}
  </div>

  <p style="text-align:center;font-weight:700;color:#CC99FF;margin:4px 0 8px">Day Slots</p>
  <div class="day-slots" id="day-slots">
    ${[1,2,3,4,5,6].map(d => `
      <div class="day-slot" id="slot-${d}">
        <span class="day-label">Day ${d}</span>
        <span class="day-ct"></span>
        <span class="day-name" style="color:#8870aa">(empty)</span>
      </div>`).join("")}
  </div>

  <p class="arrange-status" id="arr-status">Select a location card to begin.</p>
  <button id="arr-confirm" class="btn btn-primary arrange-confirm" disabled>Confirm Arrangement →</button>
</div>`;
}

function bindArrange(state) {
  let selCt = 0;
  const assigned = {};   // ct -> day
  const dayTaken = {};   // day -> ct

  function selectCt(ct) {
    if (assigned[ct]) { setStatus(`Card ${ct} is already placed on Day ${assigned[ct]}!`); return; }
    selCt = ct;
    document.querySelectorAll(".loc-btn").forEach(b => b.classList.remove("selected"));
    document.getElementById(`loc-${ct}`).classList.add("selected");
    setStatus(`Selected: ${ct} – ${LOCATION_NAMES[ct]}. Now click a Day slot.`);
  }

  function assignDay(day) {
    if (!selCt) { setStatus("Select a location card first!"); return; }
    if (assigned[selCt]) { setStatus(`Card ${selCt} is already placed!`); return; }
    if (dayTaken[day]) { setStatus(`Day ${day} already has a card! Choose another.`); return; }

    assigned[selCt] = day;
    dayTaken[day] = selCt;

    // update slot
    const slot = document.getElementById(`slot-${day}`);
    slot.classList.add("filled");
    slot.style.background = LOC_COLORS[selCt];
    slot.querySelector(".day-ct").textContent = selCt;
    slot.querySelector(".day-name").textContent = LOCATION_NAMES[selCt];
    slot.querySelector(".day-name").style.color = "";

    // disable loc button
    const locBtn = document.getElementById(`loc-${selCt}`);
    locBtn.disabled = true;
    locBtn.classList.remove("selected");

    selCt = 0;
    const remaining = 6 - Object.keys(assigned).length;
    if (remaining === 0) {
      setStatus("All cards placed! Click Confirm to continue.");
      document.getElementById("arr-confirm").disabled = false;
    } else {
      setStatus(`${remaining} card(s) still to place.`);
    }
  }

  function setStatus(msg) { document.getElementById("arr-status").textContent = msg; }

  document.querySelectorAll(".loc-btn").forEach(btn => {
    btn.addEventListener("click", () => selectCt(+btn.id.split("-")[1]));
  });
  document.querySelectorAll(".day-slot").forEach(slot => {
    slot.addEventListener("click", () => assignDay(+slot.id.split("-")[1]));
  });
  document.getElementById("arr-confirm").addEventListener("click", async () => {
    G = await apiPost("/api/arrange", { arrangement: assigned });
    render(G);
  });
}

/* ── GAME ─────────────────────────────────────────────────────────────────── */
function gameHTML(state) {
  const cur = state.current_player_idx;
  const scores = state.scores || {};

  return `
<div class="game-wrap">
  <div class="topbar">
    <span class="topbar-title">Don't Be the Third Wheel!</span>
    <span class="topbar-turn">Turn ${state.turn_count + 1} — <strong>${state.players[cur].name}</strong>'s turn</span>
    <div class="topbar-btns">
      <button class="btn btn-green" id="btn-scores">Scores</button>
      <button class="btn btn-red"   id="btn-end">End Game</button>
    </div>
  </div>

  <div class="action-strip">
    <span class="action-msg" id="action-msg">
      ${state.pending_action ? (state.action_message || "") : ""}
    </span>
    ${state.pending_action ? `<button class="btn btn-cancel" id="btn-cancel">✕ Cancel</button>` : ""}
  </div>

  <div class="board-container">
    <div class="board">
      <!-- header row -->
      <div class="board-header" style="background:transparent"></div>
      ${[1,2,3,4,5,6].map(d => `<div class="board-header">Day ${d}</div>`).join("")}

      <!-- player rows -->
      ${state.players.map((player, pi) => `
        <div class="board-player-label ${pi === cur ? "active-player" : ""}">
          ${pi === cur ? "▶ " : ""}${player.name}
        </div>
        ${player.cards.map((card, di) => cardBtnHTML(state, pi, di + 1, card)).join("")}
      `).join("")}
    </div>
  </div>

  <div class="score-strip">
    ${state.players.map(p => `
      <span class="score-item"><strong>${p.name}</strong>: ${scores[p.name] !== undefined ? (scores[p.name] >= 0 ? "+" : "") + scores[p.name] : 0} pts</span>
    `).join("")}
  </div>
</div>`;
}

function cardBtnHTML(state, pi, day, card) {
  const cur = state.current_player_idx;
  const action = state.pending_action;
  const ctx = state.action_ctx || {};

  let cls = "card-btn";
  cls += card.face_up ? ` face-up ct-${card.card_type}` : " face-down";

  if (!action) {
    // no pending action — highlight current player's flippable cards
    if (pi === cur && !card.face_up) cls += " flippable";
  } else {
    // figure out if this card is a valid target, first-selected, or dimmed
    const isOther = pi !== cur;
    const isOwn   = pi === cur;
    let valid = false;

    if (action === "flip_other_down")  valid = isOther && card.face_up;
    if (action === "flip_own_down")    valid = isOwn && card.face_up;
    if (action === "swap_other_1")     valid = isOther;
    if (action === "swap_other_2") {
      valid = pi === ctx.first_pi && day !== ctx.first_day;
      if (pi === ctx.first_pi && day === ctx.first_day) cls += " selected-first";
    }
    if (action === "swap_own_1")       valid = isOwn;
    if (action === "swap_own_2") {
      valid = isOwn && day !== ctx.first_day;
      if (isOwn && day === ctx.first_day) cls += " selected-first";
    }
    if (action === "change_arr_other") {
      const k = `${day},${card.card_type}`;
      const arr = state.arrivals ? state.arrivals[k] : [];
      valid = isOther && card.face_up && arr && arr.length >= 2;
    }
    if (action === "change_arr_own") {
      const k = `${day},${card.card_type}`;
      const arr = state.arrivals ? state.arrivals[k] : [];
      valid = isOwn && card.face_up && arr && arr.length >= 2;
    }
    if (action === "set_arrival") valid = false; // waiting for modal

    if (valid)  cls += " target-valid";
    else        cls += " dimmed";
  }

  const arrLabels = { 1: "▲ 1st", 2: "■ 2nd", 3: "▼ 3rd" };
  const arrText = card.face_up ? (arrLabels[card.arrival] || `#${card.arrival}`) : "";

  return `
<button class="card-btn ${cls}"
        data-pi="${pi}" data-day="${day}"
        ${action === "set_arrival" ? "disabled" : ""}>
  ${card.face_up ? `<span class="arr-badge">${arrText}</span>` : ""}
  <span class="card-ct">${card.face_up ? card.card_type : "?"}</span>
  <span class="card-loc">${card.face_up ? LOCATION_NAMES[card.card_type] : "face down"}</span>
</button>`;
}

function bindGame(state) {
  // card clicks
  document.querySelectorAll(".card-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const pi  = +btn.dataset.pi;
      const day = +btn.dataset.day;
      await handleCardClick(pi, day);
    });
  });

  document.getElementById("btn-cancel")?.addEventListener("click", async () => {
    G = await apiPost("/api/cancel");
    render(G);
  });

  document.getElementById("btn-scores").addEventListener("click", () => showScoresModal(G));
  document.getElementById("btn-end").addEventListener("click", async () => {
    if (confirm("End the game now and see final scores?")) {
      G = await apiPost("/api/end_game");
      render(G);
    }
  });
}

async function handleCardClick(pi, day) {
  if (G.pending_action) {
    // send as action target
    const resp = await apiPost("/api/action", { player_idx: pi, day });
    const result = resp.action_result || {};
    if (result.error) {
      showMsg(result.error, "error");
      return;  // don't re-render — keep current state
    }
    if (result.needs_position && result.arrival_info) {
      // store partial state then show modal
      G = resp;
      render(G);
      showArrivalModal(result.arrival_info);
      return;
    }
    if (result.message) showMsg(result.message, "success");
    G = resp;
    render(G);
    if (result.message) showMsg(result.message, "success");
  } else {
    // normal flip
    if (pi !== G.current_player_idx) {
      showMsg(`It's ${G.players[G.current_player_idx].name}'s turn!`, "error");
      return;
    }
    const card = G.players[pi].cards[day - 1];
    if (card.face_up) { showMsg("That card is already face up.", "error"); return; }
    G = await apiPost("/api/flip", { day });
    render(G);
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
    const label = document.createElement("label");
    label.className = "modal-radio";
    label.innerHTML = `<input type="radio" name="arrival" value="${i}" ${i === info.current ? "checked" : ""}> ${labels[i] || `#${i}`}`;
    opts.appendChild(label);
  }

  document.getElementById("modal-overlay").classList.remove("hidden");

  document.getElementById("modal-confirm").onclick = async () => {
    const sel = document.querySelector('input[name="arrival"]:checked');
    if (!sel) return;
    closeModal();
    const resp = await apiPost("/api/set_arrival", { new_pos: +sel.value });
    const result = resp.action_result || {};
    G = resp;
    render(G);
    if (result.message) showMsg(result.message, "success");
  };
  document.getElementById("modal-cancel").onclick = async () => {
    closeModal();
    G = await apiPost("/api/cancel");
    render(G);
  };
}

function showScoresModal(state) {
  const scores = state.scores || {};
  const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const arrivals = state.arrivals_display || [];

  document.getElementById("modal-title").textContent = "Current Scores";
  document.getElementById("modal-sub").textContent = "";

  const opts = document.getElementById("modal-options");
  opts.innerHTML = `
    <div style="margin-bottom:14px">
      ${ranked.map(([name, pts]) =>
        `<div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #2a1a4a">
          <span>${name}</span>
          <strong style="color:${pts >= 0 ? "#80FF80" : "#FF8080"}">${pts >= 0 ? "+" : ""}${pts} pts</strong>
        </div>`
      ).join("")}
    </div>
    <div style="font-size:.8rem;color:#CCAAFF;font-weight:700;margin-bottom:6px">Breakdown:</div>
    ${arrivals.map(r => {
      const note = r.n === 1 ? "solo" : r.n === 2 ? "1st+1, 2nd+2" : "3rd −1";
      return `<div style="font-size:.78rem;color:#CCCCFF;padding:2px 0">
        Day ${r.day} – ${r.location}: ${r.players.join(" → ")} [${note}]
      </div>`;
    }).join("")}`;

  document.getElementById("modal-overlay").classList.remove("hidden");
  document.getElementById("modal-confirm").style.display = "none";
  document.getElementById("modal-cancel").textContent = "Close";
  document.getElementById("modal-cancel").onclick = () => {
    closeModal();
    document.getElementById("modal-confirm").style.display = "";
    document.getElementById("modal-cancel").textContent = "Cancel";
  };
}

function closeModal() {
  document.getElementById("modal-overlay").classList.add("hidden");
}

/* ── END ─────────────────────────────────────────────────────────────────── */
function endHTML(state) {
  const scores  = state.scores || {};
  const ranked  = Object.entries(scores).sort((a, b) => b[1] - a[1]);
  const medals  = ["🥇", "🥈", "🥉"];
  const arrivals = state.arrivals_display || [];

  return `
<div class="end-screen">
  <h1>Game Over!</h1>
  <div class="podium">
    ${ranked.map(([name, pts], i) => `
      <div class="podium-row ${i === 0 ? "rank-1" : ""}">
        <span class="podium-medal">${medals[i] || `#${i + 1}`}</span>
        <span class="podium-name">${name}</span>
        <span class="podium-score">${pts >= 0 ? "+" : ""}${pts} pts</span>
      </div>`).join("")}
  </div>

  <div class="breakdown">
    <h3>Date Results</h3>
    ${arrivals.map(r => {
      let note, cls;
      if (r.n === 1)      { note = "solo — no points";            cls = "neutral"; }
      else if (r.n === 2) { note = "1st: +1 pt,  2nd: +2 pts";   cls = "good"; }
      else                { note = "3rd wheel: −1 pt";             cls = "bad"; }
      return `<div class="breakdown-row">
        <span class="bday">Day ${r.day}</span>
        <span class="bloc">${r.location}</span>
        <span class="bplrs">${r.players.join(" → ")}</span>
        <span class="bscore ${cls}">${note}</span>
      </div>`;
    }).join("")}
  </div>

  <button id="play-again" class="btn btn-primary">▶ Play Again</button>
</div>`;
}

function bindEnd() {
  document.getElementById("play-again").addEventListener("click", async () => {
    G = await apiPost("/api/reset");
    render(G);
  });
}

/* ── bind all events for current phase ───────────────────────────────────── */
function bindAll(state) {
  if      (state.phase === "setup")       bindSetup();
  else if (state.phase === "arrangement") bindArrange(state);
  else if (state.phase === "game")        bindGame(state);
  else if (state.phase === "end")         bindEnd();

  // modal overlay close on bg click (only for scores modal)
  document.getElementById("modal-overlay").addEventListener("click", e => {
    if (e.target === document.getElementById("modal-overlay")) {
      const cancelBtn = document.getElementById("modal-cancel");
      if (cancelBtn) cancelBtn.click();
    }
  });
}
