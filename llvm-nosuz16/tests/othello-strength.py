#!/usr/bin/env python3
"""Reproduce paired native matches against the original two-ply opponent.

Requires cc and Git history containing 313ebbb. Native matches measure
playing choices; tests/othello.py separately validates the Nosuz16 image.
"""
from pathlib import Path
import random
import subprocess
import tempfile

from othello import apply, moves

ROOT = Path(__file__).resolve().parents[2]
BASELINE = '313ebbb'
HARNESS = r'''
#define NOSUZ16_H
int game_printf(const char *format, ...);
int game_putc(int c);
int game_getc(void);
#define main game_main
#define printf game_printf
#define putc game_putc
#define getc game_getc
#include OTHELLO_SOURCE
#undef main
#undef printf
#undef putc
#undef getc
#include <stdio.h>
int game_printf(const char *format, ...) { return 0; }
int game_putc(int c) { return c; }
int game_getc(void) { return 'q'; }
int main(void) {
  char cells[65];
  while (scanf("%64s", cells) == 1) {
    int i, move;
    for (i = 0; i < 100; ++i) board[i] = 3;
    for (i = 0; i < 64; ++i) board[(i / 8 + 1) * 10 + i % 8 + 1] = cells[i] - '0';
    move = choose_cpu_move();
    for (i = 0; i < 64; ++i)
      if (board[(i / 8 + 1) * 10 + i % 8 + 1] != cells[i] - '0') return 2;
    printf("%d\n", move);
    fflush(stdout);
  }
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix='nosuz16-othello-strength-') as temporary:
        directory = Path(temporary)
        baseline = directory / 'baseline.c'
        baseline.write_bytes(subprocess.check_output(
            ['git', 'show', f'{BASELINE}:llvm-nosuz16/examples/othello.c'], cwd=ROOT))
        harness = directory / 'harness.c'
        harness.write_text(HARNESS)
        engines = {}
        try:
            for name, source in [('new', ROOT / 'llvm-nosuz16/examples/othello.c'),
                                 ('old', baseline)]:
                binary = directory / name
                subprocess.run(['cc', '-O2', '-I', str(ROOT / 'llvm-nosuz16/include'),
                                f'-DOTHELLO_SOURCE="{source}"', str(harness), '-o', str(binary)],
                               check=True, timeout=60)
                engines[name] = subprocess.Popen([binary], stdin=subprocess.PIPE,
                                                  stdout=subprocess.PIPE, text=True)
            wins = draws = losses = 0
            for seed in range(4):
                for new_color in (1, 2):
                    board = [[0] * 8 for _ in range(8)]
                    board[3][3] = board[4][4] = 2
                    board[3][4] = board[4][3] = 1
                    player, passes, ply = 1, 0, 0
                    rng = random.Random(seed)
                    while passes < 2:
                        legal = moves(board, player)
                        if not legal:
                            passes += 1
                        else:
                            passes = 0
                            if ply < 4:
                                move = rng.choice(list(legal))
                            else:
                                name = 'new' if player == new_color else 'old'
                                engine = engines[name]
                                cells = ''.join(str(0 if not p else 2 if p == player else 1)
                                                for row in board for p in row)
                                engine.stdin.write(cells + '\n')
                                engine.stdin.flush()
                                reply = engine.stdout.readline()
                                assert reply, f'{name} failed or did not restore its board'
                                square = int(reply)
                                move = (square // 10 - 1, square % 10 - 1)
                                assert move in legal, f'{name} selected an illegal move'
                            board = apply(board, move, legal[move], player)
                            ply += 1
                        player = 3 - player
                    ours = sum(row.count(new_color) for row in board)
                    theirs = sum(row.count(3 - new_color) for row in board)
                    wins += ours > theirs
                    draws += ours == theirs
                    losses += ours < theirs
                    print(f'seed={seed} new={"X" if new_color == 1 else "O"}: {ours}-{theirs}')
            print(f'New engine: {wins} wins, {draws} draws, {losses} losses against {BASELINE}')
            assert wins > losses, 'New engine did not outperform the baseline in this suite'
        finally:
            for engine in engines.values():
                engine.stdin.close()
                try:
                    engine.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    engine.kill()
                    engine.wait()
                assert engine.returncode == 0, 'Native engine failed'


if __name__ == '__main__':
    main()
