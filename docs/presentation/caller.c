#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
typedef struct { uint64_t result; uint64_t memory[2]; } rewynth_state;
extern rewynth_state original_transition(uint64_t,uint64_t);
extern rewynth_state edited_transition(uint64_t,uint64_t);
int main(void) {
 rewynth_state a=original_transition(UINT64_C(0x2fedd67bd8000000),UINT64_C(0xcc7d05711fffffff));
 rewynth_state b=edited_transition(UINT64_C(0x2fedd67bd8000000),UINT64_C(0xcc7d05711fffffff));
 rewynth_state next_a=original_transition(a.memory[0],a.memory[1]);
 rewynth_state next_b=original_transition(b.memory[0],b.memory[1]);
 printf("{\"first_original\":%" PRIu64 ",\"first_edited\":%" PRIu64 ",\"memory_original\":%" PRIu64 ",\"memory_edited\":%" PRIu64 ",\"next_original\":%" PRIu64 ",\"next_from_edited\":%" PRIu64 "}\n",a.result,b.result,a.memory[0],b.memory[0],next_a.result,next_b.result);
 return !(a.result==b.result && a.memory[0]!=b.memory[0] && a.memory[1]==b.memory[1] && next_a.result!=next_b.result);
}
