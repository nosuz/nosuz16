#include "nosuz16.h"

/* X moves first; the player chooses whether the human or CPU owns X.
 * The CPU uses bounded iterative-deepening alpha-beta search.
 * A sentinel border makes all eight directions safe without row wrapping.
 * Helpers have external linkage to retain the supported C calling convention.
 * Shared helpers and disabled loop unrolling keep the image within 64 KiB. */
#define EMPTY 0
#define HUMAN 1
#define COMPUTER 2
#define BORDER 3

/* Observable byte accesses prevent unsupported wide load/store merging. */
static volatile char board[100];
static char human_symbol = 'X', cpu_symbol = 'O';
static const short directions[8] = {-11, -10, -9, -1, 1, 9, 10, 11};

/* Shared string output avoids expanding each literal into many UART calls. */
__attribute__((noinline)) void text(const char *message) {
  while (*message) putc(*message++);
}

__attribute__((noinline)) void copy_board(volatile char *destination, const volatile char *source) {
  int i;
  #pragma clang loop unroll(disable)
  for (i = 0; i < 100; ++i) destination[i] = source[i];
}

__attribute__((noinline)) void initialize_board(void) {
  int row, column, i;
  #pragma clang loop unroll(disable)
  for (i = 0; i < 100; ++i) board[i] = BORDER;
  #pragma clang loop unroll(disable)
  for (row = 1; row <= 8; ++row)
    #pragma clang loop unroll(disable)
    for (column = 1; column <= 8; ++column)
      board[row * 10 + column] = EMPTY;
  /* O starts on d4/e5 and X on e4/d5, regardless of who controls them. */
  board[44] = board[55] = human_symbol == 'X' ? COMPUTER : HUMAN;
  board[45] = board[54] = human_symbol == 'X' ? HUMAN : COMPUTER;
}

/* With apply=0, count flips without changing anything. */
__attribute__((noinline)) int play_move(int square, int player, int apply) {
  int direction, total = 0;
  if (board[square] != EMPTY) return 0;
  #pragma clang loop unroll(disable)
  for (direction = 0; direction < 8; ++direction) {
    int step = directions[direction];
    int next = square + step;
    int count = 0;
    while (board[next] == 3 - player) {
      ++count;
      next += step;
    }
    if (count && board[next] == player) {
      total += count;
      if (apply) {
        next = square + step;
        while (count--) {
          board[next] = (char)player;
          next += step;
        }
      }
    }
  }
  if (total && apply) board[square] = (char)player;
  return total;
}

__attribute__((noinline)) int has_move(int player) {
  int row, column;
  #pragma clang loop unroll(disable)
  for (row = 1; row <= 8; ++row)
    #pragma clang loop unroll(disable)
    for (column = 1; column <= 8; ++column)
      if (play_move(row * 10 + column, player, 0)) return 1;
  return 0;
}

/* Bounded iterative deepening: retain the last fully searched result. */
#define SEARCH_NODES 3000
#define SEARCH_DEPTH 4
#define WIN_SCORE 20000
static unsigned int search_nodes;
static int search_aborted;
static const short corners[4] = {11, 18, 81, 88};
static const short corner_steps[8] = {1, 10, -1, 10, 1, -10, -1, -10};

__attribute__((noinline)) int empty_count(void) {
  int row, column, count = 0;
  #pragma clang loop unroll(disable)
  for (row = 1; row <= 8; ++row) {
    #pragma clang loop unroll(disable)
    for (column = 1; column <= 8; ++column)
      count += board[row * 10 + column] == EMPTY;
  }
  return count;
}

/* CPU perspective. Mobility and few frontier discs matter early; disc
 * count matters late. Corner-adjacent penalties apply only to empty corners.
 * Unbroken edge runs anchored at an owned corner are permanently stable. */
__attribute__((noinline)) int evaluate_board(void) {
  int row, column, direction, score = 0, discs = 0, empty = 0;
  int mobility = 0, frontier = 0;
  #pragma clang loop unroll(disable)
  for (row = 1; row <= 8; ++row) {
    #pragma clang loop unroll(disable)
    for (column = 1; column <= 8; ++column) {
      int square = row * 10 + column;
      int piece = board[square];
      if (!piece) {
        ++empty;
        mobility += (play_move(square, COMPUTER, 0) != 0) -
                    (play_move(square, HUMAN, 0) != 0);
      } else {
        int sign = piece == COMPUTER ? 1 : -1;
        discs += sign;
        #pragma clang loop unroll(disable)
        for (direction = 0; direction < 8; ++direction) {
          if (board[square + directions[direction]] == EMPTY) {
            frontier += sign;
            break;
          }
        }
      }
    }
  }
  #pragma clang loop unroll(disable)
  for (direction = 0; direction < 4; ++direction) {
    int corner = corners[direction];
    int horizontal = corner_steps[2 * direction];
    int vertical = corner_steps[2 * direction + 1];
    int owner = board[corner];
    if (!owner) {
      int piece = board[corner + horizontal + vertical];
      if (piece) score += piece == COMPUTER ? -120 : 120;
      piece = board[corner + horizontal];
      if (piece) score += piece == COMPUTER ? -40 : 40;
      piece = board[corner + vertical];
      if (piece) score += piece == COMPUTER ? -40 : 40;
    } else {
      int sign = owner == COMPUTER ? 1 : -1;
      int next;
      score += sign * 400;
      next = corner + horizontal;
      while (board[next] == owner) { score += sign * 30; next += horizontal; }
      next = corner + vertical;
      while (board[next] == owner) { score += sign * 30; next += vertical; }
    }
  }
  return score + mobility * 25 - frontier * 8 + discs * (empty <= 12 ? 12 : 1);
}

__attribute__((noinline)) int terminal_score(void) {
  int row, column, discs = 0;
  #pragma clang loop unroll(disable)
  for (row = 1; row <= 8; ++row) {
    #pragma clang loop unroll(disable)
    for (column = 1; column <= 8; ++column) {
      int piece = board[row * 10 + column];
      discs += (piece == COMPUTER) - (piece == HUMAN);
    }
  }
  return discs > 0 ? WIN_SCORE + discs : discs < 0 ? -WIN_SCORE + discs : 0;
}

/* Sort legal moves: corners, ordinary squares, then dangerous neighbors.
 * Stable insertion ordering gives deterministic ties in row order. */
__attribute__((noinline)) int ordered_moves(char *moves, int player) {
  char ranks[64];
  int row, column, count = 0;
  #pragma clang loop unroll(disable)
  for (row = 1; row <= 8; ++row) {
    #pragma clang loop unroll(disable)
    for (column = 1; column <= 8; ++column) {
      int square = row * 10 + column;
      if (play_move(square, player, 0)) {
        int rank = 2, index = count, corner;
        #pragma clang loop unroll(disable)
        for (corner = 0; corner < 4; ++corner) {
          int c = corners[corner];
          int h = corner_steps[2 * corner], v = corner_steps[2 * corner + 1];
          if (square == c) rank = 3;
          else if (!board[c] && (square == c + h || square == c + v || square == c + h + v))
            rank = 1;
        }
        while (index > 0 && ranks[index - 1] < rank) {
          ranks[index] = ranks[index - 1];
          moves[index] = moves[index - 1];
          --index;
        }
        ranks[index] = (char)rank;
        moves[index] = (char)square;
        ++count;
      }
    }
  }
  return count;
}

/* Negamax alpha-beta. A forced pass consumes no move depth; two consecutive
 * passes are terminal even with empty squares remaining. Every applied move
 * is restored, including when the node budget interrupts a search. */
__attribute__((noinline)) int search(int player, int depth, int alpha, int beta, int passed) {
  char moves[64], saved[100];
  int count, index, best = -30000, sign = player == COMPUTER ? 1 : -1;
  if (++search_nodes > SEARCH_NODES) { search_aborted = 1; return 0; }
  count = ordered_moves(moves, player);
  if (!count) {
    if (passed) return sign * terminal_score();
    return -search(3 - player, depth, -beta, -alpha, 1);
  }
  if (!depth) return sign * evaluate_board();
  copy_board(saved, board);
  #pragma clang loop unroll(disable)
  for (index = 0; index < count; ++index) {
    int score;
    play_move(moves[index], player, 1);
    score = -search(3 - player, depth - 1, -beta, -alpha, 0);
    copy_board(board, saved);
    if (search_aborted) return 0;
    if (score > best) best = score;
    if (score > alpha) alpha = score;
    if (alpha >= beta) break;
  }
  return best;
}

__attribute__((noinline)) int choose_cpu_move(void) {
  char moves[64], saved[100];
  int count = ordered_moves(moves, COMPUTER);
  int move, depth, maximum = SEARCH_DEPTH, empty = empty_count();
  if (!count) return 0;
  move = moves[0];
  /* Attempt an exact finish in small endgames, within the same node budget. */
  if (empty <= 8) maximum = empty;
  search_nodes = 0;
  search_aborted = 0;
  copy_board(saved, board);
  #pragma clang loop unroll(disable)
  for (depth = 1; depth <= maximum; ++depth) {
    int index, best = -30000, candidate = move;
    #pragma clang loop unroll(disable)
    for (index = 0; index < count; ++index) {
      int score;
      play_move(moves[index], COMPUTER, 1);
      score = -search(HUMAN, depth - 1, -30000, -best, 0);
      copy_board(board, saved);
      if (search_aborted) break;
      if (score > best) { best = score; candidate = moves[index]; }
    }
    if (search_aborted) break;
    move = candidate;
    /* Search the previous best move first in the next iteration. */
    for (index = 0; moves[index] != move; ++index) {}
    while (index > 0) { moves[index] = moves[index - 1]; --index; }
    moves[0] = (char)move;
  }
  return move;
}

__attribute__((noinline)) void print_score(int human, int cpu) {
  printf("X (%s): %d  O (%s): %d\n",
         human_symbol == 'X' ? "You" : "CPU",
         human_symbol == 'X' ? human : cpu,
         human_symbol == 'O' ? "You" : "CPU",
         human_symbol == 'X' ? cpu : human);
}

__attribute__((noinline)) void print_board(void) {
  int row, column, human = 0, cpu = 0;
  text("\n  a b c d e f g h\n");
  #pragma clang loop unroll(disable)
  for (row = 1; row <= 8; ++row) {
    printf("%d ", row);
    #pragma clang loop unroll(disable)
    for (column = 1; column <= 8; ++column) {
      int piece = board[row * 10 + column];
      putc(piece == HUMAN ? human_symbol : piece == COMPUTER ? cpu_symbol : '.');
      putc(' ');
      human += piece == HUMAN;
      cpu += piece == COMPUTER;
    }
    putc('\n');
  }
  print_score(human, cpu);
}

/* Consume a whole line, including overlong input. UART/terminal echo is
 * left to the terminal; accept LF and CRLF, and optional surrounding spaces. */
__attribute__((noinline)) int read_line(char *line) {
  int length = 0, overflow = 0, byte;
  #pragma clang loop unroll(disable)
  for (;;) {
    byte = getc();
    if (byte == '\n') break;
    if (byte == '\r') continue;
    if (length < 7) line[length++] = (char)byte;
    else overflow = 1;
  }
  line[length] = 0;
  return !overflow;
}

__attribute__((noinline)) int choose_first_player(void) {
  char line[8];
  int i = 0, choice;
  if (!read_line(line)) return -1;
  while (line[i] == ' ' || line[i] == '\t') ++i;
  choice = line[i];
  if (choice != '1' && choice != '2' && choice != 'q' && choice != 'Q')
    return -1;
  ++i;
  while (line[i] == ' ' || line[i] == '\t') ++i;
  if (line[i]) return -1;
  if (choice == 'q' || choice == 'Q') return 0;
  return choice == '1' ? HUMAN : COMPUTER;
}

__attribute__((noinline)) int read_human_move(void) {
  char line[8];
  int byte, i = 0;
  if (!read_line(line)) return -1;
  while (line[i] == ' ' || line[i] == '\t') ++i;
  byte = line[i++];
  if (byte == 'q' || byte == 'Q') {
    while (line[i] == ' ' || line[i] == '\t') ++i;
    return line[i] == 0 ? 0 : -1;
  }
  if (byte >= 'A' && byte <= 'H') byte += 'a' - 'A';
  if (byte < 'a' || byte > 'h') return -1;
  if (line[i] < '1' || line[i] > '8') return -1;
  int square = (line[i++] - '0') * 10 + byte - 'a' + 1;
  while (line[i] == ' ' || line[i] == '\t') ++i;
  return line[i] == 0 ? square : -1;
}

int main(void) {
  int player, passes = 0;
  text("Othello: X moves first.\n"
         "Enter a move such as d3, then Enter. Enter q to quit.\n");
  #pragma clang loop unroll(disable)
  for (;;) {
    text("Who moves first? 1 = human, 2 = CPU: ");
    player = choose_first_player();
    if (!player) { text("Goodbye.\n"); return 0; }
    if (player > 0) break;
    text("Choose 1 or 2, or q to quit.\n");
  }
  human_symbol = player == HUMAN ? 'X' : 'O';
  cpu_symbol = player == COMPUTER ? 'X' : 'O';
  printf("You are %c. CPU is %c.\n", human_symbol, cpu_symbol);
  initialize_board();
  print_board();
  while (passes < 2) {
    if (!has_move(player)) {
      text(player == HUMAN ? "Human passes.\n" : "CPU passes.\n");
      ++passes;
    } else {
      int move;
      passes = 0;
      if (player == HUMAN) {
        #pragma clang loop unroll(disable)
        for (;;) {
          text("Your move: ");
          move = read_human_move();
          if (!move) { text("Goodbye.\n"); return 0; }
          if (move > 0 && play_move(move, player, 1)) break;
          text("Invalid move. Use an empty square that flips CPU discs.\n");
        }
      } else {
        move = choose_cpu_move();
        play_move(move, player, 1);
        printf("CPU plays %c%d.\n", 'a' + move % 10 - 1, move / 10);
      }
      print_board();
    }
    player = 3 - player;
  }
  int i, human = 0, cpu = 0;
  #pragma clang loop unroll(disable)
  for (i = 0; i < 100; ++i) {
    human += board[i] == HUMAN;
    cpu += board[i] == COMPUTER;
  }
  text("Game over. ");
  print_score(human, cpu);
  text(human > cpu ? "You win!\n" : human < cpu ? "CPU wins.\n" : "Draw.\n");
  return 0;
}
