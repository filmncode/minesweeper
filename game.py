"""Minesweeper rules, separate from the terminal UI.

The first opened cell is never a mine. When the density allows it, the
eight surrounding cells stay clear too, so the opening move uncovers a patch.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

HIDDEN = "hidden"
REVEALED = "revealed"
FLAGGED = "flagged"

MAX_ROWS = 24
MAX_COLS = 36


@dataclass(frozen=True)
class Preset:
    name: str
    rows: int
    cols: int
    mines: int


PRESETS = (
    Preset("Beginner", 9, 9, 10),
    Preset("Intermediate", 16, 16, 40),
    Preset("Expert", 16, 30, 99),
)


def new_seed() -> int:
    return random.SystemRandom().randrange(2**31)


def label_for(rows: int, cols: int, mines: int) -> str:
    for preset in PRESETS:
        if (preset.rows, preset.cols, preset.mines) == (rows, cols, mines):
            return preset.name
    return f"Custom {rows}x{cols}"


def validate_rules(rows: int, cols: int, mines: int) -> str | None:
    if rows < 2 or cols < 2:
        return "Use at least 2 rows and 2 columns."
    if rows > MAX_ROWS or cols > MAX_COLS:
        return f"The largest board is {MAX_ROWS} rows by {MAX_COLS} columns."
    if mines < 1:
        return "Use at least 1 mine."
    if mines >= rows * cols:
        return "Keep at least one safe cell."
    return None


def counter(value: int) -> str:
    if value < 0:
        return f"-{min(99, -value):02d}"
    return f"{min(999, value):03d}"


@dataclass
class Cell:
    mine: bool = False
    state: str = HIDDEN
    adjacent: int = 0


def appearance(cell: Cell, *, outcome: str, hit: bool) -> tuple[str, str]:
    """Return the glyph and a style name for one cell."""
    if cell.state == FLAGGED:
        if outcome == "lost" and not cell.mine:
            return "x", "bad"
        return "F", "flag"

    if cell.state == HIDDEN:
        if outcome == "won" and cell.mine:
            return "F", "flag"
        if outcome == "lost" and cell.mine:
            return "*", "mine"
        return "#", "hidden"

    if cell.mine:
        return ("X", "boom") if hit else ("*", "mine")
    if cell.adjacent == 0:
        return ".", "open"
    return str(cell.adjacent), f"n{cell.adjacent}"


class Board:
    def __init__(self, rows: int, cols: int, mine_count: int) -> None:
        message = validate_rules(rows, cols, mine_count)
        if message:
            raise ValueError(message)
        self.rows = rows
        self.cols = cols
        self.mine_count = mine_count
        self.cells = [[Cell() for _ in range(cols)] for _ in range(rows)]
        self.started = False
        self.exploded = False
        self.hit: tuple[int, int] | None = None

    def neighbors(self, row: int, col: int) -> list[tuple[int, int]]:
        found = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                nr, nc = row + dr, col + dc
                if self._inside(nr, nc):
                    found.append((nr, nc))
        return found

    def reveal(self, row: int, col: int, rng: random.Random) -> None:
        if self.exploded or self.won:
            return
        if not self._inside(row, col):
            raise ValueError("cell is outside the board")
        cell = self.cells[row][col]
        if cell.state != HIDDEN:
            return
        if not self.started:
            self.place_mines(row, col, rng)
        if cell.mine:
            cell.state = REVEALED
            self.exploded = True
            self.hit = (row, col)
            return
        self._open(row, col)

    def toggle_flag(self, row: int, col: int) -> None:
        if self.exploded or self.won:
            return
        if not self._inside(row, col):
            raise ValueError("cell is outside the board")
        cell = self.cells[row][col]
        if cell.state == REVEALED:
            return
        cell.state = HIDDEN if cell.state == FLAGGED else FLAGGED

    def chord(self, row: int, col: int) -> None:
        """Open every unflagged neighbor when the flag count matches the number."""
        if self.exploded or self.won or not self.started:
            return
        if not self._inside(row, col):
            raise ValueError("cell is outside the board")
        cell = self.cells[row][col]
        if cell.state != REVEALED or cell.adjacent == 0:
            return
        nearby = self.neighbors(row, col)
        flags = sum(self.cells[r][c].state == FLAGGED for r, c in nearby)
        if flags != cell.adjacent:
            return
        for r, c in nearby:
            other = self.cells[r][c]
            if other.state != HIDDEN:
                continue
            if other.mine:
                other.state = REVEALED
                self.exploded = True
                if self.hit is None:
                    self.hit = (r, c)
            else:
                self._open(r, c)

    def place_mines(self, row: int, col: int, rng: random.Random) -> None:
        protected = {(row, col), *self.neighbors(row, col)}
        cells = [(r, c) for r in range(self.rows) for c in range(self.cols)]
        candidates = [spot for spot in cells if spot not in protected]
        if len(candidates) < self.mine_count:
            candidates = [spot for spot in cells if spot != (row, col)]
        self.set_mines(rng.sample(candidates, self.mine_count))

    def set_mines(self, positions: Iterable[tuple[int, int]]) -> None:
        chosen = {(row, col) for row, col in positions}
        if len(chosen) != self.mine_count:
            raise ValueError(f"expected {self.mine_count} mines, got {len(chosen)}")
        for row, col in chosen:
            if not self._inside(row, col):
                raise ValueError("mine is outside the board")
        if self.started:
            raise RuntimeError("mines are already placed")
        for line in self.cells:
            for cell in line:
                cell.mine = False
                cell.adjacent = 0
        for row, col in chosen:
            self.cells[row][col].mine = True
        self._count_adjacent()
        self.started = True

    def mine_positions(self) -> set[tuple[int, int]]:
        return {
            (row, col)
            for row, line in enumerate(self.cells)
            for col, cell in enumerate(line)
            if cell.mine
        }

    def view(self) -> list[list[tuple[str, str]]]:
        return [
            [
                appearance(cell, outcome=self.outcome, hit=self.hit == (row, col))
                for col, cell in enumerate(line)
            ]
            for row, line in enumerate(self.cells)
        ]

    def lines(self) -> list[str]:
        return [" ".join(char for char, _style in row) for row in self.view()]

    @property
    def safe_total(self) -> int:
        return self.rows * self.cols - self.mine_count

    @property
    def revealed_safe(self) -> int:
        return sum(
            cell.state == REVEALED and not cell.mine
            for line in self.cells
            for cell in line
        )

    @property
    def flag_count(self) -> int:
        return sum(cell.state == FLAGGED for line in self.cells for cell in line)

    @property
    def mines_left(self) -> int:
        return self.mine_count - self.flag_count

    @property
    def won(self) -> bool:
        return (
            self.started
            and not self.exploded
            and self.revealed_safe == self.safe_total
        )

    @property
    def lost(self) -> bool:
        return self.exploded

    @property
    def outcome(self) -> str:
        if self.won:
            return "won"
        if self.exploded:
            return "lost"
        return "playing"

    def _open(self, row: int, col: int) -> None:
        stack = [(row, col)]
        while stack:
            r, c = stack.pop()
            cell = self.cells[r][c]
            if cell.state != HIDDEN or cell.mine:
                continue
            cell.state = REVEALED
            if cell.adjacent == 0:
                stack.extend(self.neighbors(r, c))

    def _count_adjacent(self) -> None:
        for row in range(self.rows):
            for col in range(self.cols):
                cell = self.cells[row][col]
                if cell.mine:
                    cell.adjacent = 0
                    continue
                cell.adjacent = sum(
                    self.cells[r][c].mine for r, c in self.neighbors(row, col)
                )

    def _inside(self, row: int, col: int) -> bool:
        return 0 <= row < self.rows and 0 <= col < self.cols


class Game:
    def __init__(
        self,
        rows: int,
        cols: int,
        mine_count: int,
        *,
        label: str | None = None,
        seed: int | None = None,
        seed_locked: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.rows = rows
        self.cols = cols
        self.mine_count = mine_count
        self.label = label or label_for(rows, cols, mine_count)
        self.seed = new_seed() if seed is None else seed
        self.seed_locked = seed_locked
        self.clock = clock or time.monotonic
        self.board = Board(rows, cols, mine_count)
        self.cursor = (rows // 2, cols // 2)
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.rng = random.Random(self.seed)

    def move(self, dr: int, dc: int) -> None:
        row, col = self.cursor
        self.cursor = (
            min(max(row + dr, 0), self.rows - 1),
            min(max(col + dc, 0), self.cols - 1),
        )

    def move_to(self, row: int, col: int) -> None:
        self.cursor = (
            min(max(row, 0), self.rows - 1),
            min(max(col, 0), self.cols - 1),
        )

    def primary(self) -> None:
        """Open a covered cell, or chord when the cursor is on a number."""
        if self.over:
            return
        row, col = self.cursor
        cell = self.board.cells[row][col]
        if cell.state == REVEALED and cell.adjacent > 0:
            self.board.chord(row, col)
        else:
            self.board.reveal(row, col, self.rng)
        self._touch_clock()

    def flag(self) -> None:
        if self.over:
            return
        row, col = self.cursor
        self.board.toggle_flag(row, col)

    def chord(self) -> None:
        if self.over:
            return
        row, col = self.cursor
        self.board.chord(row, col)
        self._touch_clock()

    def restart(self) -> Game:
        return Game(
            self.rows,
            self.cols,
            self.mine_count,
            label=self.label,
            seed=self.seed if self.seed_locked else None,
            seed_locked=self.seed_locked,
            clock=self.clock,
        )

    @property
    def over(self) -> bool:
        return self.board.won or self.board.lost

    @property
    def elapsed(self) -> int:
        if self.started_at is None:
            return 0
        end = self.finished_at if self.finished_at is not None else self.clock()
        return min(999, max(0, int(end - self.started_at)))

    @property
    def face(self) -> str:
        if self.board.won:
            return "B-)"
        if self.board.lost:
            return "X-("
        return ":-)"

    def hud(self) -> str:
        row, col = self.cursor
        left = 0 if self.board.won else self.board.mines_left
        return (
            f"{self.label}   {counter(left)} left   "
            f"{row + 1},{col + 1}   {self.face}   {counter(self.elapsed)}"
        )

    def _touch_clock(self) -> None:
        if self.started_at is None and self.board.started:
            self.started_at = self.clock()
        if self.finished_at is None and self.over:
            self.finished_at = self.clock()


def apply_key(game: Game, key: str) -> str | None:
    """Apply one gameplay key. Return new, menu, quit, or None to keep playing."""
    moves = {
        "h": (0, -1),
        "j": (1, 0),
        "k": (-1, 0),
        "l": (0, 1),
        "a": (0, -1),
        "s": (1, 0),
        "w": (-1, 0),
        "d": (0, 1),
    }
    if key in moves:
        game.move(*moves[key])
        return None
    if key == " ":
        game.primary()
        return None
    if key == "f":
        game.flag()
        return None
    if key == "c":
        game.chord()
        return None
    if key == "n":
        return "new"
    if key == "m":
        return "menu"
    if key == "q":
        return "quit"
    return None
