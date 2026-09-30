#!/usr/bin/env python3
"""Play Minesweeper in the terminal.

    python3 minesweeper.py
    python3 minesweeper.py --rows 16 --cols 30 --mines 99

Move with the arrow keys, wasd, or hjkl. Space or a left click opens a cell.
f or a right click plants a flag. c, or space on a number, chords: when the
flags around a number match it, the rest of those neighbors open.
"""

from __future__ import annotations

import argparse
import curses
import os
import sys
import time
from dataclasses import dataclass

from game import PRESETS, Game, apply_key, label_for, validate_rules

HEADER = 4
FOOTER = 2

HELP_LINES = (
    "wasd/hjkl/arrows move  space open  f flag  c chord  n new  m menu  q quit",
    "space open  f flag  c chord  n new  m menu  q quit",
    "space open  f flag  n new  q quit",
)
LEGENDS = (
    "# covered   F flag   . clear   number = adjacent mines",
    "# covered  F flag  . clear",
)

CANCEL = object()
RESIZE = object()


@dataclass
class Config:
    rows: int | None = None
    cols: int | None = None
    mines: int | None = None
    seed: int | None = None


def required_size(rows: int, cols: int) -> tuple[int, int]:
    grid_w = cols * 2 - 1
    return HEADER + rows + FOOTER, grid_w + 2


def fit_message(rows: int, cols: int, height: int, width: int) -> str | None:
    need_h, need_w = required_size(rows, cols)
    if height >= need_h and width >= need_w:
        return None
    return f"This terminal is {height}x{width}. That board needs {need_h}x{need_w}."


def line_that_fits(options: tuple[str, ...], width: int) -> str:
    usable = max(1, width - 2)
    for option in options:
        if len(option) <= usable:
            return option
    return options[-1]


class Theme:
    COLORS = {
        "n1": "BLUE",
        "n2": "GREEN",
        "n3": "RED",
        "n4": "BLUE",
        "n5": "MAGENTA",
        "n6": "CYAN",
        "n7": "WHITE",
        "n8": "WHITE",
        "flag": "YELLOW",
        "mine": "RED",
        "boom": "RED",
        "bad": "MAGENTA",
        "title": "CYAN",
        "win": "GREEN",
        "lose": "RED",
        "face": "YELLOW",
        "hidden": "WHITE",
    }
    BOLD = {"n1", "n2", "n3", "n5", "n6", "n7", "flag", "mine", "boom", "title", "win", "bad", "face"}

    def __init__(self) -> None:
        self.pairs: dict[str, int] = {}
        if not curses.has_colors():
            return
        try:
            curses.start_color()
        except curses.error:
            return
        try:
            curses.use_default_colors()
            background = -1
        except curses.error:
            background = curses.COLOR_BLACK
        for index, (name, color_name) in enumerate(self.COLORS.items(), start=1):
            foreground = getattr(curses, f"COLOR_{color_name}")
            try:
                curses.init_pair(index, foreground, background)
            except curses.error:
                return
            self.pairs[name] = index

    def attr(self, style: str, cursor: bool = False) -> int:
        attr = 0
        pair = self.pairs.get(style)
        if pair:
            attr |= curses.color_pair(pair)
        if style in self.BOLD or style == "hidden":
            attr |= curses.A_BOLD
        if style == "n8" and not cursor:
            attr |= curses.A_DIM
        if cursor or style == "boom":
            attr |= curses.A_REVERSE
        return attr


def put(stdscr: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
    if not text:
        return
    height, width = stdscr.getmaxyx()
    if y < 0 or y >= height or x >= width:
        return
    if x < 0:
        text = text[-x:]
        x = 0
        if not text:
            return
    limit = width - x
    if y == height - 1:
        limit -= 1
    text = text[:limit]
    if not text:
        return
    try:
        stdscr.addstr(y, x, text, attr)
    except curses.error:
        pass


def put_center(stdscr: curses.window, y: int, text: str, attr: int = 0) -> None:
    _, width = stdscr.getmaxyx()
    put(stdscr, y, max(0, (width - len(text)) // 2), text, attr)


def parse_config(argv: list[str] | None) -> Config:
    parser = argparse.ArgumentParser(
        prog="minesweeper",
        description="Play Minesweeper in the terminal.",
    )
    parser.add_argument("--rows", type=int, help="board rows (with --cols and --mines)")
    parser.add_argument("--cols", type=int, help="board columns")
    parser.add_argument("--mines", type=int, help="number of mines")
    parser.add_argument(
        "--seed",
        type=int,
        help="layout seed; the same seed and first open make the same board",
    )
    args = parser.parse_args(argv)
    given = (args.rows, args.cols, args.mines)
    if any(value is not None for value in given) and any(value is None for value in given):
        parser.error("--rows, --cols, and --mines must be given together")
    return Config(args.rows, args.cols, args.mines, args.seed)


def game_from_config(config: Config) -> Game:
    rows = config.rows or 0
    cols = config.cols or 0
    mines = config.mines or 0
    return Game(
        rows,
        cols,
        mines,
        label=label_for(rows, cols, mines),
        seed=config.seed,
        seed_locked=config.seed is not None,
    )


def launch(stdscr: curses.window, config: Config) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    stdscr.keypad(True)
    try:
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
    except curses.error:
        pass
    theme = Theme()
    game = game_from_config(config) if config.rows is not None else None
    while True:
        if game is None:
            stdscr.timeout(-1)
            chosen = choose_board(stdscr, theme)
            if chosen is None:
                return
            label, rows, cols, mines = chosen
            game = Game(
                rows,
                cols,
                mines,
                label=label,
                seed=config.seed,
                seed_locked=config.seed is not None,
            )
            continue
        stdscr.timeout(200)
        action = play(stdscr, theme, game)
        if action == "quit":
            return
        if action == "menu":
            game = None
            continue
        if action == "new":
            game = game.restart()


def choose_board(stdscr: curses.window, theme: Theme) -> tuple[str, int, int, int] | None:
    index = 0
    while True:
        height, width = stdscr.getmaxyx()
        stdscr.erase()
        if height < 12 or width < 40:
            put(stdscr, 0, 0, "Make the terminal bigger to play.")
            put(stdscr, 1, 0, "q quits.")
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                return None
            continue
        _draw_menu(stdscr, theme, index)
        stdscr.refresh()
        ch = stdscr.getch()
        if ch in (curses.KEY_UP, ord("k"), ord("K"), ord("w"), ord("W")):
            index = (index - 1) % 4
        elif ch in (curses.KEY_DOWN, ord("j"), ord("J"), ord("s"), ord("S")):
            index = (index + 1) % 4
        elif ch in (ord("1"), ord("2"), ord("3"), ord("4")):
            index = ch - ord("1")
            chosen = _activate(stdscr, theme, index, height, width)
            if chosen is not None:
                return chosen
        elif ch in (10, 13, curses.KEY_ENTER):
            chosen = _activate(stdscr, theme, index, height, width)
            if chosen is not None:
                return chosen
        elif ch in (ord("q"), ord("Q")):
            return None


def _draw_menu(stdscr: curses.window, theme: Theme, index: int) -> None:
    rows = [
        f"{preset.name:<14}{preset.rows:>2}x{preset.cols:<2}   {preset.mines:>3} mines"
        for preset in PRESETS
    ]
    rows.append("Custom")
    put_center(stdscr, 1, "MINESWEEPER", theme.attr("title"))
    put_center(stdscr, 3, "Choose a board")
    _, width = stdscr.getmaxyx()
    left = max(2, (width - 36) // 2)
    for row, text in enumerate(rows):
        label = f"{row + 1}  {text}"
        attr = theme.attr("title") if row == index else 0
        if row == index:
            attr |= curses.A_REVERSE
        put(stdscr, 5 + row, left, label, attr)
    put_center(stdscr, 11, "arrows move    enter starts    q quits")


def _activate(
    stdscr: curses.window,
    theme: Theme,
    index: int,
    height: int,
    width: int,
) -> tuple[str, int, int, int] | None:
    if index < len(PRESETS):
        preset = PRESETS[index]
        message = fit_message(preset.rows, preset.cols, height, width)
        if message:
            _notice(stdscr, theme, message)
            return None
        return preset.name, preset.rows, preset.cols, preset.mines
    return custom_size(stdscr, theme)


def custom_size(stdscr: curses.window, theme: Theme) -> tuple[str, int, int, int] | None:
    labels = ("Rows", "Columns", "Mines")
    values = [9, 9, 10]
    step = 0
    error = ""
    while True:
        stdscr.erase()
        put_center(stdscr, 1, "MINESWEEPER", theme.attr("title"))
        put_center(stdscr, 3, "Custom board")
        for i, label in enumerate(labels):
            marker = ">" if i == step else " "
            put(stdscr, 5 + i, 4, f"{marker} {label}:")
            if i != step:
                put(stdscr, 5 + i, 16, str(values[i]))
        if error:
            put(stdscr, 9, 4, error, theme.attr("lose"))
        put(stdscr, 11, 4, "enter confirms    q back")
        stdscr.refresh()
        result = edit_field(stdscr, 5 + step, 16, str(values[step]), 3)
        if result is CANCEL:
            return None
        if result is RESIZE:
            continue
        if not isinstance(result, str) or not result.isdigit():
            error = "Enter a number."
            continue
        values[step] = int(result)
        error = ""
        if step < 2:
            step += 1
            continue
        rows, cols, mines = values
        message = validate_rules(rows, cols, mines)
        if message is None:
            height, width = stdscr.getmaxyx()
            message = fit_message(rows, cols, height, width)
        if message:
            error = message
            step = 0
            continue
        return label_for(rows, cols, mines), rows, cols, mines


def edit_field(stdscr: curses.window, y: int, x: int, default: str, limit: int) -> object:
    buffer = list(default)
    replace = True
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    try:
        while True:
            shown = "".join(buffer)
            put(stdscr, y, x, " " * limit)
            put(stdscr, y, x, shown)
            height, width = stdscr.getmaxyx()
            cy = min(max(y, 0), height - 1)
            cx = min(max(x + len(shown), 0), width - 1)
            try:
                stdscr.move(cy, cx)
            except curses.error:
                pass
            stdscr.refresh()
            ch = stdscr.getch()
            if ch == curses.KEY_RESIZE:
                return RESIZE
            if ch in (ord("q"), ord("Q")):
                return CANCEL
            if ch in (10, 13, curses.KEY_ENTER):
                return shown
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                replace = False
                if buffer:
                    buffer.pop()
                continue
            if 48 <= ch <= 57 and (replace or len(buffer) < limit):
                if replace:
                    buffer = []
                    replace = False
                if len(buffer) < limit:
                    buffer.append(chr(ch))
    finally:
        try:
            curses.curs_set(0)
        except curses.error:
            pass


def _notice(stdscr: curses.window, theme: Theme, message: str) -> None:
    stdscr.erase()
    put_center(stdscr, 1, "MINESWEEPER", theme.attr("title"))
    put_center(stdscr, 4, message, theme.attr("lose"))
    put_center(stdscr, 6, "Press any key")
    stdscr.refresh()
    stdscr.getch()


def play(stdscr: curses.window, theme: Theme, game: Game) -> str:
    origin: tuple[int, int] | None = None
    last_second: int | None = None
    dirty = True
    last_click = (0.0, -1, -1, "")
    while True:
        second = game.elapsed
        if dirty or second != last_second:
            origin = draw_game(stdscr, theme, game)
            last_second = second
            dirty = False
        ch = stdscr.getch()
        if ch == -1:
            continue
        dirty = True
        if ch == curses.KEY_RESIZE:
            continue
        if ch == curses.KEY_MOUSE:
            action = _mouse(stdscr, game, origin, last_click)
            last_click = action[1]
            if action[0] == "quit":
                return "quit"
            continue
        if ch in (curses.KEY_UP,):
            game.move(-1, 0)
            continue
        if ch in (curses.KEY_DOWN,):
            game.move(1, 0)
            continue
        if ch in (curses.KEY_LEFT,):
            game.move(0, -1)
            continue
        if ch in (curses.KEY_RIGHT,):
            game.move(0, 1)
            continue
        if ch in (10, 13, curses.KEY_ENTER):
            game.primary()
            continue
        if 0 <= ch < 256:
            action = apply_key(game, chr(ch).lower())
            if action in {"quit", "menu", "new"}:
                return action or "quit"


def draw_game(stdscr: curses.window, theme: Theme, game: Game) -> tuple[int, int] | None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    message = fit_message(game.rows, game.cols, height, width)
    if message:
        put(stdscr, 0, 0, message)
        put(stdscr, 2, 0, "q quits. Resize the terminal to see the board.")
        stdscr.refresh()
        return None

    put_center(stdscr, 1, "MINESWEEPER", theme.attr("title"))
    face_style = "win" if game.board.won else "lose" if game.board.lost else "face"
    hud = game.hud()
    # Color only the face; the rest of the HUD stays in the default color.
    face = game.face
    face_at = hud.rfind(face)
    hud_x = max(0, (width - len(hud)) // 2)
    put(stdscr, 2, hud_x, hud[:face_at])
    put(stdscr, 2, hud_x + face_at, face, theme.attr(face_style))
    put(stdscr, 2, hud_x + face_at + len(face), hud[face_at + len(face) :])

    grid_w = game.cols * 2 - 1
    origin_x = (width - grid_w) // 2
    origin_y = HEADER
    for row, line in enumerate(game.board.view()):
        for col, (char, style) in enumerate(line):
            put(
                stdscr,
                origin_y + row,
                origin_x + col * 2,
                char,
                theme.attr(style, cursor=game.cursor == (row, col)),
            )

    if game.board.won or game.board.lost:
        footer, footer_style = _result(game)
    else:
        footer, footer_style = line_that_fits(LEGENDS, width), ""
    # Keep the legend with the board. A one-line gap appears when the
    # terminal has room; a minimum window puts the legend on the next line.
    gap = 1 if height > origin_y + game.rows + 2 else 0
    legend_y = origin_y + game.rows + gap
    put_center(stdscr, legend_y, footer, theme.attr(footer_style))
    put_center(stdscr, legend_y + 1, line_that_fits(HELP_LINES, width))
    stdscr.refresh()
    return origin_y, origin_x


def _result(game: Game) -> tuple[str, str]:
    if game.board.won:
        return f"You win in {game.elapsed}s   (seed {game.seed})", "win"
    return f"Boom   (seed {game.seed})", "lose"


def _mouse(
    stdscr: curses.window,
    game: Game,
    origin: tuple[int, int] | None,
    last_click: tuple[float, int, int, str],
) -> tuple[str | None, tuple[float, int, int, str]]:
    if origin is None:
        return None, last_click
    try:
        _id, x, y, _z, bstate = curses.getmouse()
    except curses.error:
        return None, last_click
    kind = _mouse_kind(bstate)
    if kind is None:
        return None, last_click
    origin_y, origin_x = origin
    if y < origin_y or y >= origin_y + game.rows:
        return None, last_click
    dx = x - origin_x
    if dx < 0:
        return None, last_click
    col = dx // 2
    if col >= game.cols:
        return None, last_click
    row = y - origin_y
    now = time.monotonic()
    previous_at, previous_row, previous_col, previous_kind = last_click
    if (
        kind == previous_kind
        and (row, col) == (previous_row, previous_col)
        and now - previous_at < 0.12
    ):
        return None, last_click
    game.move_to(row, col)
    if kind == "open":
        game.primary()
    elif kind == "flag":
        game.flag()
    else:
        game.chord()
    return None, (now, row, col, kind)


def _mouse_kind(bstate: int) -> str | None:
    def pressed(button: int) -> bool:
        for name in ("CLICKED", "PRESSED", "RELEASED"):
            mask = getattr(curses, f"BUTTON{button}_{name}", 0)
            if mask and bstate & mask:
                return True
        return False

    if pressed(2):
        return "chord"
    if pressed(3):
        return "flag"
    if pressed(1):
        return "open"
    return None


def main(argv: list[str] | None = None) -> int:
    try:
        config = parse_config(argv)
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else 1
    if config.rows is not None:
        message = validate_rules(config.rows, config.cols or 0, config.mines or 0)
        if message:
            print(message, file=sys.stderr)
            return 2
    os.environ.setdefault("ESCDELAY", "25")
    try:
        curses.use_env(False)
    except AttributeError:
        pass
    try:
        curses.wrapper(lambda stdscr: launch(stdscr, config))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
