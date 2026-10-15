/* Original controlled fixtures, authored for this experiment. No external code.
 * All arithmetic is unsigned and wraps modulo the selected width.
 * Unlikely hints describe guards; they do not replace any branch semantics.
 */
typedef unsigned int u32;
typedef unsigned long long u64;
#define EXPORTED __attribute__((noinline,visibility("default")))
#define UNLIKELY(x) __builtin_expect(!!(x),0)

/* A piecewise fixed-point luminance curve. Input/output are 12-bit samples;
 * the high guard provides deliberate saturation for malformed large input. */
EXPORTED u32 tone_curve32(u32 x) {
    if (UNLIKELY(x > 4095u)) return 4095u;
    if (x < 512u) {
        u32 y = (x * x + 255u) >> 9;
        return (y * 3u + x) >> 2;
    }
    if (x < 3072u) return x;
    u32 y = 4095u - x;
    return 4095u - ((y * y + 511u) >> 10);
}

/* Recover a hashed table probe seed, using a separate avalanche for the
 * reserved zero key instead of letting zero collapse the multiplicative mix. */
EXPORTED u64 guarded_seed64(u64 key, u64 salt) {
    if (UNLIKELY(key == 0)) {
        u64 h = salt ^ 0x9e3779b97f4a7c15ull;
        h ^= h >> 29;
        h *= 0xbf58476d1ce4e5b9ull;
        return h ^ (h >> 31);
    }
    u64 h = key ^ (salt + 0x517cc1b727220a95ull);
    h ^= h >> 27;
    h *= 0x94d049bb133111ebull;
    h ^= h >> 33;
    return h * 0x9e3779b185ebca87ull;
}

/* Adaptive, bounded fixed-point gain: the quiet segment boosts detail,
 * middle segment retains gain, and the loud segment compresses the result.
 * Caller selects unsigned thresholds; reversed thresholds still have exact
 * defined behavior rather than an unstated mathematical precondition. */
EXPORTED u32 adaptive_gain32(u32 x, u32 quiet, u32 loud) {
    if (UNLIKELY(x < quiet)) {
        u32 y = x * 3u + (x >> 2);
        y ^= y >> 13;
        return y + ((quiet - x) >> 3);
    }
    if (UNLIKELY(x > loud)) {
        u32 y = x - loud;
        y = (y >> 2) + (y >> 4);
        return loud + y;
    }
    return x;
}

/* Four-lane hash finalization with an optional domain separator. The zero
 * separator is a common fast case; nonzero separates record categories. */
EXPORTED u64 record_hash64(u64 a, u64 b, u64 c, u64 domain) {
    u64 h = a + (b << 7) + (b >> 57);
    h ^= c + 0x9e3779b97f4a7c15ull;
    if (UNLIKELY(domain != 0)) {
        h ^= domain * 0xbf58476d1ce4e5b9ull;
        h ^= h >> 30;
        h *= 0x94d049bb133111ebull;
    }
    h ^= h >> 27;
    h *= 0x9e3779b185ebca87ull;
    return h ^ (h >> 31);
}

/* Morton (Z-order) index for a 16-bit coordinate pair. Out-of-range samples
 * map to the all-ones sentinel; all-ones is also the valid upper-right index,
 * so this API saturates rather than offering an unambiguous error code. */
EXPORTED u32 guarded_morton32(u32 x, u32 y) {
    if (UNLIKELY((x | y) > 65535u)) return 0xffffffffu;
    x = (x | (x << 8)) & 0x00ff00ffu;
    y = (y | (y << 8)) & 0x00ff00ffu;
    x = (x | (x << 4)) & 0x0f0f0f0fu;
    y = (y | (y << 4)) & 0x0f0f0f0fu;
    x = (x | (x << 2)) & 0x33333333u;
    y = (y | (y << 2)) & 0x33333333u;
    x = (x | (x << 1)) & 0x55555555u;
    y = (y | (y << 1)) & 0x55555555u;
    return x | (y << 1);
}

/* Window-relative randomized tag. Values outside the inclusive unsigned
 * interval map to zero. Values inside are mixed from their offset. This
 * is a noncryptographic tag; no uniqueness or security property is claimed. */
EXPORTED u64 window_tag64(u64 value, u64 low, u64 high) {
    if (UNLIKELY(value < low)) return 0;
    if (UNLIKELY(value > high)) return 0;
    u64 x = value - low + 0x9e3779b97f4a7c15ull;
    x ^= x >> 30;
    x *= 0xbf58476d1ce4e5b9ull;
    x ^= x >> 27;
    x *= 0x94d049bb133111ebull;
    return x ^ (x >> 31);
}
