#pragma once
#include "../offline-task-prototype/noop_task.h"
#include <cstdint>
enum EmptyResult { EMPTY_IDLE = 0, EMPTY_POSTED, EMPTY_INVALID, EMPTY_ALLOCATION,
                   EMPTY_PRIMARY_BUSY, EMPTY_WAKE_BUSY, EMPTY_NOT_EMPTY,
                   EMPTY_WAKE_OVERFLOW, EMPTY_POSIX_ERROR };
struct EmptyBinding { unsigned char* loop; int result = EMPTY_IDLE; };
// Only a zeroed three-pointer queue is accepted. No growth/old task inspection.
int publish_empty(void*, CrNoopTask*) noexcept;
