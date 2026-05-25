/* ── global state ──────────────────────────────────────────────────────────── */
let gs = null;   // server game state
let ls = {       // local UI selections
  uiStep:           "idle",    // idle | pick_dest | pick_action
  selectedCard:     null,
  selectedDest:     null,
  switchFirst:      null,      // first stack id for switch_piles action
  swapStack:        null,      // stack index chosen for swap_order action
  swapFirst:        null,      // first play index for swap_order action
  dateHandoffDone:  false,
  showTargetDone:   false,
  peekChosen:       false,
};

/* ── API helpers ───────────────────────────────────────────────────────────── */
async function api(path, body) {
  const opts = body != null
    ? { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body) }
    : { method: "GET" };
  const res  = await fetch(path, opts);
  const data = await res.json();
  if (data.error) { showToast("⚠ " + data.error); return null; }
  gs = data;
  render();
  return data;
}

function showToast(msg) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("visible");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("visible"), 3000);
}

/* ── colour helpers ────────────────────────────────────────────────────────── */
function pc(pi)    { return gs.player_colors[pi]; }
function plt(pi)   { return gs.player_light[pi]; }
function pname(pi) { return gs.players[pi].name; }

/* ── main render ───────────────────────────────────────────────────────────── */
function render() {
  const app = document.getElementById("app");
  if (!gs || gs.phase === "setup") {
    app.innerHTML = renderSetup();
    bindSetup();
    return;
  }
  if (gs.phase === "card_playing") {
    app.innerHTML = renderCardPlaying();
    bindCardPlaying();
    return;
  }
  if (gs.phase === "date_phase") {
    app.innerHTML = renderDatePhase();
    bindDatePhase();
    return;
  }
  if (gs.phase === "end") {
    app.innerHTML = renderEnd();
    return;
  }
}

/* ══ SETUP ═════════════════════════════════════════════════════════════════════ */
function renderSetup() {
  const colors = ["#E05555", "#5578E0", "#3DC470"];
  const fields = [0, 1, 2].map(i => `
    <div class="field-row">
      <label>Player ${i + 1}</label>
      <div class="swatch" style="background:${colors[i]}"></div>
      <input id="name${i}" type="text" placeholder="Player ${i + 1}" maxlength="18" />
    </div>`).join("");

  return `
  <div id="setup">
    <div class="title" style="font-size:1.5rem">💔 Don't Be The Third Wheel!</div>
    <div class="subtitle">A game of dates, strategy &amp; sabotage — 3 players</div>
    ${fields}
    <div style="text-align:center;margin-top:20px">
      <button class="btn btn-primary" id="btn-start">▶ Start Game</button>
    </div>
  </div>
  <div id="toast"></div>
  ${renderCardRef()}`;
}

function bindSetup() {
  const btn = document.getElementById("btn-start");
  if (!btn || btn._bound) return;
  btn._bound = true;
  btn.onclick = async () => {
    const names = [0, 1, 2].map(i => {
      const el = document.getElementById("name" + i);
      return el ? el.value.trim() || `Player ${i + 1}` : `Player ${i + 1}`;
    });
    resetLocalState();
    await api("/api/setup", { names });
  };
}

function resetLocalState() {
  ls = { uiStep: "idle", selectedCard: null, selectedDest: null,
         switchFirst: null, swapStack: null, swapFirst: null,
         dateHandoffDone: false, showTargetDone: false, peekChosen: false };
}

/* ══ CARD PLAYING ══════════════════════════════════════════════════════════════ */
function renderCardPlaying() {
  const cpidx   = gs.current_player_idx;
  const pending = gs.pending_action;

  let instruction;
  if (pending) {
    instruction = gs.action_message || "Resolve the pending action.";
  } else if (ls.uiStep === "pick_dest") {
    instruction = `Card ${ls.selectedCard} selected — click a pile to play it there, or use the ＋ buttons to start a new pile.`;
  } else if (ls.uiStep === "pick_action") {
    instruction = `Card ${ls.selectedCard} chosen for this pile — use the action or skip it?`;
  } else {
    instruction = `${pname(cpidx)}'s turn — pick a card from your hand below.`;
  }

  const canNew = canCreateNew();

  return `
  <div class="screen">
    <div class="title" style="font-size:1.3rem;margin-bottom:6px">Don't Be The Third Wheel!</div>
    ${renderStatusBar()}
    <div id="msg-bar">${instruction}</div>

    <div id="stacks-area">
      <div class="new-stack-btn${canNew ? "" : " unavailable"}" id="btn-new-left">＋</div>
      ${gs.stacks.map((s, si) => renderStackCol(s, si, pending, cpidx)).join("")}
      <div class="new-stack-btn${canNew ? "" : " unavailable"}" id="btn-new-right">＋</div>
    </div>

    ${pending ? "" : renderHandArea(cpidx)}
    ${renderActionPanel(pending, cpidx)}
    <div id="toast"></div>
    ${renderCardRef()}
  </div>`;
}

function canCreateNew() {
  if (gs.stacks.length >= 6) return false;
  if (gs.pending_action)      return false;
  if (ls.uiStep === "pick_action") return false;
  return true;
}

function getPlayedCards(pidx) {
  const cards = [];
  gs.stacks.forEach(s => s.plays.forEach(p => { if (p.player_idx === pidx) cards.push(p.card_num); }));
  return cards;
}

function twPosAtDate(di) {
  if (di < 2) return 2;
  if (di < 4) return 1;
  return 0;
}

/* ── stack column ─────────────────────────────────────────────────────────── */
function renderStackCol(stack, si, pending, cpidx) {
  const playedIds = gs.players[cpidx].cards_played_to || [];
  let cls = "stack-col";

  if (!pending && ls.uiStep === "pick_dest" && !playedIds.includes(stack.id)) {
    cls += " selectable";
  }
  if (pending === "switch_piles") {
    if (ls.switchFirst === null || ls.switchFirst !== stack.id) cls += " selectable";
    if (ls.switchFirst === stack.id) cls += " selected-1";
  }
  if (pending === "swap_order" && ls.swapStack === null && stack.plays.length >= 2) {
    cls += " swap-target selectable";
  }
  if (pending === "swap_order" && ls.swapStack === si) {
    cls += " swap-target";
  }

  const twPos = twPosAtDate(si);
  let twNote;
  if (stack.plays.length === 3) {
    twNote = `<span class="tw-badge">${pname(stack.plays[twPos].player_idx).substring(0,6)} = 3W</span>`;
  } else {
    const lbl = ["3rd=3W","2nd=3W","1st=3W"][twPos];
    twNote = `<span class="tw-badge future">${lbl}</span>`;
  }

  const playsHtml   = stack.plays.map((p, pi) => renderPlayCard(p, pi, si, pending, cpidx, twPos)).join("");
  const emptySlots  = 3 - stack.plays.length;
  const emptyHtml   = Array.from({length: emptySlots}, () =>
    `<div class="play-card" style="background:#1e1030;border:1px dashed #2e1a50;min-height:42px;opacity:.4">
       <div class="play-card-sub" style="text-align:center;color:#553388">— empty —</div>
     </div>`).join("");

  return `
  <div class="${cls}" data-stack-id="${stack.id}" data-stack-idx="${si}">
    <div class="stack-header">Pile ${si + 1} ${twNote}</div>
    ${playsHtml}${emptyHtml}
  </div>`;
}

function renderPlayCard(play, pi, si, pending, cpidx, twPos) {
  const bg     = plt(play.player_idx);
  const info   = gs.card_info[play.card_num];
  const active = play.modifier_active;
  const mType  = active ? (info.type === "bonus" ? "bonus" : "debuff") : "off";
  const mLabel = active
    ? (info.type === "bonus" ? "✓ Bonus" : "✗ Debuff")
    : (info.type === "bonus" ? "✕ Bonus off" : "✓ Debuff off");
  const arrLbl = ["1st","2nd","3rd"][pi];
  const isTW   = pi === twPos;

  let cls = "play-card";
  if (pending === "swap_order" && si === ls.swapStack) {
    cls += " selectable";
    if (ls.swapFirst === pi) cls += " selected-swap1";
  }
  if (pending === "deact_act" && play.player_idx !== cpidx && !play.used_action) {
    cls += " deact-target";
  }

  return `
  <div class="${cls}" style="background:${bg}" data-si="${si}" data-pi="${pi}">
    ${isTW ? `<div class="tw-play-badge">3W</div>` : ""}
    <span class="arrival-badge">${arrLbl}</span>
    <div class="play-card-inner">${pname(play.player_idx).substring(0,8)} · C${play.card_num}</div>
    <div class="play-card-sub">${play.used_action ? "⚡ Action" : "○ Skipped"}</div>
    <div class="modifier-tag ${mType}">${mLabel}</div>
  </div>`;
}

/* ── hand area ─────────────────────────────────────────────────────────────── */
function renderHandArea(cpidx) {
  const played   = getPlayedCards(cpidx);
  const disabled = ls.uiStep === "pick_dest" || ls.uiStep === "pick_action";

  const cards = [1,2,3,4,5,6].map(cn => {
    const info    = gs.card_info[cn];
    const isPlayed = played.includes(cn);
    const isSel   = ls.selectedCard === cn;
    let cls = "hand-card";
    if (isPlayed)               cls += " played";
    if (isSel)                  cls += " selected";
    if (disabled && !isPlayed && !isSel) cls += " disabled";
    const mCls = info.type === "bonus" ? "bonus" : "debuff";
    return `
    <div class="${cls}" data-card="${cn}" style="background:${plt(cpidx)}">
      <div class="hand-card-type">${info.type.toUpperCase()}</div>
      <div class="hand-card-num">${cn}</div>
      <div class="hand-card-action">${info.action}</div>
      <div class="hand-card-mod ${mCls}">${info.type === "bonus" ? "B: " : "D: "}${info.modifier}</div>
    </div>`;
  }).join("");

  return `
  <div id="hand-area">
    <h3 style="color:${pc(cpidx)}">${pname(cpidx)}'s Hand</h3>
    <div class="hand-cards">${cards}</div>
  </div>`;
}

/* ── action panel ─────────────────────────────────────────────────────────── */
function renderActionPanel(pending, cpidx) {
  if (pending) {
    return `
    <div id="action-panel">
      <h3>Resolve Action</h3>
      <p style="color:#BBAACC;margin-bottom:12px">${gs.action_message || ""}</p>
      <button class="btn btn-cancel" id="btn-cancel-action">Skip / Cancel</button>
    </div>`;
  }

  if (ls.uiStep === "pick_action") {
    const info    = gs.card_info[ls.selectedCard];
    const isBonus = info.type === "bonus";
    return `
    <div id="action-panel">
      <h3>Card ${ls.selectedCard} — How to play?</h3>
      <div class="action-choices">
        <div class="action-choice-card use" id="btn-use-action">
          <div class="choice-label">⚡ Use the Action</div>
          <div class="choice-desc">
            <b>${info.action}</b><br>
            <span style="color:#FF9090">${isBonus ? "Bonus forfeited: " + info.modifier : "Debuff activated: " + info.modifier}</span>
          </div>
        </div>
        <div class="action-choice-card skip" id="btn-skip-action">
          <div class="choice-label">○ Skip the Action</div>
          <div class="choice-desc">
            <b>No action.</b><br>
            <span style="color:${isBonus ? "#88FFAA" : "#FFAA88"}">${isBonus ? "Bonus kept: " + info.modifier : "Debuff avoided: " + info.modifier}</span>
          </div>
        </div>
      </div>
      <div style="margin-top:10px">
        <button class="btn btn-ghost btn-sm" id="btn-back-dest">← Back</button>
      </div>
    </div>`;
  }

  return "";
}

/* ── status bar ─────────────────────────────────────────────────────────────── */
function renderStatusBar() {
  const cpidx  = gs.current_player_idx;
  const played = gs.stacks.reduce((a, s) => a + s.plays.length, 0);
  const tags   = gs.players.map((p, i) =>
    `<span class="player-tag" style="border:1.5px solid ${i === cpidx ? pc(i) : "transparent"}">
      <span class="dot" style="background:${pc(i)}"></span>${p.name}
    </span>`).join("");

  return `
  <div id="status-bar">
    <span id="turn-label" style="color:${pc(cpidx)}">${pname(cpidx)}'s Turn</span>
    ${tags}
    <span style="margin-left:auto;font-size:.8rem;color:#665588">${played}/18 cards</span>
  </div>`;
}

/* ── bind card playing ─────────────────────────────────────────────────────── */
function bindCardPlaying() {
  const pending = gs.pending_action;
  const cpidx   = gs.current_player_idx;
  const canNew  = canCreateNew();

  // new pile buttons
  if (canNew && ls.uiStep === "pick_dest") {
    const btnL = document.getElementById("btn-new-left");
    const btnR = document.getElementById("btn-new-right");
    if (btnL) btnL.onclick = () => handleDestSelect("new_left");
    if (btnR) btnR.onclick = () => handleDestSelect("new_right");
  }

  // hand card clicks
  document.querySelectorAll(".hand-card:not(.played):not(.disabled)").forEach(el => {
    el.addEventListener("click", () => {
      if (ls.uiStep === "pick_dest" || ls.uiStep === "pick_action") return;
      const cn = parseInt(el.dataset.card);
      ls.selectedCard = (ls.selectedCard === cn) ? null : cn;
      ls.uiStep       = ls.selectedCard ? "pick_dest" : "idle";
      ls.selectedDest = null;
      render();
    });
  });

  // stack clicks
  document.querySelectorAll(".stack-col").forEach(col => {
    col.addEventListener("click", (e) => {
      if (e.target.closest(".play-card")) return;
      const sid = parseInt(col.dataset.stackId);
      const si  = parseInt(col.dataset.stackIdx);

      if (!pending && ls.uiStep === "pick_dest") {
        const playedIds = gs.players[cpidx].cards_played_to || [];
        if (!playedIds.includes(sid)) handleDestSelect(sid);
        return;
      }
      if (pending === "switch_piles") { handleSwitchClick(sid); return; }
      if (pending === "swap_order" && ls.swapStack === null && col.classList.contains("swap-target")) {
        ls.swapStack = si; render(); return;
      }
    });
  });

  // play card clicks (within stacks)
  document.querySelectorAll(".play-card").forEach(el => {
    el.addEventListener("click", (e) => {
      e.stopPropagation();
      const si = parseInt(el.dataset.si);
      const pi = parseInt(el.dataset.pi);
      if (pending === "swap_order" && si === ls.swapStack) { handleSwapClick(si, pi); return; }
      if (pending === "deact_act" && el.classList.contains("deact-target")) { handleDeactClick(si, pi); return; }
    });
  });

  // action / skip
  const btnUse  = document.getElementById("btn-use-action");
  const btnSkip = document.getElementById("btn-skip-action");
  const btnBack = document.getElementById("btn-back-dest");
  if (btnUse)  btnUse.onclick  = () => submitPlayCard(true);
  if (btnSkip) btnSkip.onclick = () => submitPlayCard(false);
  if (btnBack) btnBack.onclick = () => { ls.uiStep = "pick_dest"; ls.selectedDest = null; render(); };

  // cancel action
  const btnCancel = document.getElementById("btn-cancel-action");
  if (btnCancel) btnCancel.onclick = () => {
    ls.switchFirst = null; ls.swapStack = null; ls.swapFirst = null;
    api("/api/cancel_action", {});
  };
}

function handleDestSelect(dest) {
  if (ls.uiStep !== "pick_dest" || ls.selectedCard === null) return;
  ls.selectedDest = dest;
  ls.uiStep       = "pick_action";
  render();
}

async function submitPlayCard(useAction) {
  if (ls.selectedCard === null || ls.selectedDest === null) return;
  const body = { card_num: ls.selectedCard, stack_target: ls.selectedDest, use_action: useAction };
  ls.selectedCard = null; ls.selectedDest = null; ls.uiStep = "idle";
  ls.switchFirst = null;  ls.swapStack = null;    ls.swapFirst = null;
  await api("/api/play_card", body);
}

function handleSwitchClick(sid) {
  if (ls.switchFirst === null)      { ls.switchFirst = sid; render(); }
  else if (ls.switchFirst === sid)  { ls.switchFirst = null; render(); }
  else {
    const id1 = ls.switchFirst; ls.switchFirst = null;
    api("/api/resolve_action", { stack1_id: id1, stack2_id: sid });
  }
}

function handleSwapClick(si, pi) {
  if (ls.swapFirst === null)       { ls.swapFirst = pi; render(); }
  else if (ls.swapFirst === pi)    { ls.swapFirst = null; render(); }
  else {
    const p1 = ls.swapFirst; ls.swapStack = null; ls.swapFirst = null;
    api("/api/resolve_action", { stack_idx: si, play_idx1: p1, play_idx2: pi });
  }
}

function handleDeactClick(si, pi) {
  api("/api/resolve_action", { stack_idx: si, play_idx: pi });
}

/* ══ DATE PHASE ════════════════════════════════════════════════════════════════ */
function renderDatePhase() {
  const di    = gs.date_phase_idx;
  const stack = gs.stacks[di];
  const count = gs.date_submitted_count;
  const order = gs.date_submission_order;

  if (stack.date_resolved || count >= 3) {
    return `<div class="screen">${renderRevealScreen(di)}<div id="toast"></div></div>`;
  }

  const submitter = order[count];
  const peek      = gs.date_peek_info;
  const show      = gs.date_show_info;

  if (!ls.dateHandoffDone) {
    return `<div class="screen">${renderHandoffScreen(submitter, di)}<div id="toast"></div></div>`;
  }
  if (show && show.player === submitter && show.reveal_to === null && !ls.showTargetDone) {
    return `<div class="screen">${renderShowTargetScreen(submitter, di)}<div id="toast"></div></div>`;
  }
  if (peek && peek.player === submitter && peek.peek_target === null) {
    return `<div class="screen">${renderPeekSelectScreen(submitter, di)}<div id="toast"></div></div>`;
  }
  if (peek && peek.player === submitter && peek.peek_target !== null && !ls.peekChosen) {
    const peekedMove = stack.date_moves[String(peek.peek_target)];
    return `<div class="screen">${renderPeekScreen(submitter, peek.peek_target, peekedMove, di)}<div id="toast"></div></div>`;
  }
  return `<div class="screen">${renderMoveScreen(submitter, di)}<div id="toast"></div></div>`;
}

function renderHandoffScreen(pidx, di) {
  const peek = gs.date_peek_info;
  const show = gs.date_show_info;
  let note = "";
  if (show && show.player === pidx)
    note = `<p style="color:#FF9090;margin-bottom:8px">⚠ You have the <b>SHOW debuff</b> — you'll choose who sees your move first.</p>`;
  if (peek && peek.player === pidx)
    note = `<p style="color:#AA88FF;margin-bottom:8px">✦ You have the <b>PEEK bonus</b> — you'll see one other player's choice before deciding.</p>`;

  return `
  <div class="handoff-screen">
    <div style="font-size:2.2rem">📱</div>
    <div class="player-name-big" style="color:${pc(pidx)}">${pname(pidx)}</div>
    <p>Pass the device to <b>${pname(pidx)}</b>.<br>Everyone else — look away!</p>
    ${note}
    ${renderDateInfoCompact(di)}
    <br>
    <button class="btn btn-primary" id="btn-handoff-confirm">I'm ${pname(pidx)} — Ready ▶</button>
  </div>`;
}

function renderShowTargetScreen(pidx, di) {
  const others = gs.players.map((p, i) => i).filter(i => i !== pidx);
  const btns   = others.map(i =>
    `<button class="btn" data-target="${i}" id="show-tgt-${i}"
      style="background:${pc(i)};color:#fff;margin:6px">
      Reveal to ${pname(i)}
    </button>`).join("");
  return `
  <div class="move-screen">
    <div class="date-info-box">
      <div class="date-num">Date ${di + 1} — Show Debuff</div>
      <p style="margin-top:8px;color:#FF9090">⚠ <b>Card 6 Debuff:</b> Before choosing your move, reveal your choice to one player (honor system).</p>
      <p style="margin-top:8px;color:#BBAACC">Who will see your move first?</p>
      <div style="margin-top:10px">${btns}</div>
    </div>
  </div>`;
}

function renderPeekSelectScreen(pidx, di) {
  const order   = gs.date_submission_order;
  const already = order.slice(0, gs.date_submitted_count);
  if (already.length === 0) return renderMoveScreen(pidx, di);
  const btns = already.map(i =>
    `<button class="btn btn-blue" data-peek="${i}" id="peek-sel-${i}" style="margin:6px">
      Peek at ${pname(i)}'s move
    </button>`).join("");
  return `
  <div class="move-screen">
    <div class="date-info-box">
      <div class="date-num">Date ${di + 1} — Peek Bonus</div>
      <p style="margin-top:8px;color:#AA88FF">✦ <b>Card 3 Bonus:</b> Choose one player's move to peek at before you decide.</p>
      <div style="margin-top:10px">${btns}</div>
    </div>
  </div>`;
}

function renderPeekScreen(pidx, peekTarget, peekedMove, di) {
  const mLabel = peekedMove === "MM"
    ? `<span style="color:#6699FF;font-size:1.5rem;font-weight:900">💘 Make a Move (MM)</span>`
    : `<span style="color:#66CC88;font-size:1.5rem;font-weight:900">🛡 Play it Safe (PS)</span>`;
  return `
  <div class="move-screen">
    <div class="date-info-box">
      <div class="date-num">Date ${di + 1} — Peeking</div>
      <p style="margin-top:8px;color:#AA88FF">You peeked at <b style="color:${pc(peekTarget)}">${pname(peekTarget)}</b>'s move:</p>
      <div style="text-align:center;margin:16px 0">${mLabel}</div>
      <div style="text-align:center">
        <button class="btn btn-primary" id="btn-after-peek">Continue to choose →</button>
      </div>
    </div>
  </div>`;
}

function renderMoveScreen(pidx, di) {
  const show = gs.date_show_info;
  let showNote = "";
  if (show && show.player === pidx && show.reveal_to !== null) {
    showNote = `<p style="color:#FF9090;margin-bottom:10px">⚠ Remember: show your choice to <b style="color:${pc(show.reveal_to)}">${pname(show.reveal_to)}</b> before they see the reveal!</p>`;
  }
  return `
  <div class="move-screen">
    ${renderDateInfoCompact(di)}
    ${showNote}
    <p style="text-align:center;color:#BBAACC;margin-bottom:6px">
      What will <b style="color:${pc(pidx)}">${pname(pidx)}</b> do?
    </p>
    <div class="move-choices">
      <button class="btn btn-mm" id="btn-mm" data-pidx="${pidx}">💘 Make a Move<br><span style="font-size:.75rem;font-weight:500">(MM)</span></button>
      <button class="btn btn-ps" id="btn-ps" data-pidx="${pidx}">🛡 Play it Safe<br><span style="font-size:.75rem;font-weight:500">(PS)</span></button>
    </div>
  </div>`;
}

function renderRevealScreen(di) {
  const stack  = gs.stacks[di];
  const plays  = stack.plays;
  const twPos  = twPosAtDate(di);
  const scores = stack.date_scores || {};
  const moves  = stack.date_moves  || {};

  const rows = plays.map((p, i) => {
    const isTW = (i === twPos);
    const move = moves[String(p.player_idx)] || "?";
    const sc   = scores[String(p.player_idx)];
    const scTxt = sc != null
      ? `<span class="${sc >= 0 ? "score-pos" : "score-neg"}">${sc >= 0 ? "+" : ""}${sc}</span>`
      : "";
    return `<tr class="${isTW ? "tw-row" : ""}">
      <td><span class="dot" style="background:${pc(p.player_idx)};display:inline-block"></span>
        ${pname(p.player_idx)} ${isTW ? '<span class="tw-indicator">👀3W</span>' : ""}
      </td>
      <td>${["1st","2nd","3rd"][i]}</td>
      <td class="move-${move.toLowerCase()}">${move === "MM" ? "💘 MM" : "🛡 PS"}</td>
      <td>${scTxt}</td>
    </tr>`;
  }).join("");

  const modHtml   = renderDateModifiers(di);
  const nextDi    = di + 1;
  const btnLabel  = nextDi < 6 ? `Next Date (${nextDi + 1}) →` : "View Final Scores →";
  const btnCls    = nextDi < 6 ? "btn-primary" : "btn-gold";

  return `
  <div class="reveal-screen">
    <h2 style="text-align:center">Date ${di + 1} Results</h2>
    ${modHtml}
    <table class="reveal-table">
      <thead><tr><th>Player</th><th>Arrival</th><th>Move</th><th>Score</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div style="padding:8px 12px;background:#1a0c2e;border-radius:8px;font-size:.85rem;color:#BBAACC;margin:10px 0">
      Running totals: ${gs.players.map((p, i) =>
        `<span style="color:${pc(i)}">${p.name}: ${gs.total_scores[i] >= 0 ? "+" : ""}${gs.total_scores[i]}</span>`
      ).join(" · ")}
    </div>
    <div style="text-align:center;margin-top:14px">
      <button class="btn ${btnCls}" id="btn-next-date">${btnLabel}</button>
    </div>
  </div>`;
}

function renderDateInfoCompact(di) {
  const stack  = gs.stacks[di];
  const plays  = stack.plays;
  const twPos  = twPosAtDate(di);
  const tw     = plays[twPos];
  const mods   = renderDateModifiers(di);
  return `
  <div class="date-info-box" style="margin-bottom:12px">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
      <span class="date-num">Date ${di + 1}</span>
      <span class="tw-label">3rd Wheel: ${tw ? pname(tw.player_idx) : "?"}</span>
    </div>
    <div style="font-size:.82rem;color:#BBAACC">
      ${plays.map((p, i) =>
        `<span style="color:${pc(p.player_idx)};margin-right:10px">
          ${["1st","2nd","3rd"][i]}: ${pname(p.player_idx)}${i === twPos ? " 👀" : ""}
        </span>`).join("")}
    </div>
    ${mods}
  </div>`;
}

function renderDateModifiers(di) {
  const plays = gs.stacks[di].plays;
  const items = plays.filter(p => p.modifier_active).map(p => {
    const info = gs.card_info[p.card_num];
    const cls  = info.type === "bonus" ? "active-bonus" : "active-debuff";
    return `<div class="modifier-item ${cls}">
      ${info.type === "bonus" ? "✓" : "✗"}
      <b style="color:${pc(p.player_idx)}">${pname(p.player_idx)}</b>
      Card ${p.card_num}: ${info.modifier}
    </div>`;
  });
  return items.length ? `<div class="modifier-list">${items.join("")}</div>` : "";
}

function bindDatePhase() {
  const btnNext = document.getElementById("btn-next-date");
  if (btnNext) {
    btnNext.onclick = () => {
      ls.dateHandoffDone = false;
      ls.showTargetDone  = false;
      ls.peekChosen      = false;
      render();
    };
    return;
  }

  const btnHandoff = document.getElementById("btn-handoff-confirm");
  if (btnHandoff) {
    btnHandoff.onclick = () => { ls.dateHandoffDone = true; render(); };
    return;
  }

  // Show target buttons
  document.querySelectorAll("[id^='show-tgt-']").forEach(btn => {
    btn.onclick = async () => {
      const target = parseInt(btn.dataset.target);
      await api("/api/set_show_target", { target_player: target });
      ls.showTargetDone = true;
    };
  });

  // Peek select buttons
  document.querySelectorAll("[id^='peek-sel-']").forEach(btn => {
    btn.onclick = async () => {
      await api("/api/set_peek_target", { target_player: parseInt(btn.dataset.peek) });
    };
  });

  const btnAfterPeek = document.getElementById("btn-after-peek");
  if (btnAfterPeek) {
    btnAfterPeek.onclick = () => { ls.peekChosen = true; render(); };
    return;
  }

  // Move buttons
  ["btn-mm","btn-ps"].forEach(id => {
    const btn = document.getElementById(id);
    if (!btn) return;
    btn.onclick = async () => {
      const pidx = parseInt(btn.dataset.pidx);
      const move = id === "btn-mm" ? "MM" : "PS";
      ls.dateHandoffDone = false;
      ls.showTargetDone  = false;
      ls.peekChosen      = false;
      await api("/api/submit_move", { player_idx: pidx, move });
    };
  });
}

/* ══ END SCREEN ════════════════════════════════════════════════════════════════ */
function renderEnd() {
  const finals = gs.final_scores || gs.total_scores;
  const ranked = gs.players.map((p, i) => ({name: p.name, score: finals[i], idx: i}))
                  .sort((a, b) => b.score - a.score);
  const medals  = ["🥇","🥈","🥉"];
  const places  = ["first","second","third"];

  const podium = ranked.map((r, rank) => `
    <div class="podium-row ${places[rank] || ""}">
      <span class="podium-medal">${medals[rank] || "#" + (rank+1)}</span>
      <span class="podium-name" style="color:${pc(r.idx)}">${r.name}</span>
      <span class="podium-score">${r.score >= 0 ? "+" : ""}${r.score}</span>
    </div>`).join("");

  const dateRows = gs.stacks.map((s, di) => {
    const sc    = s.date_scores || {};
    const twIdx = s.plays[twPosAtDate(di)]?.player_idx;
    const cells = gs.players.map((p, i) => {
      const v = sc[String(i)];
      return `<span style="color:${pc(i)}">${v != null ? (v >= 0 ? "+" : "") + v : "—"}</span>`;
    }).join(" / ");
    return `<div class="breakdown-row">
      <span style="color:#998ABB;min-width:56px">Date ${di+1}</span>
      <span style="flex:1">${cells}</span>
      ${twIdx != null ? `<span style="color:#FF8888;font-size:.75rem">3W:${pname(twIdx)}</span>` : ""}
    </div>`;
  }).join("");

  const modRows = gs.stacks.flatMap((s, di) =>
    s.plays.filter(p => p.modifier_active && (p.card_num === 1 || p.card_num === 4))
      .map(p => {
        const plus = p.card_num === 1;
        return `<div class="breakdown-row">
          <span style="color:${pc(p.player_idx)}">${pname(p.player_idx)}</span>
          <span style="flex:1">Card ${p.card_num} ${plus ? "Bonus" : "Debuff"} (Pile ${di+1})</span>
          <span style="color:${plus ? "#88FFCC" : "#FF8888"}">${plus ? "+1" : "−1"}</span>
        </div>`;
      })
  ).join("");

  return `
  <div class="screen">
    <div id="end-screen">
      <div class="title">💔 Game Over!</div>
      <div class="subtitle">Final standings</div>
      <div class="podium">${podium}</div>
      <div class="score-breakdown">
        <h3>Score Breakdown</h3>
        ${dateRows}
        ${modRows || ""}
      </div>
      <div style="text-align:center;margin-top:20px">
        <button class="btn btn-primary" id="btn-play-again">▶ Play Again</button>
      </div>
    </div>
    <div id="toast"></div>
    ${renderCardRef()}
  </div>`;
}

/* ══ CARD REFERENCE ════════════════════════════════════════════════════════════ */
function renderCardRef() {
  if (!gs || !gs.card_info) return '<div id="toast"></div>';
  const light = gs.player_light ? gs.player_light[0] : "#FFCCCC";

  const rows = [1,2,3,4,5,6].map(n => {
    const info  = gs.card_info[n];
    const bonus = info.type === "bonus";
    return `<div class="ref-card-row">
      <div class="ref-card-chip" style="background:${light}">C${n}</div>
      <div class="ref-text">
        <span>${info.action}</span> ·
        <span style="color:${bonus ? "#88FFAA" : "#FF9090"}">${info.modifier}</span>
      </div>
    </div>`;
  }).join("");

  return `
  <details id="ref-panel" style="margin-top:14px">
    <summary>📋 Card & Scoring Reference</summary>
    <div class="ref-section">${rows}</div>
    <div class="ref-section" style="margin-top:8px">
      <h4>Date Scoring Matrix (Third Wheel · Normal · Normal)</h4>
      <div class="scoring-grid">
        <div class="sh">TW</div><div class="sh">N1</div><div class="sh">N2</div><div class="sh">TW/N1/N2</div>
        <div class="sl">PS</div><div class="sl">PS</div><div class="sl">PS</div><div class="sr">0 / +1 / +1</div>
        <div class="sl">PS</div><div class="sl">MM</div><div class="sl">PS</div><div class="sr">0 / −1 / +1</div>
        <div class="sl">PS</div><div class="sl">MM</div><div class="sl">MM</div><div class="sr">0 / +2 / +2</div>
        <div class="sl">MM</div><div class="sl">PS</div><div class="sl">PS</div><div class="sr">−2 / +1 / +1</div>
        <div class="sl">MM</div><div class="sl">MM</div><div class="sl">PS</div><div class="sr">+2 / +2 / 0</div>
        <div class="sl">MM</div><div class="sl">MM</div><div class="sl">MM</div><div class="sr">−2* / +2 / +2</div>
      </div>
      <div style="color:#998ABB;font-size:.72rem;margin-top:3px">*C2 Bonus → TW scores 0 · C5 Debuff → TW scores −4</div>
    </div>
    <div class="ref-section" style="margin-top:6px;font-size:.75rem;color:#998ABB">
      <b>Third Wheel rule:</b> Piles 1–2 → 3rd arrival is 3W · Piles 3–4 → 2nd arrival · Piles 5–6 → 1st arrival
    </div>
  </details>`;
}

/* ══ BOOT ══════════════════════════════════════════════════════════════════════ */
async function boot() {
  document.getElementById("app").innerHTML = `<div style="text-align:center;padding:60px;color:#998ABB">Loading…</div><div id="toast"></div>`;
  const data = await fetch("/api/state").then(r => r.json());
  gs = data;
  render();

  document.getElementById("app").addEventListener("click", e => {
    if (e.target.id === "btn-play-again" || e.target.closest("#btn-play-again")) {
      resetLocalState();
      api("/api/reset", {});
    }
  });
}

boot();
