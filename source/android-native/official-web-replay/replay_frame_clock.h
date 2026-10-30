#pragma once
#include <limits>

namespace replay_frame_clock {
// Native replay controls implement Pause as rate=0, not C+17c. Zero is
// a valid playback state; rejecting it also kills the separate render pump.
constexpr bool valid_rate(float speed){return speed>=0&&speed<=4;}
// A debugger/background pause is not simulation time. Match the original
// controller's 0.1-second frame cap instead of rejecting a valid long pause.
constexpr bool bounded_delta(float elapsed,float& delta){
    if(!(elapsed>=0&&elapsed<=std::numeric_limits<float>::max()))return false;
    delta=elapsed>.1f?.1f:elapsed;
    return true;
}
}
