#!/usr/bin/env python3
"""Don't Be the Third Wheel! — A romantic scheduling strategy card game."""

import tkinter as tk
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple


LOCATION_NAMES = {
    1: "Coffee Shop",
    2: "Park",
    3: "Cinema",
    4: "Restaurant",
    5: "Beach",
    6: "Museum",
}

LOCATION_COLORS = {
    1: "#FFAAAA",
    2: "#AAFFCC",
    3: "#AACCFF",
    4: "#CCFFAA",
    5: "#FFEEAA",
    6: "#DDAAFF",
}

CARD_ABILITIES = {
    1: "Flip one of another player's face-up cards face down",
    2: "Flip one of your own face-up cards face down",
    3: "Swap the day slot of two of another player's cards",
    4: "Swap the day slot of two of your own cards",
    5: "Change the arrival order of an opponent's face-up card",
    6: "Change the arrival order of one of your own face-up cards",
}


@dataclass
class CardSlot:
    card_type: int
    face_up: bool = False
    arrival: int = 0  # 0 = not played, 1 = first, 2 = second, 3 = third


@dataclass
class Player:
    name: str
    cards: List[CardSlot] = field(default_factory=list)

    def card_at(self, day: int) -> Optional[CardSlot]:
        return self.cards[day - 1] if 1 <= day <= 6 else None


class GameState:
    def __init__(self, players: List[Player]):
        self.players = players
        self.current_player_idx = 0
        self.turn_count = 0
        self.game_over = False
        # arrivals[(day, card_type)] = [player_idx, ...] in arrival order
        self.arrivals: Dict[Tuple[int, int], List[int]] = {}

    @property
    def current_player(self) -> Player:
        return self.players[self.current_player_idx]

    def next_turn(self):
        self.turn_count += 1
        self.current_player_idx = (self.current_player_idx + 1) % len(self.players)
        if all(c.face_up for p in self.players for c in p.cards):
            self.game_over = True

    def flip_up(self, player: Player, day: int) -> bool:
        card = player.card_at(day)
        if not card or card.face_up:
            return False
        card.face_up = True
        key = (day, card.card_type)
        if key not in self.arrivals:
            self.arrivals[key] = []
        self.arrivals[key].append(self.players.index(player))
        card.arrival = len(self.arrivals[key])
        return True

    def flip_down(self, player: Player, day: int) -> bool:
        card = player.card_at(day)
        if not card or not card.face_up:
            return False
        key = (day, card.card_type)
        pidx = self.players.index(player)
        if key in self.arrivals and pidx in self.arrivals[key]:
            self.arrivals[key].remove(pidx)
            self._renumber(key)
        card.face_up = False
        card.arrival = 0
        return True

    def swap_days(self, player: Player, day1: int, day2: int) -> bool:
        c1, c2 = player.card_at(day1), player.card_at(day2)
        if not c1 or not c2 or day1 == day2:
            return False
        pidx = self.players.index(player)
        for day, card in [(day1, c1), (day2, c2)]:
            if card.face_up:
                key = (day, card.card_type)
                if key in self.arrivals and pidx in self.arrivals[key]:
                    self.arrivals[key].remove(pidx)
                    self._renumber(key)
        player.cards[day1 - 1], player.cards[day2 - 1] = (
            player.cards[day2 - 1],
            player.cards[day1 - 1],
        )
        # c1 is now at day2, c2 is now at day1
        for day, card in [(day1, c2), (day2, c1)]:
            if card.face_up:
                key = (day, card.card_type)
                if key not in self.arrivals:
                    self.arrivals[key] = []
                self.arrivals[key].append(pidx)
                card.arrival = len(self.arrivals[key])
        return True

    def change_arrival(self, player: Player, day: int, new_pos: int) -> bool:
        card = player.card_at(day)
        if not card or not card.face_up:
            return False
        key = (day, card.card_type)
        if key not in self.arrivals:
            return False
        pidx = self.players.index(player)
        arr = self.arrivals[key]
        if pidx not in arr:
            return False
        new_pos = max(1, min(new_pos, len(arr)))
        arr.remove(pidx)
        arr.insert(new_pos - 1, pidx)
        self._renumber(key)
        return True

    def _renumber(self, key: Tuple[int, int]):
        day, _ = key
        for i, pidx in enumerate(self.arrivals.get(key, [])):
            self.players[pidx].card_at(day).arrival = i + 1

    def calculate_scores(self) -> Dict[str, int]:
        scores = {p.name: 0 for p in self.players}
        for (day, ct), arr in self.arrivals.items():
            n = len(arr)
            if n == 2:
                scores[self.players[arr[0]].name] += 1
                scores[self.players[arr[1]].name] += 2
            elif n >= 3:
                scores[self.players[arr[2]].name] -= 1
        return scores


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Don't Be the Third Wheel!")
        self.root.geometry("980x700")
        self.root.configure(bg="#1a0a2e")
        self.root.resizable(True, True)

        self.game_state: Optional[GameState] = None
        self.pending_action: Optional[str] = None
        self.action_ctx: dict = {}

        self._show_setup()

    def _clear(self):
        for w in self.root.winfo_children():
            w.destroy()

    # ── SETUP SCREEN ──────────────────────────────────────────────────────────

    def _show_setup(self):
        self._clear()
        frame = tk.Frame(self.root, bg="#1a0a2e")
        frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=15)

        tk.Label(
            frame,
            text="Don't Be the Third Wheel!",
            font=("Arial", 26, "bold"),
            bg="#1a0a2e",
            fg="#FFD700",
        ).pack(pady=8)
        tk.Label(
            frame,
            text="A romantic scheduling strategy game for 2–3 players",
            font=("Arial", 12, "italic"),
            bg="#1a0a2e",
            fg="#CC99FF",
        ).pack()

        mid = tk.Frame(frame, bg="#1a0a2e")
        mid.pack(pady=15)

        tk.Label(
            mid, text="Number of Players:", font=("Arial", 12), bg="#1a0a2e", fg="white"
        ).pack()
        self._num_players = tk.IntVar(value=3)
        for n in (2, 3):
            tk.Radiobutton(
                mid,
                text=f"{n} Players",
                variable=self._num_players,
                value=n,
                font=("Arial", 11),
                bg="#1a0a2e",
                fg="white",
                selectcolor="#3a1a5e",
                activebackground="#1a0a2e",
                activeforeground="white",
            ).pack()

        tk.Label(
            mid, text="\nPlayer Names:", font=("Arial", 12), bg="#1a0a2e", fg="white"
        ).pack()
        self._name_vars = []
        for i in range(3):
            var = tk.StringVar(value=f"Player {i + 1}")
            row = tk.Frame(mid, bg="#1a0a2e")
            row.pack(pady=2)
            tk.Label(
                row, text=f"P{i + 1}:", font=("Arial", 11), bg="#1a0a2e", fg="white", width=3
            ).pack(side=tk.LEFT)
            tk.Entry(
                row,
                textvariable=var,
                font=("Arial", 11),
                width=14,
                bg="#2a1a4e",
                fg="white",
                insertbackground="white",
            ).pack(side=tk.LEFT)
            self._name_vars.append(var)

        tk.Button(
            frame,
            text="▶  Start Game",
            font=("Arial", 13, "bold"),
            bg="#9040FF",
            fg="white",
            padx=20,
            pady=9,
            bd=0,
            activebackground="#7030CC",
            cursor="hand2",
            command=self._start,
        ).pack(pady=12)

        ref = tk.LabelFrame(
            frame,
            text="Card Abilities",
            font=("Arial", 10, "bold"),
            bg="#1a0a2e",
            fg="#CC99FF",
            padx=10,
            pady=6,
        )
        ref.pack(fill=tk.X, pady=4)
        for ct in range(1, 7):
            tk.Label(
                ref,
                text=f"  {ct} – {LOCATION_NAMES[ct]:<12}: {CARD_ABILITIES[ct]}",
                font=("Courier", 9),
                bg="#1a0a2e",
                fg="#CCCCFF",
                anchor="w",
            ).pack(anchor="w")

        scoring = tk.LabelFrame(
            frame,
            text="Scoring",
            font=("Arial", 10, "bold"),
            bg="#1a0a2e",
            fg="#CC99FF",
            padx=10,
            pady=5,
        )
        scoring.pack(fill=tk.X, pady=4)
        for line in (
            "2 players same card on same day  →  1st arrival: +1 pt,  2nd arrival: +2 pts",
            "3 players same card on same day  →  1st: 0,  2nd: 0,  3rd (third wheel!): −1 pt",
            "1 player same card on a day      →  no points",
        ):
            tk.Label(
                scoring, text=line, font=("Arial", 9), bg="#1a0a2e", fg="#CCCCFF", anchor="w"
            ).pack(anchor="w")

    def _start(self):
        n = self._num_players.get()
        self._players_setup = []
        for i in range(n):
            name = self._name_vars[i].get().strip() or f"Player {i + 1}"
            self._players_setup.append(Player(name=name))
        self._arrange_idx = 0
        self._show_arrange()

    # ── ARRANGEMENT SCREEN ────────────────────────────────────────────────────

    def _show_arrange(self):
        self._clear()
        player = self._players_setup[self._arrange_idx]
        self._arrange_map: Dict[int, int] = {}  # card_type -> day

        frame = tk.Frame(self.root, bg="#1a0a2e")
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        tk.Label(
            frame,
            text=f"{player.name}: Schedule Your Dates!",
            font=("Arial", 19, "bold"),
            bg="#1a0a2e",
            fg="#FFD700",
        ).pack(pady=5)
        tk.Label(
            frame,
            text="Click a location card, then click a Day slot to assign it.",
            font=("Arial", 11),
            bg="#1a0a2e",
            fg="#CCAAFF",
        ).pack()

        self._sel_type = tk.IntVar(value=0)

        cards_frame = tk.LabelFrame(
            frame,
            text="Location Cards — click to select",
            font=("Arial", 10, "bold"),
            bg="#1a0a2e",
            fg="#CC99FF",
            padx=5,
            pady=8,
        )
        cards_frame.pack(fill=tk.X, padx=10, pady=10)
        inner = tk.Frame(cards_frame, bg="#1a0a2e")
        inner.pack()
        self._loc_btns: Dict[int, tk.Button] = {}
        for ct in range(1, 7):
            btn = tk.Button(
                inner,
                text=f"{ct}\n{LOCATION_NAMES[ct]}",
                font=("Arial", 10, "bold"),
                width=11,
                height=3,
                bg=LOCATION_COLORS[ct],
                fg="#1a0a2e",
                relief=tk.RAISED,
                bd=2,
                cursor="hand2",
                command=lambda c=ct: self._sel_card(c),
            )
            btn.grid(row=0, column=ct - 1, padx=4, pady=3)
            self._loc_btns[ct] = btn

        days_frame = tk.LabelFrame(
            frame,
            text="Day Slots — click to assign selected card",
            font=("Arial", 10, "bold"),
            bg="#1a0a2e",
            fg="#CC99FF",
            padx=5,
            pady=8,
        )
        days_frame.pack(fill=tk.X, padx=10, pady=5)
        inner2 = tk.Frame(days_frame, bg="#1a0a2e")
        inner2.pack()
        self._day_btns: List[tk.Button] = []
        for d in range(1, 7):
            btn = tk.Button(
                inner2,
                text=f"Day {d}\n(empty)",
                font=("Arial", 10),
                width=11,
                height=3,
                bg="#2a1a4e",
                fg="#AAAACC",
                relief=tk.GROOVE,
                bd=2,
                cursor="hand2",
                command=lambda day=d: self._assign_day(day),
            )
            btn.grid(row=0, column=d - 1, padx=4, pady=3)
            self._day_btns.append(btn)

        self._arrange_status = tk.Label(
            frame,
            text="Select a location card to begin.",
            font=("Arial", 11, "italic"),
            bg="#1a0a2e",
            fg="#FFCCAA",
        )
        self._arrange_status.pack(pady=8)

        self._confirm_btn = tk.Button(
            frame,
            text="Confirm Arrangement →",
            font=("Arial", 12, "bold"),
            bg="#9040FF",
            fg="white",
            padx=15,
            pady=8,
            state=tk.DISABLED,
            cursor="hand2",
            command=self._confirm_arrange,
        )
        self._confirm_btn.pack(pady=5)

    def _sel_card(self, ct: int):
        if ct in self._arrange_map:
            self._arrange_status.configure(
                text=f"Card {ct} is already placed on Day {self._arrange_map[ct]}!"
            )
            return
        self._sel_type.set(ct)
        for c, btn in self._loc_btns.items():
            btn.configure(relief=tk.SUNKEN if c == ct else tk.RAISED, bd=4 if c == ct else 2)
        self._arrange_status.configure(
            text=f"Selected: {ct} – {LOCATION_NAMES[ct]}.  Now click a Day slot."
        )

    def _assign_day(self, day: int):
        ct = self._sel_type.get()
        if ct == 0:
            self._arrange_status.configure(text="Select a location card first!")
            return
        if ct in self._arrange_map:
            self._arrange_status.configure(text=f"Card {ct} is already placed!")
            return
        if day in self._arrange_map.values():
            self._arrange_status.configure(
                text=f"Day {day} already has a card! Choose another day."
            )
            return
        self._arrange_map[ct] = day
        self._day_btns[day - 1].configure(
            text=f"Day {day}\n{ct}: {LOCATION_NAMES[ct][:9]}",
            bg=LOCATION_COLORS[ct],
            fg="#1a0a2e",
        )
        self._loc_btns[ct].configure(state=tk.DISABLED, relief=tk.FLAT, bg="#666666")
        self._sel_type.set(0)
        for btn in self._loc_btns.values():
            btn.configure(relief=tk.RAISED, bd=2)
        remaining = 6 - len(self._arrange_map)
        if remaining == 0:
            self._confirm_btn.configure(state=tk.NORMAL)
            self._arrange_status.configure(
                text="All cards placed!  Click Confirm to continue."
            )
        else:
            self._arrange_status.configure(text=f"{remaining} card(s) still to place.")

    def _confirm_arrange(self):
        player = self._players_setup[self._arrange_idx]
        cards = [None] * 6
        for ct, day in self._arrange_map.items():
            cards[day - 1] = CardSlot(card_type=ct)
        player.cards = cards
        self._arrange_idx += 1
        if self._arrange_idx < len(self._players_setup):
            self._show_arrange()
        else:
            self.game_state = GameState(self._players_setup)
            self._show_game()

    # ── GAME SCREEN ───────────────────────────────────────────────────────────

    def _show_game(self):
        self._clear()
        self.pending_action = None
        self.action_ctx = {}
        gs = self.game_state

        outer = tk.Frame(self.root, bg="#1a0a2e")
        outer.pack(fill=tk.BOTH, expand=True)

        tbar = tk.Frame(outer, bg="#2a0a4e", pady=6)
        tbar.pack(fill=tk.X)
        tk.Label(
            tbar,
            text="Don't Be the Third Wheel!",
            font=("Arial", 14, "bold"),
            bg="#2a0a4e",
            fg="#FFD700",
        ).pack(side=tk.LEFT, padx=12)
        self._turn_lbl = tk.Label(tbar, text="", font=("Arial", 11), bg="#2a0a4e", fg="#CCAAFF")
        self._turn_lbl.pack(side=tk.RIGHT, padx=12)

        self._act_lbl = tk.Label(
            outer,
            text="",
            font=("Arial", 11, "italic"),
            bg="#1a0a2e",
            fg="#FFB060",
            wraplength=940,
            pady=4,
        )
        self._act_lbl.pack(fill=tk.X, padx=10)

        board = tk.Frame(outer, bg="#1a0a2e")
        board.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        tk.Label(board, text="", bg="#1a0a2e", width=13).grid(row=0, column=0)
        for day in range(1, 7):
            tk.Label(
                board,
                text=f"Day {day}",
                font=("Arial", 11, "bold"),
                bg="#2a1a4e",
                fg="#CCAAFF",
                width=13,
                relief=tk.GROOVE,
                pady=4,
            ).grid(row=0, column=day, padx=2, pady=2)

        self._grid_btns: Dict[Tuple[int, int], tk.Button] = {}
        for pi, player in enumerate(gs.players):
            tk.Label(
                board,
                text=player.name,
                font=("Arial", 11, "bold"),
                bg="#1a0a2e",
                fg="#FFD700",
                width=13,
                anchor="w",
            ).grid(row=pi + 1, column=0, padx=5, pady=4)
            for day in range(1, 7):
                card = player.card_at(day)
                btn = tk.Button(
                    board,
                    text=self._card_text(card),
                    font=("Arial", 9),
                    width=13,
                    height=5,
                    bg=self._card_bg(card),
                    fg=self._card_fg(card),
                    relief=tk.RAISED,
                    bd=2,
                    cursor="hand2",
                    command=lambda p=pi, d=day: self._card_click(p, d),
                )
                btn.grid(row=pi + 1, column=day, padx=2, pady=4)
                self._grid_btns[(pi, day)] = btn

        bbar = tk.Frame(outer, bg="#1a0a2e", pady=5)
        bbar.pack(fill=tk.X, padx=10)

        self._cancel_btn = tk.Button(
            bbar,
            text="✕  Cancel Action",
            font=("Arial", 10),
            bg="#882020",
            fg="white",
            padx=10,
            pady=4,
            bd=0,
            cursor="hand2",
            command=self._cancel,
        )

        tk.Button(
            bbar,
            text="View Scores",
            font=("Arial", 10),
            bg="#206050",
            fg="white",
            padx=10,
            pady=4,
            bd=0,
            cursor="hand2",
            command=self._popup_scores,
        ).pack(side=tk.LEFT, padx=4)
        tk.Button(
            bbar,
            text="End Game",
            font=("Arial", 10),
            bg="#602020",
            fg="white",
            padx=10,
            pady=4,
            bd=0,
            cursor="hand2",
            command=self._end_game_screen,
        ).pack(side=tk.LEFT, padx=4)

        self._update_board()

    def _card_text(self, card: Optional[CardSlot]) -> str:
        if card is None:
            return "?"
        if not card.face_up:
            return "[ ? ]\n(face down)"
        sym = {1: "▲  1st arrival", 2: "■  2nd arrival", 3: "▼  3rd arrival"}.get(
            card.arrival, f"#{card.arrival}"
        )
        return f"{card.card_type}  –  {LOCATION_NAMES[card.card_type]}\n{sym}"

    def _card_bg(self, card: Optional[CardSlot]) -> str:
        if card is None or not card.face_up:
            return "#3a2a5a"
        return LOCATION_COLORS[card.card_type]

    def _card_fg(self, card: Optional[CardSlot]) -> str:
        return "#AAAACC" if (card is None or not card.face_up) else "#1a0a2e"

    def _update_board(self):
        gs = self.game_state
        self._turn_lbl.configure(
            text=f"Turn {gs.turn_count + 1}  —  {gs.current_player.name}'s turn"
        )
        for (pi, day), btn in self._grid_btns.items():
            card = gs.players[pi].card_at(day)
            btn.configure(
                text=self._card_text(card),
                bg=self._card_bg(card),
                fg=self._card_fg(card),
            )
            is_active = pi == gs.current_player_idx and not card.face_up
            btn.configure(
                relief=tk.RAISED if is_active else tk.FLAT,
                bd=3 if is_active else 1,
            )

    # ── CARD CLICK & ABILITY DISPATCH ─────────────────────────────────────────

    def _card_click(self, pi: int, day: int):
        gs = self.game_state
        if self.pending_action:
            self._handle_action(pi, day)
            return
        if pi != gs.current_player_idx:
            self._act_lbl.configure(text=f"It's {gs.current_player.name}'s turn!")
            return
        card = gs.players[pi].card_at(day)
        if card.face_up:
            self._act_lbl.configure(text="That card is already face up.")
            return
        gs.flip_up(gs.players[pi], day)
        self._update_board()
        self._trigger(card.card_type, pi, day)

    def _trigger(self, card_type: int, pi: int, day: int):
        gs = self.game_state
        player = gs.players[pi]

        if card_type == 1:
            targets = [
                True
                for p_idx, p in enumerate(gs.players)
                if p_idx != pi
                for d in range(1, 7)
                if p.card_at(d) and p.card_at(d).face_up
            ]
            if not targets:
                self._act_lbl.configure(text="Card 1: No opponent face-up cards. Ability skipped.")
                self._end_turn()
                return
            self.pending_action = "flip_other_down"
            self.action_ctx = {"actor": pi}
            self._act_lbl.configure(
                text=f"Card 1 ({LOCATION_NAMES[1]}): Click an OPPONENT'S face-up card to flip it face down."
            )
            self._cancel_btn.pack(side=tk.RIGHT, padx=5)

        elif card_type == 2:
            faceups = [
                d for d in range(1, 7) if player.card_at(d) and player.card_at(d).face_up
            ]
            if not faceups:
                self._act_lbl.configure(text="Card 2: No face-up cards to flip down. Ability skipped.")
                self._end_turn()
                return
            self.pending_action = "flip_own_down"
            self.action_ctx = {"actor": pi}
            self._act_lbl.configure(
                text=f"Card 2 ({LOCATION_NAMES[2]}): Click one of YOUR face-up cards to flip it face down."
            )
            self._cancel_btn.pack(side=tk.RIGHT, padx=5)

        elif card_type == 3:
            self.pending_action = "swap_other_1"
            self.action_ctx = {"actor": pi, "first_pidx": None, "first_day": None}
            self._act_lbl.configure(
                text=f"Card 3 ({LOCATION_NAMES[3]}): Click ANOTHER PLAYER'S card (first of two to swap days)."
            )
            self._cancel_btn.pack(side=tk.RIGHT, padx=5)

        elif card_type == 4:
            self.pending_action = "swap_own_1"
            self.action_ctx = {"actor": pi, "first_day": None}
            self._act_lbl.configure(
                text=f"Card 4 ({LOCATION_NAMES[4]}): Click one of YOUR cards (first of two to swap days)."
            )
            self._cancel_btn.pack(side=tk.RIGHT, padx=5)

        elif card_type == 5:
            valid = [
                True
                for p_idx, p in enumerate(gs.players)
                if p_idx != pi
                for d in range(1, 7)
                if p.card_at(d)
                and p.card_at(d).face_up
                and len(gs.arrivals.get((d, p.card_at(d).card_type), [])) >= 2
            ]
            if not valid:
                self._act_lbl.configure(
                    text="Card 5: No opponent cards with changeable arrival order. Ability skipped."
                )
                self._end_turn()
                return
            self.pending_action = "change_arr_other"
            self.action_ctx = {"actor": pi}
            self._act_lbl.configure(
                text=f"Card 5 ({LOCATION_NAMES[5]}): Click an OPPONENT'S face-up card to change its arrival order."
            )
            self._cancel_btn.pack(side=tk.RIGHT, padx=5)

        elif card_type == 6:
            valid = [
                d
                for d in range(1, 7)
                if player.card_at(d)
                and player.card_at(d).face_up
                and len(gs.arrivals.get((d, player.card_at(d).card_type), [])) >= 2
            ]
            if not valid:
                self._act_lbl.configure(
                    text="Card 6: No face-up cards with changeable arrival order. Ability skipped."
                )
                self._end_turn()
                return
            self.pending_action = "change_arr_own"
            self.action_ctx = {"actor": pi}
            self._act_lbl.configure(
                text=f"Card 6 ({LOCATION_NAMES[6]}): Click one of YOUR face-up cards to change its arrival order."
            )
            self._cancel_btn.pack(side=tk.RIGHT, padx=5)

        else:
            self._end_turn()

    # ── ACTION HANDLER ────────────────────────────────────────────────────────

    def _handle_action(self, pi: int, day: int):
        gs = self.game_state
        player = gs.players[pi]
        card = player.card_at(day)
        actor = self.action_ctx["actor"]

        if self.pending_action == "flip_other_down":
            if pi == actor:
                self._act_lbl.configure(text="Must click an OPPONENT'S card!")
                return
            if not card or not card.face_up:
                self._act_lbl.configure(text="Must click a face-up card!")
                return
            gs.flip_down(player, day)
            self._update_board()
            self._finish_action(
                f"Flipped {player.name}'s {LOCATION_NAMES[card.card_type]} (Day {day}) face down!"
            )

        elif self.pending_action == "flip_own_down":
            if pi != actor:
                self._act_lbl.configure(text="Must click YOUR OWN card!")
                return
            if not card or not card.face_up:
                self._act_lbl.configure(text="Must click a face-up card!")
                return
            gs.flip_down(player, day)
            self._update_board()
            self._finish_action(
                f"Flipped your {LOCATION_NAMES[card.card_type]} (Day {day}) face down!"
            )

        elif self.pending_action == "swap_other_1":
            if pi == actor:
                self._act_lbl.configure(text="Must click ANOTHER PLAYER'S card!")
                return
            self.action_ctx["first_pidx"] = pi
            self.action_ctx["first_day"] = day
            self.pending_action = "swap_other_2"
            self._act_lbl.configure(
                text=f"Selected {player.name}'s Day {day}.  Now click a SECOND card from THE SAME player."
            )

        elif self.pending_action == "swap_other_2":
            if pi == actor:
                self._act_lbl.configure(text="Must click an OPPONENT'S card!")
                return
            if pi != self.action_ctx["first_pidx"]:
                self._act_lbl.configure(text="Must pick two cards from THE SAME player!")
                return
            fd = self.action_ctx["first_day"]
            if day == fd:
                self._act_lbl.configure(text="Must select a DIFFERENT day!")
                return
            gs.swap_days(player, fd, day)
            self._update_board()
            self._finish_action(f"Swapped {player.name}'s Day {fd} and Day {day} cards!")

        elif self.pending_action == "swap_own_1":
            if pi != actor:
                self._act_lbl.configure(text="Must click YOUR OWN card!")
                return
            self.action_ctx["first_day"] = day
            self.pending_action = "swap_own_2"
            self._act_lbl.configure(
                text=f"Selected your Day {day}.  Now click a SECOND card of yours to complete the swap."
            )

        elif self.pending_action == "swap_own_2":
            if pi != actor:
                self._act_lbl.configure(text="Must click YOUR OWN card!")
                return
            fd = self.action_ctx["first_day"]
            if day == fd:
                self._act_lbl.configure(text="Must select a DIFFERENT day!")
                return
            gs.swap_days(gs.players[actor], fd, day)
            self._update_board()
            self._finish_action(f"Swapped your Day {fd} and Day {day} cards!")

        elif self.pending_action == "change_arr_other":
            if pi == actor:
                self._act_lbl.configure(text="Must click an OPPONENT'S card!")
                return
            if not card or not card.face_up:
                self._act_lbl.configure(text="Must click a face-up card!")
                return
            key = (day, card.card_type)
            if len(gs.arrivals.get(key, [])) < 2:
                self._act_lbl.configure(
                    text="That card's arrival can't be changed (only one player there)."
                )
                return
            self._arrival_picker(pi, day)

        elif self.pending_action == "change_arr_own":
            if pi != actor:
                self._act_lbl.configure(text="Must click YOUR OWN card!")
                return
            if not card or not card.face_up:
                self._act_lbl.configure(text="Must click a face-up card!")
                return
            key = (day, card.card_type)
            if len(gs.arrivals.get(key, [])) < 2:
                self._act_lbl.configure(
                    text="That card's arrival can't be changed (only one player there)."
                )
                return
            self._arrival_picker(pi, day)

    def _arrival_picker(self, pi: int, day: int):
        gs = self.game_state
        player = gs.players[pi]
        card = player.card_at(day)
        key = (day, card.card_type)
        num = len(gs.arrivals[key])

        popup = tk.Toplevel(self.root)
        popup.title("Change Arrival Order")
        popup.geometry("320x240")
        popup.configure(bg="#1a0a2e")
        popup.grab_set()
        popup.resizable(False, False)

        tk.Label(
            popup,
            text=f"{player.name}'s {LOCATION_NAMES[card.card_type]}\non Day {day}",
            font=("Arial", 12, "bold"),
            bg="#1a0a2e",
            fg="#FFD700",
        ).pack(pady=10)
        tk.Label(
            popup,
            text=f"Current position: #{card.arrival} of {num}",
            font=("Arial", 10),
            bg="#1a0a2e",
            fg="#CCAAFF",
        ).pack()
        tk.Label(
            popup, text="Move to position:", font=("Arial", 10), bg="#1a0a2e", fg="white"
        ).pack(pady=(10, 3))

        var = tk.IntVar(value=card.arrival)
        labels = {1: "1st  (above the line)", 2: "2nd  (in line)", 3: "3rd  (below the line)"}
        for i in range(1, num + 1):
            tk.Radiobutton(
                popup,
                text=labels.get(i, f"#{i}"),
                variable=var,
                value=i,
                font=("Arial", 10),
                bg="#1a0a2e",
                fg="white",
                selectcolor="#3a1a5e",
                activebackground="#1a0a2e",
                activeforeground="white",
            ).pack()

        def confirm():
            new_pos = var.get()
            gs.change_arrival(player, day, new_pos)
            popup.destroy()
            self._update_board()
            self._finish_action(
                f"Changed {player.name}'s {LOCATION_NAMES[card.card_type]} arrival to position #{new_pos}!"
            )

        tk.Button(
            popup,
            text="Confirm",
            command=confirm,
            bg="#9040FF",
            fg="white",
            font=("Arial", 11),
            padx=12,
            pady=5,
            bd=0,
            cursor="hand2",
        ).pack(pady=12)

    def _finish_action(self, msg: str):
        self.pending_action = None
        self.action_ctx = {}
        self._cancel_btn.pack_forget()
        self._act_lbl.configure(text=f"✓  {msg}")
        self.root.after(1500, self._end_turn)

    def _cancel(self):
        self.pending_action = None
        self.action_ctx = {}
        self._cancel_btn.pack_forget()
        self._act_lbl.configure(text="Action cancelled.")
        self.root.after(400, self._end_turn)

    def _end_turn(self):
        gs = self.game_state
        gs.next_turn()
        if gs.game_over:
            self._end_game_screen()
            return
        self._update_board()
        skipped = 0
        while (
            all(c.face_up for c in gs.current_player.cards)
            and skipped < len(gs.players)
        ):
            self._act_lbl.configure(
                text=f"{gs.current_player.name} has no face-down cards left — skipping turn."
            )
            gs.next_turn()
            if gs.game_over:
                self._end_game_screen()
                return
            skipped += 1
        if skipped == 0:
            self._act_lbl.configure(text="")
        self._update_board()

    # ── SCORES ────────────────────────────────────────────────────────────────

    def _popup_scores(self):
        gs = self.game_state
        scores = gs.calculate_scores()
        popup = tk.Toplevel(self.root)
        popup.title("Current Scores")
        popup.geometry("460x420")
        popup.configure(bg="#1a0a2e")
        popup.grab_set()

        tk.Label(
            popup, text="Current Scores", font=("Arial", 15, "bold"), bg="#1a0a2e", fg="#FFD700"
        ).pack(pady=10)
        for name, pts in sorted(scores.items(), key=lambda x: -x[1]):
            tk.Label(
                popup, text=f"{name}:  {pts:+d} pts", font=("Arial", 12), bg="#1a0a2e", fg="white"
            ).pack(pady=2)

        tk.Frame(popup, bg="#444466", height=1).pack(fill=tk.X, padx=20, pady=10)
        tk.Label(
            popup, text="Breakdown:", font=("Arial", 10, "bold"), bg="#1a0a2e", fg="#CCAAFF"
        ).pack()

        for (day, ct), arr in sorted(gs.arrivals.items()):
            n = len(arr)
            pnames = " → ".join(gs.players[pi].name[:7] for pi in arr)
            note = {1: "solo – no pts", 2: "1st+1, 2nd+2", 3: "3rd: −1"}.get(n, f"{n} players")
            tk.Label(
                popup,
                text=f"Day {day}  {LOCATION_NAMES[ct]:<12}: {pnames}  [{note}]",
                font=("Courier", 9),
                bg="#1a0a2e",
                fg="#CCCCFF",
                anchor="w",
            ).pack(anchor="w", padx=20)

        tk.Button(
            popup,
            text="Close",
            command=popup.destroy,
            bg="#9040FF",
            fg="white",
            font=("Arial", 10),
            padx=10,
            pady=4,
            bd=0,
        ).pack(pady=10)

    def _end_game_screen(self):
        gs = self.game_state
        scores = gs.calculate_scores()
        self._clear()

        frame = tk.Frame(self.root, bg="#1a0a2e")
        frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)

        tk.Label(
            frame, text="Game Over!", font=("Arial", 26, "bold"), bg="#1a0a2e", fg="#FFD700"
        ).pack(pady=8)

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        medals = ["🥇", "🥈", "🥉"]
        for i, (name, pts) in enumerate(ranked):
            m = medals[i] if i < 3 else f"#{i + 1}"
            tk.Label(
                frame,
                text=f"{m}  {name}  —  {pts:+d} points",
                font=("Arial", 14, "bold" if i == 0 else "normal"),
                bg="#1a0a2e",
                fg="#FFD700" if i == 0 else "white",
            ).pack(pady=3)

        tk.Frame(frame, bg="#444466", height=2).pack(fill=tk.X, pady=12)
        tk.Label(
            frame, text="Date Results:", font=("Arial", 12, "bold"), bg="#1a0a2e", fg="#CC99FF"
        ).pack()

        for (day, ct), arr in sorted(gs.arrivals.items()):
            n = len(arr)
            pnames = " → ".join(gs.players[pi].name for pi in arr)
            if n == 1:
                detail = f"Day {day}  {LOCATION_NAMES[ct]:<12}: {pnames}  (solo — no points)"
                col = "#888888"
            elif n == 2:
                detail = f"Day {day}  {LOCATION_NAMES[ct]:<12}: {pnames}  (1st: +1,  2nd: +2)"
                col = "#AAFFCC"
            else:
                detail = f"Day {day}  {LOCATION_NAMES[ct]:<12}: {pnames}  (3rd wheel: −1)"
                col = "#FFAAAA"
            tk.Label(
                frame, text=detail, font=("Courier", 10), bg="#1a0a2e", fg=col, anchor="w"
            ).pack(anchor="w", padx=10)

        tk.Button(
            frame,
            text="▶  Play Again",
            font=("Arial", 13, "bold"),
            bg="#9040FF",
            fg="white",
            padx=20,
            pady=9,
            bd=0,
            cursor="hand2",
            command=self._show_setup,
        ).pack(pady=18)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
