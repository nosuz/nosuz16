#!/usr/bin/env python3
"""Compile Othello and compare a complete game with independent board rules."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DIRECTIONS = [(r, c) for r in (-1, 0, 1) for c in (-1, 0, 1) if r or c]


def moves(board, player):
    result = {}
    for r in range(8):
        for c in range(8):
            if board[r][c]:
                continue
            flipped = []
            for dr, dc in DIRECTIONS:
                rr, cc = r + dr, c + dc
                ray = []
                while 0 <= rr < 8 and 0 <= cc < 8 and board[rr][cc] == 3 - player:
                    ray.append((rr, cc))
                    rr, cc = rr + dr, cc + dc
                if ray and 0 <= rr < 8 and 0 <= cc < 8 and board[rr][cc] == player:
                    flipped.extend(ray)
            if flipped:
                result[r, c] = flipped
    return result


def apply(board, move, flipped, player):
    result = [row[:] for row in board]
    for r, c in [move] + flipped:
        result[r][c] = player
    return result


def evaluate(board):
    score = discs = empty = 0
    for r, row in enumerate(board):
        for c, piece in enumerate(row):
            if not piece:
                empty += 1
                continue
            edge_r, edge_c = r in (0, 7), c in (0, 7)
            near_r, near_c = r in (1, 6), c in (1, 6)
            if edge_r and edge_c:
                weight = 100
            elif (edge_r and near_c) or (edge_c and near_r):
                weight = -25
            elif edge_r or edge_c:
                weight = 10
            elif near_r and near_c:
                weight = -40
            else:
                weight = 2
            sign = 1 if piece == 2 else -1
            score += sign * weight
            discs += sign
    return score + (100 * discs if empty <= 8 else 0)


def cpu_move(board, legal):
    best, selected = -30000, None
    for move, flipped in legal.items():
        after = apply(board, move, flipped, 2)
        replies = moves(after, 1)
        score = min(evaluate(apply(after, reply, flips, 1))
                    for reply, flips in replies.items()) if replies else evaluate(after)
        if score > best:
            best, selected = score, move
    return selected


def reference(first=1):
    board = [[0] * 8 for _ in range(8)]
    board[3][3] = board[4][4] = 3 - first
    board[3][4] = board[4][3] = first
    states, inputs, events = [[row[:] for row in board]], [], []
    player, passes = first, 0
    while passes < 2:
        legal = moves(board, player)
        if not legal:
            events.append('Human passes.' if player == 1 else 'CPU passes.')
            passes += 1
        else:
            passes = 0
            # Taking the last legal human move exercises forced CPU passes.
            move = list(legal)[-1] if player == 1 else cpu_move(board, legal)
            label = chr(ord('a') + move[1]) + str(move[0] + 1)
            if player == 1:
                inputs.append(label + '\n')
            else:
                events.append('CPU plays ' + label + '.')
            board = apply(board, move, legal[move], player)
            states.append(board)
        player = 3 - player
    human = sum(row.count(1) for row in board)
    cpu = sum(row.count(2) for row in board)
    winner = 'You win!' if human > cpu else 'CPU wins.' if human < cpu else 'Draw.'
    # The rules/search use owner IDs; displayed boards use X=1, O=2.
    colors = {0: 0, first: 1, 3 - first: 2}
    states = [[[colors[piece] for piece in row] for row in state] for state in states]
    x, o = (human, cpu) if first == 1 else (cpu, human)
    x_owner, o_owner = ('You', 'CPU') if first == 1 else ('CPU', 'You')
    ending = f'Game over. X ({x_owner}): {x}  O ({o_owner}): {o}. {winner}'
    return str(first) + '\n' + ''.join(inputs), states, events, ending


def rendered_boards(output):
    blocks = re.findall(r'  a b c d e f g h\n((?:[1-8] [XO. ]+\n){8})', output)
    return [[[{'.': 0, 'X': 1, 'O': 2}[p] for p in line[2:].split()]
             for line in block.splitlines()] for block in blocks]


def main():
    emulator = Path(os.environ.get('NOSUZ16_EMULATOR') or shutil.which('nosuz16')
                    or ROOT / 'nosuz16/target/release/nosuz16')
    with tempfile.TemporaryDirectory(prefix='nosuz16-othello-') as temporary:
        image = Path(temporary) / 'othello.bin'
        subprocess.run([ROOT / 'llvm-nosuz16/scripts/compile-c.sh',
                        ROOT / 'llvm-nosuz16/examples/othello.c', image], check=True, timeout=120)
        assert image.stat().st_size < 60000, 'Insufficient room for the search stack'

        def run(arguments, input=None):
            result = subprocess.run([emulator, '--dump', '--max-steps', '2000000000',
                                     *arguments, image], input=input, capture_output=True,
                                    text=True, check=True, timeout=120)
            assert 'r1=0000' in result.stderr and 'r6=FF00' in result.stderr, result.stderr
            assert 'halted=true faulted=false' in result.stderr, result.stderr
            return result.stdout

        for first in (1, 2):
            inputs, states, events, ending = reference(first)
            if first == 1:
                assert sum('passes' in event for event in events) > 2
            output = run(['--uart-input', inputs])
            assert rendered_boards(output) == states, 'Board/flipping mismatch'
            scores = [(sum(row.count(1) for row in state), sum(row.count(2) for row in state))
                      for state in states]
            owners = ('You', 'CPU') if first == 1 else ('CPU', 'You')
            score_lines = re.findall(r'^X \((You|CPU)\): (\d+)  O \((You|CPU)\): (\d+)$', output, re.M)
            assert all((x_owner, o_owner) == owners for x_owner, _, o_owner, _ in score_lines)
            displayed = [(int(x), int(o)) for _, x, _, o in score_lines]
            assert displayed == scores, 'Displayed X/O scores mismatch'
            roles = 'You are X. CPU is O.' if first == 1 else 'You are O. CPU is X.'
            assert roles in output, 'Incorrect color assignment'
            if first == 2:
                assert states[1][2][3] == 1, 'CPU must open as X at d3'
            assert re.findall(r'(?:CPU plays [a-h][1-8]\.|(?:Human|CPU) passes\.)', output) == events
            assert ending in output, 'Wrong final score or winner'
        short_input = 'invalid\n 1 \r\n\na1\nz9\nd3extra-long\n D3 \r\nq\n'
        short = run(['--uart-input', short_input])
        assert short.count('Invalid move.') == 4, short
        assert len(rendered_boards(short)) == 3 and 'CPU plays c3.' in short, short
        assert short.endswith('Your move: Goodbye.\n'), short
        assert 'Choose 1 or 2, or q to quit.' in short
        assert run([], input='q\n').endswith('Goodbye.\n')
        live = run([], input=short_input)
        assert live == short, 'Live stdin differs from queued UART input'
        print('PASS Othello: complete games with both starting players, every board, '
              'CPU replies, passes, final score, invalid input, CRLF, quit, and default stdin')


if __name__ == '__main__':
    main()
