#include "nosuz16.h"

/* X moves first; the player chooses whether the human or CPU owns X.
 * The CPU searches a move and the opponent's reply.
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

/* Score from the CPU's perspective: corners are valuable, their adjacent
 * squares risky. Near the end, favor the final number of discs instead. */
__attribute__((noinline)) int evaluate_board(void) {
  int row, column, score = 0, discs = 0, empty = 0;
  #pragma clang loop unroll(disable)
  for (row = 1; row <= 8; ++row) {
    #pragma clang loop unroll(disable)
    for (column = 1; column <= 8; ++column) {
      int piece = board[row * 10 + column];
      int weight = 2;
      if (!piece) { ++empty; continue; }
      if (row == 1 || row == 8) {
        weight = 10;
        if (column == 1 || column == 8) weight = 100;
        else if (column == 2 || column == 7) weight = -25;
      } else if (column == 1 || column == 8) {
        weight = (row == 2 || row == 7) ? -25 : 10;
      } else if ((row == 2 || row == 7) &&
                 (column == 2 || column == 7)) weight = -40;
      if (piece == COMPUTER) { score += weight; ++discs; }
      else { score -= weight; --discs; }
    }
  }
  return empty <= 8 ? discs * 100 + score : score;
}

__attribute__((noinline)) int opponent_reply_score(void) {
  char saved[100];
  int row, column, worst = 30000, found = 0;
  copy_board(saved, board);
  #pragma clang loop unroll(disable)
  for (row = 1; row <= 8; ++row) {
    #pragma clang loop unroll(disable)
    for (column = 1; column <= 8; ++column) {
      if (play_move(row * 10 + column, HUMAN, 1)) {
        int score = evaluate_board();
        if (score < worst) worst = score;
        found = 1;
        copy_board(board, saved);
      }
    }
  }
  return found ? worst : evaluate_board();
}

__attribute__((noinline)) int choose_cpu_move(void) {
  char saved[100];
  int row, column, best = -30000, move = 0;
  copy_board(saved, board);
  #pragma clang loop unroll(disable)
  for (row = 1; row <= 8; ++row) {
    #pragma clang loop unroll(disable)
    for (column = 1; column <= 8; ++column) {
      int square = row * 10 + column;
      if (play_move(square, COMPUTER, 1)) {
        int score = opponent_reply_score();
        if (score > best) { best = score; move = square; }
        copy_board(board, saved);
      }
    }
  }
  return move;
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
  printf("X (%s): %d  O (%s): %d\n",
         human_symbol == 'X' ? "You" : "CPU",
         human_symbol == 'X' ? human : cpu,
         human_symbol == 'O' ? "You" : "CPU",
         human_symbol == 'X' ? cpu : human);
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
  printf("Game over. X (%s): %d  O (%s): %d. %s\n",
         human_symbol == 'X' ? "You" : "CPU",
         human_symbol == 'X' ? human : cpu,
         human_symbol == 'O' ? "You" : "CPU",
         human_symbol == 'X' ? cpu : human,
         human > cpu ? "You win!" : human < cpu ? "CPU wins." : "Draw.");
  return 0;
}
