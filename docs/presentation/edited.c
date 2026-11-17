/* Artifact SHA256: ace691f7e16518d363ed0582d7a6ab9ee54c2818014b955b2ee886bf31bc556f
   Model scope: pure transition struct: architectural return and every declared uint64 memory word; not a binary ABI replacement, declared domain only.
   This export is reconstructed source, not a native equivalence certificate. */
/* Pure transition: logical inputs are original scalars then initial memory words.
   All declared post-state words and architectural X0 are returned.
   This is reconstructed model source, not the original pointer ABI. */
#include <stdint.h>
#include <stdbool.h>

static uint64_t rewynth_observation_0(uint64_t x0, uint64_t x1) {
    uint64_t nr_0 = (uint64_t)(x0 >> (UINT64_C(0x000000000000002d) & UINT64_C(63)));
    uint64_t nr_1 = (uint64_t)(nr_0 >> (UINT64_C(0x0000000000000000) & UINT64_C(63)));
    uint64_t nr_2 = (uint64_t)(nr_1 & UINT64_C(0x00000000ffffffff));
    uint64_t nr_3 = (uint64_t)(x0 >> (UINT64_C(0x000000000000001b) & UINT64_C(63)));
    uint64_t nr_4 = (uint64_t)(nr_3 >> (UINT64_C(0x0000000000000000) & UINT64_C(63)));
    uint64_t nr_5 = (uint64_t)(nr_4 & UINT64_C(0x00000000ffffffff));
    uint64_t nr_6 = (uint64_t)(nr_2 ^ nr_5);
    uint64_t nr_7 = (uint64_t)(nr_6 & UINT64_C(0x00000000ffffffff));
    uint64_t nr_8 = (uint64_t)(nr_7 >> (UINT64_C(0x0000000000000000) & UINT64_C(63)));
    uint64_t nr_9 = (uint64_t)(nr_8 & UINT64_C(0x00000000ffffffff));
    uint64_t nr_10 = (uint64_t)(x0 >> (UINT64_C(0x000000000000003b) & UINT64_C(63)));
    uint64_t nr_11 = (uint64_t)(nr_10 >> (UINT64_C(0x0000000000000000) & UINT64_C(63)));
    uint64_t nr_12 = (uint64_t)(nr_11 & UINT64_C(0x00000000ffffffff));
    uint64_t nr_13 = (uint64_t)(nr_12 & UINT64_C(0x000000000000001f));
    uint64_t nr_14 = (uint64_t)(nr_13 & UINT64_C(0x00000000ffffffff));
    uint64_t nr_15 = (uint64_t)(nr_14 & UINT64_C(0x000000000000001f));
    uint64_t nr_16 = (uint64_t)(nr_9 >> (nr_15 & UINT64_C(63)));
    uint64_t nr_17 = (uint64_t)(UINT64_C(0x0000000000000020) - nr_15);
    uint64_t nr_18 = (uint64_t)(nr_9 << (nr_17 & UINT64_C(63)));
    uint64_t nr_19 = (uint64_t)(nr_16 | nr_18);
    uint64_t nr_20 = (uint64_t)(nr_19 & UINT64_C(0x00000000ffffffff));
    return (uint64_t)(nr_20);
}

static uint64_t rewynth_observation_1(uint64_t x0, uint64_t x1) {
    return (uint64_t)(x0);
}

static uint64_t rewynth_observation_2(uint64_t x0, uint64_t x1) {
    return (uint64_t)(x1);
}

typedef struct { uint64_t result; uint64_t memory[2]; } rewynth_state;
rewynth_state rewynth_transition(uint64_t x0, uint64_t x1) {
    rewynth_state output;
    output.result = rewynth_observation_0(x0, x1);
    output.memory[0] = rewynth_observation_1(x0, x1);
    output.memory[1] = rewynth_observation_2(x0, x1);
    return output;
}
