.text
.p2align 2
.globl _wide_add_shift
_wide_add_shift:
  add x0,x0,#1,lsl #12
  ret
.p2align 2
.globl _wide_shift63
_wide_shift63:
  add x0,x0,x1,lsl #63
  ret
.p2align 2
.globl _wide_movk48
_wide_movk48:
  mov x8,#0x1234
  movk x8,#0xabcd,lsl #48
  eor x0,x0,x8
  ret
.p2align 2
.globl _wide_add_carry
_wide_add_carry:
  adds x8,x0,x1
  csel x0,x2,x3,hs
  ret
.p2align 2
.globl _wide_add_overflow
_wide_add_overflow:
  adds x8,x0,x1
  csel x0,x2,x3,vs
  ret
.p2align 2
.globl _wide_sub_carry
_wide_sub_carry:
  subs x8,x0,x1
  csel x0,x2,x3,lo
  ret
.p2align 2
.globl _wide_sub_signed
_wide_sub_signed:
  subs x8,x0,x1
  csel x0,x2,x3,le
  ret
.p2align 2
.globl _wide_logic_flags
_wide_logic_flags:
  ands x8,x0,x1
  csel x0,x2,x3,mi
  ret
.p2align 2
.globl _wide_w_flags
_wide_w_flags:
  adds w8,w0,w1
  csel x0,x2,x3,hs
  ret
.p2align 2
.globl _wide_w_cmp
_wide_w_cmp:
  cmp w0,w1
  csel x0,x2,x3,lt
  ret
.p2align 2
.globl _wide_w_zeroext
_wide_w_zeroext:
  mov w8,w0
  add x0,x8,x1
  ret
.p2align 2
.globl _wide_w_movk
_wide_w_movk:
  mov w8,w0
  movk x8,#0xdead,lsl #48
  eor x0,x8,x1
  ret
.p2align 2
.globl _wide_w_rotate
_wide_w_rotate:
  ror w8,w0,w1
  eor x0,x8,x2
  ret
.p2align 2
.globl _wide_w_arithmetic
_wide_w_arithmetic:
  asr w8,w0,w1
  add x0,x8,x2
  ret
.p2align 2
.globl _wide_x_variable_shift
_wide_x_variable_shift:
  lsr x0,x0,x1
  ret
.p2align 2
.globl _wide_x_rotate
_wide_x_rotate:
  ror x0,x0,x1
  ret
.p2align 2
.globl _wide_ubfx_high
_wide_ubfx_high:
  ubfx x0,x0,#40,#24
  ret
.p2align 2
.globl _wide_bfxil_high
_wide_bfxil_high:
  bfxil x0,x1,#40,#24
  ret
.p2align 2
.globl _wide_bfxil_full
_wide_bfxil_full:
  bfxil x0,x1,#0,#64
  ret
.p2align 2
.globl _wide_bfi_high
_wide_bfi_high:
  bfi x0,x1,#40,#24
  ret
.p2align 2
.globl _wide_bfi_one
_wide_bfi_one:
  bfi x0,x1,#63,#1
  ret
.p2align 2
.globl _wide_w_bfi
_wide_w_bfi:
  bfi w0,w1,#16,#16
  ret
.p2align 2
.globl _wide_rbit
_wide_rbit:
  rbit x0,x0
  ret
.p2align 2
.globl _wide_linear
_wide_linear:
  eor x8,x0,x1,ror #17
  eor x0,x8,x2,lsr #7
  ret
