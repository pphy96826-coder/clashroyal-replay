#include "noop_task.h"
#include <atomic>
#include <cstddef>
#include <new>
#if defined(__linux__)
#include <sys/syscall.h>
#include <unistd.h>
#elif defined(__APPLE__)
#include <pthread.h>
#else
#error Unsupported platform for audited thread IDs
#endif

#define CR_EXPORT __attribute__((visibility("default")))

struct CrNoopRequest {
    std::atomic<unsigned> refs{2};  // caller + task
    std::atomic<int> phase{CR_NOOP_READY};
    std::atomic<bool> submitted{false}, entered{false}, returned{false}, destroyed{false};
    const uint64_t expected_tid;
    std::atomic<uint64_t> execution_tid{0}, destruction_tid{0};
    explicit CrNoopRequest(uint64_t tid) noexcept : expected_tid(tid) {}
};

using TaskMethod = void (*)(CrNoopTask*) noexcept;
struct CrNoopTask {
    const TaskMethod* table;
    CrNoopRequest* request;
};
static_assert(offsetof(CrNoopTask, table) == 0);
static_assert(offsetof(CrNoopTask, request) == 8);
static_assert(sizeof(CrNoopTask) == 16);

extern "C" CR_EXPORT uint64_t cr_noop_current_tid(void) {
#if defined(__linux__)
    return static_cast<uint64_t>(syscall(SYS_gettid));
#else
    uint64_t tid = 0;
    return pthread_threadid_np(nullptr, &tid) == 0 ? tid : 0;
#endif
}

static void release(CrNoopRequest* request) noexcept {
    if (request && request->refs.fetch_sub(1, std::memory_order_acq_rel) == 1)
        delete request;
}

static void destroy_contents(CrNoopTask* task) noexcept {
    auto* request = task->request;
    task->request = nullptr; // nondeleting followed by deleting dtor is safe
    if (!request) return;
    int expected = CR_NOOP_READY;
    if (!request->phase.compare_exchange_strong(expected, CR_NOOP_ABANDONED)) {
        expected = CR_NOOP_CANCEL_REQUESTED;
        request->phase.compare_exchange_strong(expected, CR_NOOP_CANCELLED);
    }
    request->destruction_tid.store(cr_noop_current_tid());
    request->destroyed.store(true, std::memory_order_release);
    release(request);
}

static void delete_task(CrNoopTask* task) noexcept {
    destroy_contents(task);
    delete task; // the same component that allocated it deletes it
}

static void execute_task(CrNoopTask* task) noexcept {
    auto* request = task->request;
    if (!request || request->entered.exchange(true)) return;
    const auto tid = cr_noop_current_tid();
    request->execution_tid.store(tid);
    int expected = CR_NOOP_READY;
    if (request->phase.compare_exchange_strong(expected, CR_NOOP_RUNNING)) {
        // Deliberately no payload: do not initialize/step/deploy or read Battle.
        request->phase.store(tid == request->expected_tid
            ? CR_NOOP_COMPLETED : CR_NOOP_THREAD_MISMATCH);
    } else if (expected == CR_NOOP_CANCEL_REQUESTED) {
        request->phase.store(CR_NOOP_CANCELLED);
    }
    request->returned.store(true, std::memory_order_release);
}

static const TaskMethod methods[] = {destroy_contents, delete_task, execute_task};

extern "C" CR_EXPORT CrNoopTask* cr_noop_prepare(uint64_t tid, CrNoopRequest** output) {
    if (!output) return nullptr;
    *output = nullptr;
    if (!tid) return nullptr;
    auto* request = new (std::nothrow) CrNoopRequest(tid);
    if (!request) return nullptr;
    auto* task = new (std::nothrow) CrNoopTask{methods, request};
    if (!task) { delete request; return nullptr; }
    *output = request;
    return task;
}

extern "C" CR_EXPORT int cr_noop_submit(CrNoopTask* task, CrNoopPublish publish, void* queue) {
    if (!task || !task->request || !publish) return CR_NOOP_INVALID;
    auto* request = task->request;
    if (request->submitted.exchange(true)) return CR_NOOP_INVALID;
    // A fast consumer can delete the task inside publish. Pin only the request
    // and NEVER dereference the task again after an accepted publication.
    request->refs.fetch_add(1);
    const int accepted = publish(queue, task);
    int result = CR_NOOP_ACCEPTED;
    if (!accepted) {
        if (request->entered.load() || request->destroyed.load()) {
            result = CR_NOOP_PROTOCOL_ERROR; // no double delete on broken publisher
        } else {
            request->submitted.store(false);
            delete_task(task); // permitted only by the rejection ownership contract
            result = CR_NOOP_REJECTED;
        }
    }
    release(request);
    return result;
}

extern "C" CR_EXPORT int cr_noop_cancel(CrNoopRequest* request) {
    if (!request) return 0;
    int expected = CR_NOOP_READY;
    return request->phase.compare_exchange_strong(expected, CR_NOOP_CANCEL_REQUESTED);
}

extern "C" CR_EXPORT int cr_noop_discard_unsubmitted(CrNoopTask* task) {
    if (!task || !task->request || task->request->submitted.load()) return 0;
    delete_task(task);
    return 1;
}

extern "C" CR_EXPORT int cr_noop_snapshot(CrNoopRequest* request, CrNoopSnapshot* output) {
    if (!request || !output) return 0;
    // Diagnostic, non-atomic aggregate; caller must keep its request reference.
    *output = {request->phase.load(), request->submitted.load(), request->entered.load(),
        request->returned.load(), request->destroyed.load(), request->expected_tid,
        request->execution_tid.load(), request->destruction_tid.load()};
    return 1;
}

extern "C" CR_EXPORT void cr_noop_release_request(CrNoopRequest* request) {
    release(request);
}
