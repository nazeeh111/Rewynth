/* Owned fixtures. Mixer follows the public-domain SplitMix64 transform by
   Sebastiano Vigna, https://prng.di.unimi.it/splitmix64.c (2015).
   This is a scalar transform fixture, not the complete stateful PRNG. */
#include <stdint.h>
uint64_t wide_mixer(uint64_t x) {
 x+=UINT64_C(0x9e3779b97f4a7c15);x^=x>>30;x*=UINT64_C(0xbf58476d1ce4e5b9);
 x^=x>>27;x*=UINT64_C(0x94d049bb133111eb);x^=x>>31;return x;
}
uint64_t wide_mixed(uint64_t x,uint64_t y) {
 uint64_t a=x*UINT64_C(0x100000003)+y*17u;
 uint64_t b=((y<<41)|(y>>23))^x;
 return (x & (UINT64_C(1)<<63)) ? a:b;
}
uint64_t wide_luma(uint64_t r,uint64_t g,uint64_t b) { return ((77*r+150*g+29*b)>>8)&255u; }
uint64_t wide_clamp(uint64_t x) {
 if(x & (UINT64_C(1)<<63))return 0;
 return x>255?255:x;
}
