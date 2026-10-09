# Nosuz16 CPU 仕様書 v2.5

## 概要

教育・趣味用途向けの16bit CPU。命令とwordデータは16bit、アドレスの単位は8bit byte。

設計目標：

- FPGA/TTLで実装しやすい
- 固定長命令による単純なデコード
- 小規模回路で構築可能
- コンパイラを作りやすい
- 数値計算やゲームが実装可能
- RISC的な最小命令セット
- 16bit byte addressによるCと互換性のあるメモリモデル

本書はコアISA、標準ABI、および参照マシンプロファイルを定義する。
デバイス、SYSTEM命令、初期メモリは参照プロファイルの規則であり、
異なるプラットフォームはその差異を明記する。

## v2.4からの変更

- PC、SP、データポインタを含む全アドレスを16bit byte addressに統一。
- 統一アドレス空間を64 KiB（32768 physical words）とし、17bitアドレスは導入しない。
- little-endianを定義し、8bit charを1 byte、16bit intとポインタを2 byteに格納。
- PCの通常の増分と戻りアドレスを+2 byteに変更。
- LD/ST/JALRのimm6はbyte単位。相対分岐/JALは2 byte単位の変位を維持。
- LDB/STBをopcode 9/Aに追加し、コア命令数を20に変更。
- 命令フェッチ、LD/ST、JALRの奇数アドレスに対するalignment faultを定義。
- ABIのスタック操作を2 byte単位に変更。
- N16-REF-2を定義。UART DATAをFF00h、STATUSをFF02h、VIDEO DATAをFF10hに配置。
- イメージのload/entry addressをbyte単位に変更。BINの奇数byte長も許可。

ALUのopcode/funcと既存命令のencodingは維持するが、アドレスの意味と一部の
即値単位が変わるため、v2.4の機械語、オブジェクト、イメージはバイナリ互換ではない。
旧byte-per-word Cプロファイルは廃止する。v2.5向けに再コンパイルが必要。

**実装状態：Rustエミュレータと実験的LLVM/Clangバックエンドはv2.5のbyte addressingに
対応済み。コンパイラの対応範囲・制限と検証手順はllvm-nosuz16/README.mdを参照。**

---

# 基本構成

| 項目 | 内容 |
| --- | --- |
| CPU種別 | 16bit CPU |
| 命令長 | 16bit固定長 |
| wordデータ長・推奨メモリbus幅 | 16bit |
| PC・アドレス幅 | 16bit |
| アドレス単位 | 8bit byte |
| byte access | LDB/STB |
| メモリ構成 | Unified memory |
| CPUのエンディアン | little-endian |
| ALU | 16bit |
| レジスタ数 | 8本 |
| 符号付き整数 | 16bit 2の補数、-32768～32767 |

# メモリ・数値モデル

```text
0000h - FFFFh : 65536 bytes = 64 KiB = 32768 words
1 address = 1 byte
1 instruction / 1 word = 2 bytes
```

命令、データ、I/Oは同じbyteアドレス空間を使う。物理RAMを64K×16で実装しても、
コアから見えるのは下位32K wordsのみであり、残りの64 KiBをアクセスする命令や
bank規約は本仕様に含めない。コード、スタック、データ、I/Oは64 KiBを共有する。

推奨する×16 RAMへの対応は次の通り。word addressを保持する専用アドレスモードを
追加するのではなく、bus上でbyte addressをword位置とlaneに分ける。

```text
physical_word_index = byte_address >> 1      ; 15bit
byte_lane           = byte_address & 1       ; 0=low, 1=high
```

byteアクセスは偶数・奇数のどちらのアドレスにも可能。
命令フェッチと16bit LD/STは偶数アドレスのみ許可する。
RAM wordはlittle-endianで、1234hをアドレスAに格納するとBYTE[A]=34h、
BYTE[A+1]=12hとなる。STBは選択したbyteだけを書き換え、隣のbyteを保存する。
byte write enableを持たないRAMではread-modify-writeで実装してよいが、
I/Oアクセスに余分なデバイス読み取りを発生させてはならない。

演算結果、PCの加算、分岐先、有効アドレスはすべて下位16bitを使用する。
アドレスの加減算はmodulo 65536でwraparoundする。
例：FFFFh+1=0000h、0000h-1=FFFFh。FFFEhの命令実行後のNEXTは0000h。
算術overflowやスタックの範囲外アクセスによる自動trapはない。
alignment faultは後述の規則で実行を中断する。

以降では以下の記号を使用する。

```text
u16(x) = xの下位16bitを符号なし整数として解釈
s16(x) = xの下位16bitを2の補数の符号付き整数として解釈
u8(x)  = xの下位8bitを符号なし整数として解釈
sext6(x) = 6bit値を16bitに符号拡張
sext9(x) = 9bit値を16bitに符号拡張
BYTE[A] = アドレスAの8bit値
WORD[A] = BYTE[A] | (BYTE[u16(A+1)] << 8)   ; Aは偶数
```

WORD/BYTEアクセスにI/Oが含まれる場合は、RAMを2回読むのではなく、参照プロファイルの
幅とlaneに対応したデバイスtransactionとして処理する。

# リセット

| CPU状態 | リセット値 |
| --- | --- |
| PC | 0000h |
| r0-r7 | 0000h |
| Z/C/N/V | 0 |
| HALT状態 | 解除、実行可能 |
| fault状態 | 不正命令・alignment faultの停止状態を解除 |

CPUリセットはメモリを書き換えず、デバイスもリセットしない。
参照マシン全体の初期化規則は後述する。
SPはCPUリセットでは初期化されない。ABIの起動処理が設定する。

# 命令フェッチ・実行順

```text
P  = 命令実行開始時のPC
if P & 1: alignment fault   ; フェッチしない
IR = WORD[P]
```

Pが奇数ならフェッチ前にalignment faultとする。
IRが合法な命令なら、`NEXT = u16(P + 2)` を計算し、
すべてのレジスタ入力と入力フラグを実行前の値から読み取る。
その後、命令に従ってレジスタ、フラグ、メモリ、PCを更新する。
通常の命令の実行後PCはNEXTである。

分岐およびJALの基準はNEXTであり、Pではない。
JAL/JALRが保存する戻りアドレスもNEXTである。
delay slotはなく、自己書き換えした命令は次回のフェッチから有効になる。

# レジスタ

ハードウェアとして特別扱いされるのはr0のみである。

| レジスタ | ハードウェア上の扱い | ABI上の用途 |
| --- | --- | --- |
| r0 | 常に0 | zero |
| r1-r5 | 汎用 | 引数、結果、一時値、保存値 |
| r6 | 汎用 | sp |
| r7 | 汎用 | ra / lr |

r6/r7はハードウェア専用レジスタではなく、役割はABI上の約束である。
r0への書き込みは値の保存だけを破棄する。
ALUのフラグ更新、LD/LDBのメモリ読み取り、デバイスの読み取り副作用、
JAL/JALRの制御移動はr0が書き込み先でも実行する。
`ST r0, [base+imm]` は0000h、`STB r0, [base+imm]` は00hを書き込む。

# フラグ

| フラグ | 内容 |
| --- | --- |
| Z | 16bit演算結果が0なら1 |
| C | 加算のcarry、減算のborrow、シフトで押し出されたbit |
| N | 16bit演算結果のbit 15 |
| V | 符号付き算術のoverflow |

フラグ更新は書き込み先レジスタへの保存前の16bit結果に基づく。

| 命令 | Z/N | C | V |
| --- | --- | --- | --- |
| ADD/ADDC/ADDI | 結果から更新 | 符号なし加算のcarry | 符号付きoverflow |
| SUB/SUBC | 結果から更新 | 符号なし減算のborrow | 符号付きoverflow |
| AND/OR/XOR | 結果から更新 | 0 | 0 |
| SLL | 結果から更新 | 入力のbit 15 | 0 |
| SRL/ASR | 結果から更新 | 入力のbit 0 | 0 |
| LD/ST/LDB/STB/BEQ/BNE/BLT/JAL/JALR | 保存 | 保存 | 保存 |
| 参照プロファイルのHALT | 保存 | 保存 | 保存 |

算術の入力をA、B、実行前CをCinとする。
以下の中間計算は切り捨てずに行い、最後に結果を16bitにする。

```text
ADD/ADDI:
  U = u16(A) + u16(B)
  S = s16(A) + s16(B)
ADDC:
  U = u16(A) + u16(B) + Cin
  S = s16(A) + s16(B) + Cin

加算結果 = u16(U)
C = (U > 65535)
V = (S < -32768 または S > 32767)

SUB/SUBC:
  Bin = SUBなら0、SUBCならCin
  T = u16(B) + Bin
  結果 = u16(u16(A) - T)
  C = (u16(A) < T)
  S = s16(A) - s16(B) - Bin
  V = (S < -32768 または S > 32767)
```

ADDIのBはsext6(imm6)。
SUB/SUBCではC=1が「borrowあり」であり、「borrowなし」ではない。
ADDC/SUBCは更新前のCを入力に使う。
多word演算のcarry/borrow連鎖中に、フラグを変更する命令を挿入してはならない。
分岐はレジスタを直接比較し、フラグを判定しない。

# 命令形式

## ALU形式

```text
15        12 11      9 8       6 5                  0
+-----------+----------+---------+-------------------+
| opcode=0  | rd       | rs      | func              |
+-----------+----------+---------+-------------------+
```

ADD/SUB/ADDC/SUBC/AND/OR/XORはrdとrsの実行前の値を使用する。
SLL/SRL/ASRはrdだけを使用し、rsフィールドを無視する。
アセンブラはシフトのrsフィールドを0にする。
0以外のrsを持つシフトも合法であり、同じ動作をする。

## I形式

```text
15        12 11      9 8       6 5                  0
+-----------+----------+---------+-------------------+
| opcode    | rd       | rs/base | imm6              |
+-----------+----------+---------+-------------------+
```

すべてのI形式のimm6は符号付き2の補数で、範囲は-32～31。
ADDI/LD/ST/LDB/STB/JALRのすべてでsext6する。
LD/ST/LDB/STB/JALRのオフセットの単位はbyte。ADDIの即値自体は整数である。

ADDIは `rd ← rd + imm` の2オペランド命令であり、rsを無視する。
アセンブラはADDIのrsフィールドをrdと同じ値にする。
rsがrdと異なるADDIも合法であり、同じ動作をする。

## B形式

```text
15        12 11      9 8       6 5                  0
+-----------+----------+---------+-------------------+
| opcode    | rs1      | rs2     | offset6           |
+-----------+----------+---------+-------------------+
```

offset6は符号付き2 byte単位のoffset、範囲は-32～31。
NEXTに`2 * sext6(offset6)`を加算する。byte変位の範囲は-64～+62。

## J形式

```text
15        12 11      9 8                            0
+-----------+----------+----------------------------+
| opcode    | rd       | offset9                    |
+-----------+----------+----------------------------+
```

offset9は符号付き2 byte単位のoffset、範囲は-256～255。
NEXTに`2 * sext9(offset9)`を加算する。byte変位の範囲は-512～+510。
rdはリンク保存先であり、通常の呼び出しではABIに従ってr7を使用する。

# Opcode割り当て

| Opcode | 命令/分類 | 命令形式 |
| ---: | --- | --- |
| 0x0 | ALU Group | ALU |
| 0x1 | ADDI | I |
| 0x2 | LD | I |
| 0x3 | ST | I |
| 0x4 | BEQ | B |
| 0x5 | BNE | B |
| 0x6 | BLT | B |
| 0x7 | JAL | J |
| 0x8 | JALR | I |
| 0x9 | LDB | I |
| 0xA | STB | I |
| 0xB-0xE | Reserved、不正命令 | - |
| 0xF | SYSTEM、マシンプロファイルで定義 | SYSTEM |

# ALU Group Function割り当て

| func | 命令 |
| ---: | --- |
| 0x00 | ADD |
| 0x01 | SUB |
| 0x02 | ADDC |
| 0x03 | SUBC |
| 0x04 | AND |
| 0x05 | OR |
| 0x06 | XOR |
| 0x07 | SLL |
| 0x08 | SRL |
| 0x09 | ASR |
| 0x0A-0x3F | Reserved、不正命令 |

# コア命令セット

以下の加減算と格納結果は16bitに切り詰める。
表内のレジスタ右辺はすべて実行前の値。

## 算術・論理命令

| 命令 | 形式 | 動作 |
| --- | --- | --- |
| ADD rd, rs | ALU | rd ← rd + rs |
| SUB rd, rs | ALU | rd ← rd - rs |
| ADDC rd, rs | ALU | rd ← rd + rs + Cin |
| SUBC rd, rs | ALU | rd ← rd - rs - Cin |
| ADDI rd, imm | I | rd ← rd + sext6(imm6) |
| AND rd, rs | ALU | rd ← rd AND rs |
| OR rd, rs | ALU | rd ← rd OR rs |
| XOR rd, rs | ALU | rd ← rd XOR rs |

## シフト命令

シフト数は常に1。rsによる可変シフトではない。

| 命令 | 形式 | 動作 |
| --- | --- | --- |
| SLL rd | ALU | 左に1bit移動、bit 0に0、旧bit 15をCへ |
| SRL rd | ALU | 右に1bit移動、bit 15に0、旧bit 0をCへ |
| ASR rd | ALU | 右に1bit移動、bit 15に旧bit 15、旧bit 0をCへ |

## メモリアクセス命令

```text
A = u16(old_rs + sext6(imm6))
```

| 命令 | 形式 | 動作 |
| --- | --- | --- |
| LD rd, [rs+imm] | I | rd ← WORD[A]。Aは偶数 |
| ST rd, [rs+imm] | I | WORD[A] ← old_rd。Aは偶数 |
| LDB rd, [rs+imm] | I | rd ← u8(BYTE[A])。上位8bitを0にする |
| STB rd, [rs+imm] | I | BYTE[A] ← u8(old_rd)。隣接byteを保存 |

LD/LDBでrd=rsでも、有効アドレスは書き込み前のrsから計算する。
ST/STBでrd=rsなら、同じ実行前のレジスタ値をデータとbaseに使う。
LD/STでAが奇数なら、データアクセスや書き込みを行う前にalignment faultとする。
baseやimmが奇数でも、計算後のAが偶数ならLD/STは合法。

各命令は指定幅のデータtransactionを1回行う。STBのRAM内部read-modify-writeは
外部可観測な別のデバイスtransactionとして扱わない。
LDBは符号拡張しない。signed charの符号拡張はコンパイラがALU命令で行う。
例えばbyte FFhのLDB結果は00FFhで、16bit signed値-1はFFFFhとなる。

## 分岐命令

| 命令 | 形式 | 条件 |
| --- | --- | --- |
| BEQ rs1, rs2, offset | B | rs1 == rs2 |
| BNE rs1, rs2, offset | B | rs1 != rs2 |
| BLT rs1, rs2, offset | B | s16(rs1) < s16(rs2) |

```text
条件成立: PC ← u16(NEXT + 2 * sext6(offset6))
条件不成立: PC ← NEXT
```

## ジャンプ命令

| 命令 | 形式 | 動作 |
| --- | --- | --- |
| JAL rd, offset | J | rd ← NEXT; PC ← u16(NEXT + 2 * sext9(offset9)) |
| JALR rd, rs, imm | I | target ← u16(old_rs + sext6(imm6)); rd ← NEXT; PC ← target |

JALRのold_rsはリンク保存前の値。
例：P=0010h、r7=0200hで `JALR r7, r7, 0` を実行すると、
r7=0012h、PC=0200hとなる。
JALRのtargetが奇数なら、リンクレジスタもPCも更新せずalignment faultとする。

# 命令数

コア命令は20：ALU Groupの10命令と、
ADDI/LD/ST/LDB/STB/BEQ/BNE/BLT/JAL/JALRの10命令。
アセンブラ疑似命令およびプロファイル固有のSYSTEM命令は含めない。
参照プロファイルはさらにHALTを1命令定義する。

# 不正命令

未割り当てopcode/func、および選択したプロファイルで未定義のSYSTEM encodingは不正命令。
命令フェッチ後に不正と判定し、レジスタ、フラグ、PC、データメモリの更新を行わない。
PCは不正命令のアドレスPを保持し、実装は不正命令を報告して通常実行を中断する。
暗黙のNOPとして扱ってはならない。例外ベクタへの分岐は定義しない。

エミュレータはPとIRを含むエラーを返す。
ハードウェアはfault信号等で中断を外部へ通知する。
命令フェッチ自体のデバイス副作用は取り消さない。
外部のリセットやデバッガ操作以外に、自動復帰は行わない。

# Alignment fault

次のいずれかの場合、通常実行を中断してfaultを報告する。

- 命令実行開始時のPCが奇数：命令フェッチを行わない。
- LD/STの有効アドレスが奇数：データbusアクセスを行わない。
- JALRのtargetが奇数：リンクレジスタを含む更新を行わない。

faultではレジスタ、フラグ、PC、データメモリを更新しない。
PCは命令開始時のPを保持する。命令をフェッチ済みの場合、そのフェッチによる
デバイス副作用は取り消さない。エラーにはP、アクセス種別、対象アドレスを含め、
フェッチ済みならIRも含める。エミュレータとハードウェアは不正命令と同様に停止し、
リセットまたは明示的なデバッガ操作まで自動復帰しない。
FFFEhのwordアクセスはFFFEh/FFFFhを使用するため合法。
FFFFhのwordアクセスは0000hへ跨ぐのではなく、奇数アドレスとしてfaultとなる。

# アセンブラ疑似命令（Alias）

| Alias | 展開・制約 |
| --- | --- |
| INC rd | ADDI rd, 1 |
| DEC rd | ADDI rd, -1 |
| SUBI rd, imm | ADDI rd, -imm。入力immの範囲は-31～32 |
| MOV rd, rs | rd≠rsなら `XOR rd, rd`、`ADD rd, rs`。rd=rsなら `ADDI rd, 0` |
| CLR rd | XOR rd, rd |
| NOP | JAL r0, 0。機械語7000h、フラグ保存 |
| RET | JALR r0, r7, 0 |
| JMP label | JAL r0, label |
| CALL label | JAL r7, label |
| CMP rs1, rs2, tmp | MOV tmp, rs1; SUB tmp, rs2。tmpはr0/rs1/rs2と異なるレジスタ |

MOVは元のrsの値をコピーし、Z/Nをその値から更新、C/Vを0にする。
rd=r0の場合はコピーの保存だけを破棄し、フラグは更新する。
MOVは場合により2命令（4 byte）になり、フラグを保存しない。

CMPはtmpを破壊し、フラグを `rs1 - rs2` に基づいて更新する。
rs1/rs2自体は保存する。誤った旧形式 `CMP rd, rs` は受理しない。
フラグ判定の分岐命令は存在しないため、条件分岐だけが目的ならBEQ/BNE/BLTを直接使う。

BEQ/BNE/BLT/JALの数値offsetはNEXTからの2 byte単位の変位であり、
labelはbyteアドレスである。`delta = s16(u16(target - NEXT))`を計算し、
targetとdeltaが偶数であること、delta/2が命令のoffset範囲に入ることを確認する。
例：P=0010h、target=0018hのJALではNEXT=0012h、offset9=3。
JALR/LD/ST/LDB/STBの数値オフセットはbyte単位であり、相対分岐の単位と異なる。

アセンブラは疑似命令展開後の実際のbyte位置でlabelを解決する。
即値、offset、レジスタ、一時レジスタ制約の範囲外はエラーとし、bitの切り捨てで隠さない。
命令labelは偶数に配置し、byteデータの後は必要ならpaddingを入れる。
自動的な長距離ジャンプ展開は標準Aliasには含めない。
遠い呼び出しにはbyte単位のターゲットをレジスタに用意してJALRを使う。

# 標準ABI

## レジスタ規約

| レジスタ | 用途・保存規約 |
| --- | --- |
| r0 | 常に0 |
| r1-r3 | 第1～第3引数、caller-saved |
| r1 | 16bit戻り値。32bit戻り値の下位word |
| r2 | 32bit戻り値の上位word |
| r4-r5 | callee-saved |
| r6 | sp、calleeは呼び出し時の値に復元 |
| r7 | 戻りアドレス、caller-saved |
| Z/C/N/V | caller-saved |

引数の標準単位は16bit word。
第4引数以降は呼び出し時のWORD[sp+0]、WORD[sp+2]…に置き、callerが呼び出し後に解放する。
callerは追加引数を最後の引数から逆順にPUSHする。
8bit引数・戻り値もregisterまたは2 byteの引数slotを使用し、signed charは16bitへ
符号拡張、unsigned charはzero-extendする。_Boolは0または1に正規化する。
plain charの既定の符号は後述のCプロファイルに従う。
32bitなど複数wordの型を引数に渡す規約は言語ABI拡張で別途定義する。
整数は16bit、符号付き整数は2の補数。標準bool値は0または1。
戻り値を持たない関数はr1/r2の値を保証しない。

## スタック・呼び出し

スタックは下向きに伸び、spは現在の先頭のbyteアドレスを指す。
関数呼び出し時とwordアクセス時にspを偶数に揃える。引数・保存レジスタのslotは2 byte。
参照プロファイルの起動処理は、最初の関数呼び出し前にr6=FF00hを設定する。
空スタックのFF00hは上端の次のbyteアドレスであり、最初のPUSHはFEFEh/FEFFhを使う。
CPUリセットがr6=FF00hを自動設定するわけではない。
スタックはコード、データ、I/Oと重ならないようソフトウェアで管理する。

```asm
; PUSH r1
ADDI r6, -2
ST   r1, [r6 + 0]

; POP r1
LD   r1, [r6 + 0]
ADDI r6, 2
```

CALLはr7を書き換える。別の関数を呼ぶcalleeは、自分の戻りアドレスを
呼び出し前にスタック等へ保存し、RET前に復元する。
使用したr4/r5も保存・復元する。
スタックフレームを確保した後は、引数の参照位置をその分だけ調整する。
PUSH/POPのADDIはフラグを変更するため、フラグ保存操作ではない。

# 参照マシンプロファイル N16-REF-2

## 初期化とSYSTEM

マシンの新規作成時、RAMとVIDEOレジスタは0、UART入力・出力キューは空とする。
プログラムイメージのロードはその後に行い、RAMのCPUリセット時クリアは要求しない。
デバイスリセットはUARTキューを空にし、VIDEOレジスタを0にする。
プログラムロードは実行時のbus transactionではなく、デバイス副作用を発生させない。
デバイスアドレスのbacking storageをロードしても、デバイスの読み取り値は上書きしない。
FF10h/FF11hへのロードはVIDEOレジスタ自体の下位/上位byteの初期値を設定する。
片方のbyteだけをロードした場合、もう片方は変更しない。

SYSTEMはopcode=0xF、下位12bitが機能指定。

| 機械語 | 命令 | 動作 |
| --- | --- | --- |
| F000h | HALT | PC←NEXT、フラグ・レジスタ保存、実行停止 |
| F001h-FFFFh | 不正命令 | 不正命令の規則に従う |

HALT中は命令フェッチもデータアクセスも行わず、CPU状態を更新しない。
CPUリセットまたは明示的なデバッガ操作で停止を解除できる。
異なるSYSTEM機能を定義するマシンは、N16-REF-2以外のプロファイル名を使用する。

## メモリマップドI/O

以下のアドレスはすべてbyte単位。各16bitレジスタは偶数baseとその次のbyteを使う。

| byteアドレス | 名前 | wordアクセスの動作 |
| --- | --- | --- |
| FF00h–FF01h | UART DATA | LDは受信byteを1個消費してzero-extend。STは下位8bitを送信 |
| FF02h–FF03h | UART STATUS | 読み取り専用status。書き込みは無視 |
| FF10h–FF11h | VIDEO DATA | 16bit読み書き可能なデータレジスタ |
| その他 | RAM | 通常のlittle-endian byte/word読み書き |

デバイスの範囲は同じアドレスのRAMアクセスを置き換える。
LDB/STBのlane動作は次の通りであり、余分なword読み取りを行わない。

| byteアドレス | LDB | STB |
| --- | --- | --- |
| FF00h | 受信byteを1個消費、空なら0 | 下位8bitを1 byte送信 |
| FF01h | 0、受信を消費しない | 無視、送信しない |
| FF02h | STATUSの下位byte | 無視 |
| FF03h | 0 | 無視 |
| FF10h | VIDEOの下位byte | VIDEOの下位byteのみ変更 |
| FF11h | VIDEOの上位byte | VIDEOの上位byteのみ変更 |

UART DATAの読み取り：

- LD FF00hまたはLDB FF00hは、入力キューが非空なら先頭の1 byteを消費して返す。
- 入力キューが空なら0を返し、何も消費しない。
- NUL受信と空キューの区別は、読み取り前のSTATUSで行う。
- LDB FF01hは常に0を返し、DATA読み取りの副作用を起こさない。

UART DATAの書き込み：

- ST FF00hまたはSTB FF00hはレジスタの下位8bitだけを出力へ追加する。
- ST FF00hの上位8bitとSTB FF01hは送信しない。
- 参照プロファイルの送信は常に受理可能。満杯、待ち時間、送信完了割り込みはモデル化しない。

UART STATUS：

| bit | 意味 |
| --- | --- |
| 0 | RX_READY：受信キューが非空なら1 |
| 1 | TX_READY：常に1 |
| 15:2 | 常に0 |

VIDEO DATAは最後に書き込んだ16bit値を読み返すレジスタ。
bit 15:0はアプリケーション定義のデータであり、N16-REF-2は画素形式、画面寸法、
フレームバッファ、描画処理を定義しない。画像表示機能が必要なマシンは、
別のプロファイルでそのフォーマットとアドレス配置を定義する。

命令フェッチも同じ16bit bus読み取りを使う。
FF00hからのフェッチは受信byteを消費し、その値を命令としてデコードする。
ソフトウェアは意図しないデバイス副作用を避けるためI/O上で命令を実行しない。
デバイスのtimingや実際のUART通信速度はISAには含めない。

## プログラムイメージ

- HEX：16bitの16進wordを空白または改行で区切る。`0x`/`0X` prefixを許可。
  `#`、`;`、`//`から行末まではコメント。符号や桁区切りは許可しない。
  各wordを下位byte、上位byteの順に連続した2 byteへロードする。load addressは偶数。
- BIN：RAM byte列をそのまま保存する。16bit値と命令はlittle-endian。
  byteデータを含むためファイル長が奇数でも合法。最後のbyteに暗黙のpaddingを加えない。
- load addressとentry addressはbyte単位で、イメージ外のツール設定として指定する。
  指定がない場合はload address=0000h、entry address=load address。
- entry addressは偶数。BINのload addressは奇数でもよいが、その場合は偶数entryを明示する。
- `load address + byte長 > 65536`のイメージはエラー。ロード時はwraparoundしない。
- 参照ランナーは空イメージをエラーとする。実行時のRAM範囲外保護は追加しない。
- 起動コードはFF00hより下にスタック用RAMを確保し、イメージとスタックを重ねない。

# 乗算・割り込み・用途

ハードウェア乗算器は持たず、必要ならソフトウェアで実装する。
例： `CALL __mul16`。ターゲットがJALの到達範囲外ならJALRを使用する。
割り込みはv2.5でも未実装。

想定用途：モニタプログラム、Tiny BASIC、自作言語、ゲーム、
マンデルブロ集合、教育、小規模OS。
想定実装：FPGA、CPLD + SRAM、TTL。

# 設計思想

16bitレジスタと固定長命令を維持し、メモリはbyte単位でアドレス指定する。
charを2個ずつwordへ格納でき、16bit intとポインタは1 physical wordに収まる。
64 KiBの統一アドレス空間に制限することで、17bitアドレスやbankレジスタを不要にする。

```text
1 address = 1 byte
1 instruction = 2 bytes
PC += 2
```

# Clang Cメモリプロファイル（packed byte）

| C型 | C上の幅 | sizeof（byte） | alignment（byte） |
| --- | --- | --- | --- |
| char / signed char / unsigned char | 8bit | 1 | 1 |
| _Bool | 0または1 | 1 | 1 |
| int / unsigned int | 16bit | 2 | 2 |
| オブジェクト・関数ポインタ | 16bit byte address | 2 | 2 |

`CHAR_BIT`は8。charはbyte laneの8bit全部を使用し、隣のbyteも別のcharやデータに
使用する。char格納時に隣のbyteを0にしてはならない。LDB結果の上位8bitは0だが、
signed charを16bitへ変換するときはbit 7を符号拡張する。
plain charは既定でsigned charと同じ範囲（-128～127）とする。
unsigned charの範囲は0～255。コンパイラがplain charのunsigned設定を提供する場合は
全translation unitで同じ設定を使用する。

intとポインタは通常、偶数アドレスの1 physical wordへ格納する。
1234hは同じwordの下位byte 34h、上位byte 12hであり、2 physical wordsに分割しない。
ポインタの数値はCPU byte addressと一致する。`char *p`の`p+1`は1 byte先、
`int *p`の`p+1`は2 byte先。null pointerの表現は0000hで、dereferenceはCの未定義動作。

配列stride、構造体offset、padding、sizeofは通常の8bit byteを使うCレイアウト。
通常のint/pointerロードとストアはLD/STを使い、charはLDB/STBを使う。
packed構造体などの奇数アドレスにあるint/pointerは、2回のLDB/STBとALU操作で扱う。
これはRAM中のオブジェクト用の規則であり、I/Oの副作用を持つレジスタに対して
2回のbyteアクセスが1回のwordアクセスと同じ意味になるとは限らない。

Cの自動変数、グローバル、spill、ABI引数slotは同じpacked byteメモリを使う。
spと戻りアドレスもbyte addressであり、呼び出し時はspを2 byteに揃える。
コンパイラ、エミュレータ、アセンブラ、リンカ、ランタイム、起動コードはこの規則へ
移行する必要がある。旧v2.4オブジェクトや旧byte-per-word表現を混在させない。

# v2.5移行時の検証例

以下はエミュレータ、アセンブラ、コンパイラのv2.5対応を確認する代表的な検証条件である。

| 操作・条件 | 期待される結果 |
| --- | --- |
| STでA=1000hに1234hを格納 | BYTE[1000h]=34h、BYTE[1001h]=12h |
| 上記のRAMにLDBを実行 | 1000hから0034h、1001hから0012hを取得 |
| STBでA=1001hに00ABhを格納 | WORD[1000h]=AB34h、下位byteは保存 |
| LD/STのA=1001h | alignment fault、データbusアクセスなし |
| P=1000hでJAL r7,1 | r7=1002h、PC=1004h |
| P=1000hでBEQ r0,r0,-1 | PC=1000h |
| JALRのtarget=1001h | alignment fault、リンクレジスタも更新しない |
| P=FFFEhでNOP | PC=0000h、フラグ保存 |
| sp=FF00hから1234hをPUSH | sp=FEFEh、BYTE[FEFEh]=34h、BYTE[FEFFh]=12h |
| LDB FF01h（UART DATAの上位lane） | 0を返し、受信byteを消費しない |

encoding例：`LDB r1,[r2-1]`は92BFh、`STB r3,[r4+1]`はA701h。
