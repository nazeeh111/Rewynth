.text
.p2align 2
.globl _immediate_add_shift
_immediate_add_shift:
 add w0,w0,#1,lsl #12
 ret
.p2align 2
.globl _immediate_cmp_shift
_immediate_cmp_shift:
 cmp w0,#1,lsl #12
 csel w0,w1,w2,eq
 ret
.p2align 2
.globl _shift_lsl
_shift_lsl:
 add w0,w0,w1,lsl #31
 ret
.p2align 2
.globl _shift_lsr
_shift_lsr:
 eor w0,w0,w1,lsr #11
 ret
.p2align 2
.globl _shift_asr
_shift_asr:
 bic w0,w0,w1,asr #31
 ret
.p2align 2
.globl _shift_ror
_shift_ror:
 orr w0,w0,w1,ror #21
 ret
.p2align 2
.globl _move_insert
_move_insert:
 mov w8,#0xca77
 movk w8,#0x85eb,lsl #16
 eor w0,w0,w8
 ret
.p2align 2
.globl _flag_add_carry
_flag_add_carry:
 adds w8,w0,w1
 csel w0,w2,w3,hs
 ret
.p2align 2
.globl _flag_add_overflow
_flag_add_overflow:
 adds w8,w0,w1
 csel w0,w2,w3,vs
 ret
.p2align 2
.globl _flag_add_signed
_flag_add_signed:
 adds w8,w0,w1
 csel w0,w2,w3,ge
 ret
.p2align 2
.globl _flag_sub_carry
_flag_sub_carry:
 subs w8,w0,w1
 csel w0,w2,w3,ls
 ret
.p2align 2
.globl _flag_sub_overflow
_flag_sub_overflow:
 subs w8,w0,w1
 csel w0,w2,w3,vs
 ret
.p2align 2
.globl _flag_logic
_flag_logic:
 ands w8,w0,w1
 csel w0,w2,w3,mi
 ret
.p2align 2
.globl _test_alias
_test_alias:
 tst w0,w1
 csel w0,w2,w3,eq
 ret
.p2align 2
.globl _cmn_alias
_cmn_alias:
 cmn w0,w1
 csel w0,w2,w3,vs
 ret
.p2align 2
.globl _condition_invert
_condition_invert:
 cmp w0,w1
 csinv w0,w2,w3,eq
 ret
.p2align 2
.globl _condition_negate
_condition_negate:
 cmp w0,w1
 csneg w0,w2,w3,gt
 ret
.p2align 2
.globl _condition_increment
_condition_increment:
 cmp w0,w1
 csinc w0,w2,w3,ne
 ret
.p2align 2
.globl _multiply_add
_multiply_add:
 madd w0,w0,w1,w2
 ret
.p2align 2
.globl _multiply_subtract
_multiply_subtract:
 msub w0,w0,w1,w2
 ret
.p2align 2
.globl _negate
_negate:
 neg w0,w0
 ret
.p2align 2
.globl _invert
_invert:
 mvn w0,w0
 ret
.p2align 2
.globl _logical_register_shift
_logical_register_shift:
 lsr w0,w0,w1
 ret
.p2align 2
.globl _arithmetic_register_shift
_arithmetic_register_shift:
 asr w0,w0,w1
 ret
.p2align 2
.globl _rotate_register
_rotate_register:
 ror w0,w0,w1
 ret
.p2align 2
.globl _bitfield
_bitfield:
 ubfx w0,w0,#7,#11
 ret
.p2align 2
.globl _bitreverse
_bitreverse:
 rbit w0,w0
 ret
