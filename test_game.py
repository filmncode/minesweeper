"""Rules tests, plus a scripted game played through the real terminal UI."""

from __future__ import annotations

import os
import random
import select
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game import (  # noqa: E402
    FLAGGED,
    PRESETS,
    REVEALED,
    Board,
    Cell,
    Game,
    appearance,
    apply_key,
    counter,
    validate_rules,
)
from minesweeper import fit_message, line_that_fits, main, parse_config, required_size  # noqa: E402


def path_keys(cursor: tuple[int, int], target: tuple[int, int]) -> str:
    row, col = cursor
    target_row, target_col = target
    keys = []
    if target_row > row:
        keys.append("j" * (target_row - row))
    elif row > target_row:
        keys.append("k" * (row - target_row))
    if target_col > col:
        keys.append("l" * (target_col - col))
    elif col > target_col:
        keys.append("h" * (col - target_col))
    return "".join(keys)


def script_clear(game: Game) -> str:
    """Keystrokes that open every safe cell, using the same commands as the UI."""
    keys: list[str] = []
    while not game.board.won:
        target = next(
            (
                (row, col)
                for row in range(game.rows)
                for col in range(game.cols)
                if game.board.cells[row][col].state != REVEALED
                and game.board.cells[row][col].state != FLAGGED
                and (not game.board.started or not game.board.cells[row][col].mine)
            ),
            None,
        )
        if target is None:
            break
        step = path_keys(game.cursor, target) + " "
        before = game.board.revealed_safe
        keys.append(step)
        for key in step:
            apply_key(game, key)
        if game.board.lost:
            raise AssertionError("clearing script opened a mine")
        if game.board.revealed_safe == before and not game.board.won:
            raise AssertionError("clearing script made no progress")
    if not game.board.won:
        raise AssertionError("clearing script did not win")
    return "".join(keys)


class RulesTest(unittest.TestCase):
    def test_presets_are_legal(self) -> None:
        for preset in PRESETS:
            self.assertIsNone(validate_rules(preset.rows, preset.cols, preset.mines))

    def test_validate_rules_rejects_impossible_boards(self) -> None:
        self.assertIsNotNone(validate_rules(1, 9, 1))
        self.assertIsNotNone(validate_rules(9, 1, 1))
        self.assertIsNotNone(validate_rules(9, 9, 0))
        self.assertIsNotNone(validate_rules(9, 9, 81))
        self.assertIsNotNone(validate_rules(25, 9, 10))
        self.assertIsNotNone(validate_rules(9, 37, 10))
        self.assertIsNone(validate_rules(9, 9, 80))
        self.assertIsNone(validate_rules(2, 2, 3))

    def test_new_board_is_covered(self) -> None:
        board = Board(3, 4, 2)
        self.assertEqual(board.lines(), ["# # # #", "# # # #", "# # # #"])
        self.assertEqual(board.mines_left, 2)
        self.assertFalse(board.started)

    def test_neighbor_counts(self) -> None:
        board = Board(5, 5, 1)
        self.assertEqual(len(board.neighbors(0, 0)), 3)
        self.assertEqual(len(board.neighbors(0, 2)), 5)
        self.assertEqual(len(board.neighbors(2, 2)), 8)

    def test_first_click_clears_a_pocket(self) -> None:
        clicks = ((0, 0), (0, 8), (8, 8), (4, 4), (3, 6))
        for seed in range(25):
            for click in clicks:
                with self.subTest(seed=seed, click=click):
                    board = Board(9, 9, 10)
                    board.reveal(*click, random.Random(seed))
                    self.assertFalse(board.lost)
                    self.assertEqual(board.cells[click[0]][click[1]].state, REVEALED)
                    for row, col in {click, *board.neighbors(*click)}:
                        self.assertFalse(board.cells[row][col].mine)
                        expected = sum(
                            board.cells[nr][nc].mine for nr, nc in board.neighbors(row, col)
                        )
                        if not board.cells[row][col].mine:
                            self.assertEqual(board.cells[row][col].adjacent, expected)

    def test_crowded_board_still_protects_the_first_cell(self) -> None:
        board = Board(5, 5, 20)
        board.reveal(2, 2, random.Random(1))
        self.assertFalse(board.cells[2][2].mine)
        self.assertFalse(board.lost)
        self.assertEqual(len(board.mine_positions()), 20)

    def test_dense_opening_reveals_only_the_safe_pocket(self) -> None:
        board = Board(9, 9, 71)
        board.reveal(4, 4, random.Random(5))
        pocket = {(4, 4), *board.neighbors(4, 4)}
        for spot in pocket:
            self.assertFalse(board.cells[spot[0]][spot[1]].mine)
        self.assertEqual(board.revealed_safe, 9)
        self.assertEqual(board.safe_total, 10)
        self.assertFalse(board.won)
        self.assertFalse(board.lost)

    def test_only_one_safe_cell_wins_on_the_first_click(self) -> None:
        board = Board(2, 2, 3)
        board.reveal(0, 0, random.Random(2))
        self.assertTrue(board.won)
        self.assertFalse(board.lost)
        self.assertFalse(board.cells[0][0].mine)

    def test_same_seed_and_click_make_the_same_board(self) -> None:
        first = Board(9, 9, 10)
        second = Board(9, 9, 10)
        first.reveal(3, 4, random.Random(99))
        second.reveal(3, 4, random.Random(99))
        self.assertEqual(first.mine_positions(), second.mine_positions())
        self.assertGreater(len(first.mine_positions()), 0)

    def test_flood_opens_the_connected_region(self) -> None:
        board = Board(5, 5, 2)
        board.set_mines({(0, 4), (4, 0)})
        self.assertEqual(board.cells[2][2].adjacent, 0)
        self.assertEqual(board.cells[0][3].adjacent, 1)
        self.assertEqual(board.cells[4][1].adjacent, 1)
        board.reveal(2, 2, random.Random(0))
        self.assertTrue(board.won)
        self.assertEqual(board.cells[0][4].state, "hidden")
        self.assertEqual(board.cells[4][0].state, "hidden")
        self.assertEqual(board.lines()[0][0], ".")

    def test_a_flag_blocks_the_cell_under_it(self) -> None:
        board = Board(5, 5, 2)
        board.set_mines({(0, 4), (4, 0)})
        board.toggle_flag(2, 1)
        board.reveal(2, 2, random.Random(0))
        self.assertEqual(board.cells[2][1].state, FLAGGED)
        self.assertFalse(board.won)
        board.toggle_flag(2, 1)
        board.reveal(2, 1, random.Random(0))
        self.assertTrue(board.won)

    def test_opening_a_mine_loses_and_marks_it(self) -> None:
        board = Board(3, 3, 2)
        board.set_mines({(0, 0), (2, 2)})
        board.toggle_flag(0, 0)
        board.toggle_flag(0, 1)
        board.reveal(2, 2, random.Random(0))
        self.assertTrue(board.lost)
        self.assertFalse(board.won)
        self.assertEqual(board.hit, (2, 2))
        self.assertEqual(board.lines(), ["F x #", "# # #", "# # X"])

    def test_win_shows_remaining_mines_as_flags(self) -> None:
        board = Board(2, 2, 1)
        board.set_mines({(0, 0)})
        board.reveal(0, 1, random.Random(0))
        board.reveal(1, 0, random.Random(0))
        board.reveal(1, 1, random.Random(0))
        self.assertTrue(board.won)
        self.assertEqual(board.lines(), ["F 1", "1 1"])

    def test_chord_opens_the_neighbors(self) -> None:
        board = Board(3, 3, 1)
        board.set_mines({(0, 0)})
        board.reveal(1, 1, random.Random(0))
        self.assertEqual(board.cells[1][1].adjacent, 1)
        board.chord(1, 1)
        self.assertEqual(board.cells[1][1].state, REVEALED)
        self.assertFalse(board.won)
        board.toggle_flag(0, 0)
        board.chord(1, 1)
        self.assertTrue(board.won)
        self.assertFalse(board.lost)

    def test_a_wrong_chord_loses(self) -> None:
        board = Board(3, 3, 1)
        board.set_mines({(0, 0)})
        board.reveal(1, 1, random.Random(0))
        board.toggle_flag(0, 1)
        board.chord(1, 1)
        self.assertTrue(board.lost)
        self.assertEqual(board.cells[0][0].state, REVEALED)
        self.assertEqual(board.lines()[0][0], "X")

    def test_chord_waits_until_the_flags_match(self) -> None:
        board = Board(3, 3, 2)
        board.set_mines({(0, 0), (0, 2)})
        board.reveal(1, 1, random.Random(0))
        before = board.revealed_safe
        board.chord(1, 1)
        self.assertEqual(board.revealed_safe, before)
        self.assertFalse(board.lost)

    def test_extra_flags_drive_the_counter_negative(self) -> None:
        game = Game(3, 3, 1, seed=1)
        self.assertEqual(game.board.mines_left, 1)
        game.flag()
        self.assertEqual(game.board.mines_left, 0)
        game.move(0, 1)
        game.flag()
        self.assertEqual(game.board.mines_left, -1)
        game.flag()
        self.assertEqual(game.board.mines_left, 0)
        self.assertEqual(counter(-1), "-01")
        self.assertEqual(counter(7), "007")

    def test_flagging_first_does_not_place_mines(self) -> None:
        game = Game(5, 5, 3, seed=1)
        game.flag()
        game.primary()
        self.assertFalse(game.board.started)
        self.assertIsNone(game.started_at)
        game.flag()
        game.primary()
        self.assertTrue(game.board.started)
        self.assertFalse(game.board.lost)

    def test_timer_starts_on_the_first_open_and_then_stops(self) -> None:
        now = {"t": 10.0}
        game = Game(4, 4, 1, seed=1, clock=lambda: now["t"])
        game.board.set_mines({(0, 0)})
        game.cursor = (0, 1)
        game.primary()
        self.assertEqual(game.elapsed, 0)
        now["t"] = 15.5
        self.assertEqual(game.elapsed, 5)
        for row in range(4):
            for col in range(4):
                if game.board.won:
                    break
                cell = game.board.cells[row][col]
                if cell.mine or cell.state == REVEALED:
                    continue
                game.move_to(row, col)
                game.primary()
        self.assertTrue(game.board.won)
        now["t"] = 40
        self.assertEqual(game.elapsed, 5)

    def test_space_on_a_number_chords(self) -> None:
        game = Game(3, 3, 1, seed=1)
        game.board.set_mines({(0, 0)})
        game.cursor = (1, 1)
        game.primary()
        game.cursor = (0, 0)
        game.flag()
        game.cursor = (1, 1)
        apply_key(game, " ")
        self.assertTrue(game.board.won)

    def test_movement_stays_on_the_board(self) -> None:
        game = Game(3, 3, 1, seed=1)
        game.cursor = (0, 0)
        game.move(-1, -1)
        self.assertEqual(game.cursor, (0, 0))
        apply_key(game, "l")
        apply_key(game, "j")
        self.assertEqual(game.cursor, (1, 1))

    def test_new_game_key_does_not_play_a_move(self) -> None:
        game = Game(3, 3, 1, seed=2, seed_locked=True)
        self.assertEqual(apply_key(game, "n"), "new")
        self.assertFalse(game.board.started)
        self.assertEqual(game.restart().seed, 2)

    def test_replay_of_a_clearing_script_wins(self) -> None:
        guide = Game(5, 5, 2, seed=4)
        keys = script_clear(guide)
        game = Game(5, 5, 2, seed=4)
        for key in keys:
            apply_key(game, key)
        self.assertTrue(game.board.won)
        self.assertIn(" ", keys)

    def test_glyphs(self) -> None:
        covered = Cell()
        self.assertEqual(appearance(covered, outcome="playing", hit=False), ("#", "hidden"))
        number = Cell(state=REVEALED, adjacent=3)
        self.assertEqual(appearance(number, outcome="playing", hit=False), ("3", "n3"))
        empty = Cell(state=REVEALED, adjacent=0)
        self.assertEqual(appearance(empty, outcome="playing", hit=False), (".", "open"))

    def test_out_of_bounds_is_rejected(self) -> None:
        board = Board(3, 3, 1)
        with self.assertRaises(ValueError):
            board.reveal(3, 0, random.Random(0))
        with self.assertRaises(ValueError):
            board.set_mines({(0, 4)})


class LayoutTest(unittest.TestCase):
    def test_required_size(self) -> None:
        self.assertEqual(required_size(9, 9), (15, 19))
        self.assertEqual(required_size(16, 16), (22, 33))
        self.assertEqual(required_size(16, 30), (22, 61))

    def test_presets_fit_a_standard_terminal(self) -> None:
        for preset in PRESETS:
            need_h, need_w = required_size(preset.rows, preset.cols)
            self.assertLessEqual(need_h, 24, preset.name)
            self.assertLessEqual(need_w, 80, preset.name)

    def test_fit_message(self) -> None:
        self.assertIsNone(fit_message(9, 9, 24, 80))
        self.assertIn("22x61", fit_message(16, 30, 20, 80) or "")

    def test_standard_terminal_shows_the_full_help(self) -> None:
        line = line_that_fits(
            (
                "wasd/hjkl/arrows move  space open  f flag  c chord  n new  m menu  q quit",
                "space open  f flag  n new  q quit",
            ),
            80,
        )
        self.assertIn("chord", line)
        self.assertIn("flag", line)
        self.assertLessEqual(len(line), 78)

    def test_partial_size_is_an_error(self) -> None:
        with self.assertRaises(SystemExit):
            parse_config(["--rows", "9"])

    def test_invalid_board_does_not_open_the_terminal(self) -> None:
        self.assertEqual(main(["--rows", "1", "--cols", "1", "--mines", "1"]), 2)


class TerminalTest(unittest.TestCase):
    def test_menu_opens_beginner(self) -> None:
        chunks, code = run_session([], "1q", needle=b"adjacent mines")
        data = b"".join(chunks)
        self.assertEqual(code, 0, data.decode("utf-8", "replace")[-2000:])
        self.assertIn(b"MINESWEEPER", data)
        self.assertIn(b"Beginner", data)
        self.assertIn(b"adjacent mines", data)
        self.assertNotIn(b"Traceback", data)

    def test_custom_form_cancels_back_to_the_menu(self) -> None:
        chunks, code = run_session([], "4qq", needle=b"enter confirms")
        data = b"".join(chunks)
        self.assertEqual(code, 0, data.decode("utf-8", "replace")[-2000:])
        self.assertIn(b"enter confirms", data)
        self.assertNotIn(b"Traceback", data)

    def test_scripted_game_wins_on_screen(self) -> None:
        guide = Game(5, 5, 2, seed=4)
        keys = script_clear(guide)
        chunks, code = run_session(
            ["--rows", "5", "--cols", "5", "--mines", "2", "--seed", "4"],
            keys + "q",
            needle=b"You win",
        )
        data = b"".join(chunks)
        message = data.decode("utf-8", "replace")[-3000:]
        self.assertEqual(code, 0, message)
        self.assertIn(b"You win", data, message)
        self.assertIn(b"seed 4", data, message)
        self.assertNotIn(b"Traceback", data, message)


def run_session(args: list[str], keys: str, needle: bytes) -> tuple[list[bytes], int]:
    import fcntl
    import pty
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
    env = os.environ.copy()
    env.pop("LINES", None)
    env.pop("COLUMNS", None)
    env["TERM"] = "xterm-256color"
    env["LC_ALL"] = "C"
    chunks: list[bytes] = []
    proc = None
    try:
        proc = __import__("subprocess").Popen(
            [sys.executable, str(ROOT / "minesweeper.py"), *args],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            start_new_session=True,
        )
        os.close(slave)
        slave = -1
        if not _wait_for(master, chunks, b"MINESWEEPER", proc, 4):
            raise AssertionError(_dump(chunks))
        _send(master, chunks, keys, proc)
        if not _wait_for(master, chunks, needle, proc, 5):
            raise AssertionError(_dump(chunks))
        code = proc.wait(timeout=5)
        _drain(master, chunks, 0.2)
        return chunks, code
    finally:
        if slave >= 0:
            os.close(slave)
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
        os.close(master)


def _send(master: int, chunks: list[bytes], keys: str, proc) -> None:
    data = keys.encode()
    for start in range(0, len(data), 8):
        if proc.poll() is not None:
            return
        os.write(master, data[start : start + 8])
        _drain(master, chunks, 0.05)


def _wait_for(master: int, chunks: list[bytes], needle: bytes, proc, timeout: float) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if needle in b"".join(chunks):
            return True
        if proc.poll() is not None:
            while _read_some(master, chunks, 0.05):
                pass
            return needle in b"".join(chunks)
        _read_some(master, chunks, 0.1)
    return needle in b"".join(chunks)


def _drain(master: int, chunks: list[bytes], timeout: float) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _read_some(master, chunks, min(0.02, max(0, deadline - time.monotonic()))):
            return


def _read_some(master: int, chunks: list[bytes], timeout: float) -> bool:
    ready, _, _ = select.select([master], [], [], timeout)
    if not ready:
        return False
    try:
        data = os.read(master, 8192)
    except OSError:
        return False
    if not data:
        return False
    chunks.append(data)
    return True


def _dump(chunks: list[bytes]) -> str:
    return b"".join(chunks).decode("utf-8", "replace")[-4000:]


if __name__ == "__main__":
    unittest.main()
