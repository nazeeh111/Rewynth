/* Test kernels extracted from nothings/stb stb_image.h, public-domain/MIT dual license.
   Canonical public source is retained alongside this probe. */
typedef unsigned char stbi_uc;
__attribute__((visibility("default"))) stbi_uc kernel_luma(int r,int g,int b) {
 return (stbi_uc)(((r*77)+(g*150)+(29*b))>>8);
}
__attribute__((visibility("default"))) stbi_uc kernel_clamp(int x) {
 if((unsigned int)x>255){if(x<0)return 0;if(x>255)return 255;}
 return (stbi_uc)x;
}
__attribute__((visibility("default"))) int kernel_reverse(int n) {
 n=((n&0xAAAA)>>1)|((n&0x5555)<<1);
 n=((n&0xCCCC)>>2)|((n&0x3333)<<2);
 n=((n&0xF0F0)>>4)|((n&0x0F0F)<<4);
 n=((n&0xFF00)>>8)|((n&0x00FF)<<8);
 return n;
}
/* Owned mixed arithmetic/conditional control kernel, not a recognized recipe. */
__attribute__((visibility("default"))) unsigned int kernel_mixed(unsigned int x,unsigned int y) {
 unsigned int a=x*3u+y*17u;
 unsigned int b=((y<<11u)|(y>>21u))^x;
 return (int)x<0?a:b;
}
/* xxHash XXH32_avalanche; source xxhash.h retained; BSD 2-clause license. */
__attribute__((visibility("default"))) unsigned int kernel_avalanche(unsigned int hash) {
 hash ^= hash >> 15;
 hash *= 0x85ebca77u;
 hash ^= hash >> 13;
 hash *= 0xc2b2ae3du;
 hash ^= hash >> 16;
 return hash;
}
/* Owned four-input GF(2) bitfield/permutation mixing kernel. */
__attribute__((visibility("default"))) unsigned int kernel_bits(unsigned int x,unsigned int y,unsigned int z,unsigned int w) {
 return ((x&0xff00ff00u)>>8)^((y<<5)|(y>>27))^(z>>3)^(w&0x33333333u)^0xa5a5a5a5u;
}
