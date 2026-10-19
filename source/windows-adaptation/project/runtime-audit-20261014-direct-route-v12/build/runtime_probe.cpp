#include "../../offline-queue-runtime/empty_publisher.h"
#include <pthread.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <unistd.h>

#define EXPORT extern "C" __attribute__((visibility("default")))
static CrNoopRequest* request{}; // Controller entry points must be serialized.
static int publisher_result = EMPTY_IDLE;
template<class T> static T read(uintptr_t p) { T v{}; std::memcpy(&v, reinterpret_cast<void*>(p), sizeof(v)); return v; }
static bool mapped(uintptr_t p, size_t size, const char* required) {
    if (!p || p + size < p) return false;
    FILE* stream = std::fopen("/proc/self/maps", "r");
    if (!stream) return false;
    char line[1024]; bool found = false; uintptr_t covered=p;
    while (std::fgets(line,sizeof(line),stream)) {
        unsigned long long low{},high{}; char mode[5]{};
        if (std::sscanf(line,"%llx-%llx %4s",&low,&high,mode)!=3) continue;
        if (high<=covered) continue;
        if (low>covered) break;
        bool permitted=true;
        for (const char* r=required;*r;++r) if (!std::strchr(mode,*r)) permitted=false;
        if (!permitted) break;
        covered=high;
        if (covered>=p+size) {found=true;break;}
    }
    std::fclose(stream); return found;
}

static bool validated(uintptr_t base, int pid, uint64_t tid, uintptr_t handle) {
    if (pid != getpid() || !tid || tid == cr_noop_current_tid() || base % 4096 ||
        !mapped(base, 64, "rx") || read<uint32_t>(base) != 0x464c457f ||
        !mapped(base + 0x1d88818, 0x110, "rw") ||
        !mapped(handle, 0x18, "r")) return false;
    const auto loop = base + 0x1d88818;
    if (read<uintptr_t>(loop) != base + 0x1c4a2e8 ||
        read<uintptr_t>(loop + 8) != handle || read<int>(handle + 0x10) != static_cast<int>(tid)) return false;
    struct Pin { uintptr_t va; uint32_t word; };
    const Pin pins[] = {
        {0x1629ab4, 0xa94fd674}, {0x1629abc, 0xa90ffe7f}, {0x1629ac0, 0xf900867f},
        {0x1629ae8, 0xf9400908}, {0x1629b24, 0xf9400508}, {0x1629b44, 0x94142b7d},
        {0x1b34938, 0xd503245f}, {0x1b3493c, 0x14001d39}
    };
    for (const auto& pin : pins)
        if (!mapped(base + pin.va, 4, "rx") || read<uint32_t>(base + pin.va) != pin.word) return false;
    struct Import { uintptr_t va; uintptr_t target; };
    const Import imports[] = {{0x1c72ba8, reinterpret_cast<uintptr_t>(&malloc)},
        {0x1c72bb0, reinterpret_cast<uintptr_t>(&free)},
        {0x1c72de0, reinterpret_cast<uintptr_t>(&pthread_mutex_lock)},
        {0x1c72df8, reinterpret_cast<uintptr_t>(&pthread_mutex_unlock)},
        {0x1c72e68, reinterpret_cast<uintptr_t>(&pthread_cond_signal)}};
    for (const auto& import : imports)
        if (!mapped(base + import.va, 8, "r") || read<uintptr_t>(base + import.va) != import.target) return false;
    return true; // Full installed libg hash is checked separately by controller.
}
EXPORT int cr_runtime_start(uintptr_t base, int pid, uint64_t tid, uintptr_t handle) {
    if (request) return -10;
    if (!validated(base, pid, tid, handle)) return -11;
    auto* task = cr_noop_prepare(tid, &request);
    if (!task) return -12;
    EmptyBinding binding{reinterpret_cast<unsigned char*>(base + 0x1d88818)};
    const int result = cr_noop_submit(task, publish_empty, &binding);
    publisher_result = binding.result;
    return result;
}
// Scalar access simplifies debugger calls without inventing opaque struct ABI.
EXPORT uint64_t cr_runtime_field(unsigned index) {
    if (index == 0) return static_cast<uint64_t>(publisher_result);
    CrNoopSnapshot state{};
    if (!request || !cr_noop_snapshot(request, &state)) return UINT64_MAX;
    switch (index) {
        case 1: return state.phase; case 2: return state.submitted;
        case 3: return state.entered; case 4: return state.returned;
        case 5: return state.destroyed; case 6: return state.expected_tid;
        case 7: return state.execution_tid; case 8: return state.destruction_tid;
        default: return UINT64_MAX;
    }
}
EXPORT int cr_runtime_release() {
    if (!request) return 0;
    CrNoopSnapshot state{}; cr_noop_snapshot(request, &state);
    if (!state.destroyed) return -1; // never free a possibly queued task
    cr_noop_release_request(request); request = nullptr; return 1;
    // This alone is NOT permission to unload: controller must also ensure no
    // worker stack is inside this module (destroyed flag precedes final return).
}
