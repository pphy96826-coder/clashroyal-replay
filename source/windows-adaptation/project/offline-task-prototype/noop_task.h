#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct CrNoopTask CrNoopTask;
typedef struct CrNoopRequest CrNoopRequest;

enum CrNoopPhase {
    CR_NOOP_READY = 0, CR_NOOP_RUNNING, CR_NOOP_COMPLETED,
    CR_NOOP_CANCEL_REQUESTED, CR_NOOP_CANCELLED,
    CR_NOOP_THREAD_MISMATCH, CR_NOOP_ABANDONED
};
enum CrNoopSubmitResult {
    CR_NOOP_REJECTED = 0, CR_NOOP_ACCEPTED = 1,
    CR_NOOP_PROTOCOL_ERROR = -1, CR_NOOP_INVALID = -2
};
typedef struct {
    int phase;
    int submitted;
    int entered;
    int returned;
    int destroyed;
    uint64_t expected_tid;
    uint64_t execution_tid;
    uint64_t destruction_tid;
} CrNoopSnapshot;

/* Publish must not throw or wait for task completion; queue mutex acquisition
 * may block. Caller must not already hold the queue/wake mutexes.
 * True transfers exclusive task
 * ownership to a queue; false MUST mean no reference was retained or scheduled.
 * A queue may execute and delete the task before Publish returns true.
 * This project DOES NOT yet provide an official-client Publish implementation.
 */
typedef int (*CrNoopPublish)(void* queue, CrNoopTask* task);

/* No automatic game entry points, sockets, hooks, game calls, or fixed engine addresses.
 * Each returned request owns a reference which the caller must release.
 * The task's three-slot table is a prototype of the observed +0/+8/+16 ABI,
 * not proof of its compatibility with the official client.
 * Submit/discard must not race, and task pointers must not be used after an
 * accepted/rejected submission: the owner may already have destroyed the task.
 * Cancel only updates the retained request; it never frees a queued task.
 * Snapshots are diagnostic aggregates, not atomic completion transactions.
 */
uint64_t cr_noop_current_tid(void);
CrNoopTask* cr_noop_prepare(uint64_t expected_tid, CrNoopRequest** request);
int cr_noop_submit(CrNoopTask* task, CrNoopPublish publish, void* queue);
/* Only BEFORE submission. A submitted task may only be deleted by its owner. */
int cr_noop_discard_unsubmitted(CrNoopTask* task);
int cr_noop_cancel(CrNoopRequest* request);
int cr_noop_snapshot(CrNoopRequest* request, CrNoopSnapshot* snapshot);
void cr_noop_release_request(CrNoopRequest* request);

#ifdef __cplusplus
}
#endif
