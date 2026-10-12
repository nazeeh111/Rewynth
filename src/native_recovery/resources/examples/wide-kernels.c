/*  Written in 2015 by Sebastiano Vigna (vigna@acm.org)

To the extent possible under law, the author has dedicated all copyright
and related and neighboring rights to this software to the public domain
worldwide. This software is distributed without any warranty.

See <http://creativecommons.org/publicdomain/zero/1.0/>. */


/* Pure-function adapter of Sebastiano Vigna's 2015 SplitMix64 code.
 * Pinned upstream: svaarala/duktape 84131700dfd32d9d1063f99b5b0a900f5935a613,
 * misc/splitmix64.c. Upstream notice is preserved in splitmix64-upstream.c.
 * Adaptation: global state is an explicit uint64_t argument; state write-back
 * is outside the candidate function. Arithmetic and constants are unchanged.
 * This wrapper is not the original stateful next() native function.
 */
#include <stdint.h>

__attribute__((noinline)) uint64_t splitmix64_step(uint64_t before_state)
{
    uint64_t z = before_state + UINT64_C(0x9E3779B97F4A7C15);
    z = (z ^ (z >> 30)) * UINT64_C(0xBF58476D1CE4E5B9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94D049BB133111EB);
    return z ^ (z >> 31);
}


/* Original Rewynth fixtures. These are not upstream SplitMix64 functions. */
__attribute__((noinline)) uint64_t wide_lattice(uint64_t a, uint64_t b) {
    return ((a & UINT64_C(0xf0f0f0f0f0f0f0f)) << 4) ^ (a >> 17) ^ ((b << 39) | (b >> 25)) ^ a;
}
__attribute__((noinline)) uint64_t wide_permute(uint64_t a) {
    a ^= a >> 9;
    a *= UINT64_C(0xd6e8feb86659fd93);
    a = (a << 43) | (a >> 21);
    return a + UINT64_C(0x123456789abcdef1);
}
__attribute__((noinline)) uint64_t wide_lossy(uint64_t a) {
    return (uint64_t)(uint32_t)(a + UINT64_C(3));
}
__attribute__((noinline)) uint64_t wide_select(uint64_t a, uint64_t b) {
    return (int64_t)a < (int64_t)b ? a + UINT64_C(17) : b - UINT64_C(13);
}
__attribute__((noinline)) uint64_t wide_field(uint64_t a, uint64_t b) {
    const uint64_t mask = UINT64_C(0x7fffff);
    return (a & ~(mask << 13)) | ((b & mask) << 13);
}
