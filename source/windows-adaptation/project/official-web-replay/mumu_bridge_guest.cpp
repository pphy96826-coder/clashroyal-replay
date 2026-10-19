// This library executes as ARM64 through NativeBridge. Game code is unchanged.
#include <stdint.h>

extern "C" __attribute__((visibility("default")))
uint64_t Java_RoyaleReplayBridge_dispatch(void*, void*, uint64_t op,
    uint64_t address, uint64_t a, uint64_t b, uint64_t c, uint64_t d, uint64_t e) {
    if (op == 0) return 0x41524d3634425247ULL;
    if (!address) return 0;
    switch (op) {
        case 1: return reinterpret_cast<uint64_t(*)()>(address)();
        case 2: return static_cast<uint64_t>(reinterpret_cast<int(*)()>(address)());
        case 3: return static_cast<uint64_t>(reinterpret_cast<int(*)(uint64_t,int,uint64_t,uint64_t,uint64_t)>(address)(a,static_cast<int>(b),c,d,e));
        case 4: return static_cast<uint64_t>(reinterpret_cast<int(*)(void*)>(address)(reinterpret_cast<void*>(a)));
        case 5: return reinterpret_cast<uint64_t>(reinterpret_cast<void*(*)(const char*,int)>(address)(reinterpret_cast<const char*>(a),static_cast<int>(b)));
        default: return 0;
    }
}
