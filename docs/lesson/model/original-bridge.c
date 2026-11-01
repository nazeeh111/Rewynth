#include "original.c"

/* Browser bridge: preserve the pure export's complete return and post-state. */
static rewynth_state last;
void lesson_call(uint64_t state, uint64_t increment) {
    last = rewynth_transition(state, increment);
}
uint64_t lesson_result(void) { return last.result; }
uint64_t lesson_state(void) { return last.memory[0]; }
uint64_t lesson_increment(void) { return last.memory[1]; }
