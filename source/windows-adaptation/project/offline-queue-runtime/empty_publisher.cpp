#include "empty_publisher.h"
#include <pthread.h>
#include <cstdlib>
#include <cstring>
#include <climits>

int publish_empty(void* opaque, CrNoopTask* task) noexcept {
    auto* b = static_cast<EmptyBinding*>(opaque);
    if (!b || !b->loop || !task) { if (b) b->result = EMPTY_INVALID; return 0; }
    // Consumer's verified buffer delete is a direct libc free. malloc storage
    // is used only after the adapter checks host GOT == our libc imports.
    auto* storage = static_cast<CrNoopTask**>(std::malloc(sizeof(task)));
    if (!storage) { b->result = EMPTY_ALLOCATION; return 0; }
    auto* primary = reinterpret_cast<pthread_mutex_t*>(b->loop + 0x14);
    auto* wake = reinterpret_cast<pthread_mutex_t*>(b->loop + 0x3c);
    if (pthread_mutex_trylock(primary)) {
        std::free(storage); b->result = EMPTY_PRIMARY_BUSY; return 0;
    }
    uintptr_t v[3]{};
    std::memcpy(v, b->loop + 0xf8, sizeof(v));
    if (v[0] || v[1] || v[2]) {
        pthread_mutex_unlock(primary); std::free(storage);
        b->result = EMPTY_NOT_EMPTY; return 0;
    }
    if (pthread_mutex_trylock(wake)) {
        pthread_mutex_unlock(primary); std::free(storage);
        b->result = EMPTY_WAKE_BUSY; return 0;
    }
    uint32_t count{}; std::memcpy(&count, b->loop + 0x94, sizeof(count));
    if (count >= INT_MAX) {
        pthread_mutex_unlock(wake); pthread_mutex_unlock(primary); std::free(storage);
        b->result = EMPTY_WAKE_OVERFLOW; return 0;
    }
    storage[0] = task;
    const auto begin = reinterpret_cast<uintptr_t>(storage);
    const uintptr_t after[3] = {begin, begin + 8, begin + 8};
    std::memcpy(b->loop + 0xf8, after, sizeof(after));
    ++count; std::memcpy(b->loop + 0x94, &count, sizeof(count));
    // Ownership is now transferred. Even a POSIX notification/unlock error
    // must return accepted; the controller may NEVER delete the queued task.
    const int unlock_wake = pthread_mutex_unlock(wake);
    const int signal = pthread_cond_signal(reinterpret_cast<pthread_cond_t*>(b->loop + 0x64));
    const int unlock_primary = pthread_mutex_unlock(primary);
    b->result = unlock_wake || signal || unlock_primary ? EMPTY_POSIX_ERROR : EMPTY_POSTED;
    return 1;
}
