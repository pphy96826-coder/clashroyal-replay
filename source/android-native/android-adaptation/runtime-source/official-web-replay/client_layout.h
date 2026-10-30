#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace client_layout {
struct AvatarAccounting {
    std::size_t current, spent, gained, leaked;
};
// Distinct object layouts, not a blanket adjustment of every native offset.
inline constexpr AvatarAccounting avatar_3842{0x300,0x348,0x34c,0x350};
inline constexpr AvatarAccounting avatar_3852{0x308,0x350,0x354,0x358};
// The current approved runtime remains 38.4.2. Merely adding investigated
// constants must never activate an unvalidated native adapter.
inline constexpr AvatarAccounting active_avatar=avatar_3842;
struct Domain {std::size_t allocation_bytes;};
inline constexpr Domain domain_3842{0x240};
inline constexpr Domain domain_3852{0x248};
inline constexpr Domain active_domain=domain_3842;
struct AvatarDeal {std::size_t hand,hand_count,queue,queue_count;};
inline constexpr AvatarDeal deal_3842{0x218,0x224,0x228,0x234};
inline constexpr AvatarDeal deal_3852{0x220,0x22c,0x230,0x23c};
inline constexpr AvatarDeal active_deal=deal_3842;

struct UnitAbility {
    std::size_t ready_slot, table_extent;
};
inline constexpr UnitAbility unit_3842{0x190,0x198};
inline constexpr UnitAbility unit_3852{0x198,0x1a0};
inline constexpr UnitAbility active_unit=unit_3842;
struct ReplayController {
    std::size_t presentation_handle;
};
inline constexpr ReplayController controller_3842{0x2b0};
inline constexpr ReplayController controller_3852{0x2c8};
inline constexpr ReplayController active_controller=controller_3842;
struct StaticVtables {std::uintptr_t first,last;};
inline constexpr StaticVtables vtables_3842{0x1b3dd60,0x1c6d670};
inline constexpr StaticVtables vtables_3852{0x1c46030,0x1d80020};
inline constexpr StaticVtables active_vtables=vtables_3842;
inline bool contains_vtable(std::uintptr_t base,std::uintptr_t table,std::size_t bytes,StaticVtables layout) {
    if(table<base||!bytes)return false;
    const auto relative=table-base;
    return relative>=layout.first&&relative<layout.last&&bytes<=layout.last-relative;
}
// The caller checks table_extent against the current process read ranges.
inline std::uintptr_t ability_ready_method(std::uintptr_t table,UnitAbility layout) {
    std::uintptr_t result{};
    std::memcpy(&result,reinterpret_cast<const void*>(table+layout.ready_slot),sizeof(result));
    return result;
}

// Caller must prove the object readable and owned by the current replay.
inline std::array<int,4> elixir_snapshot(std::uintptr_t object,AvatarAccounting layout) {
    std::array<int,4> result{};
    const std::size_t offsets[]={layout.current,layout.spent,layout.gained,layout.leaked};
    for(unsigned i=0;i<4;++i)std::memcpy(&result[i],reinterpret_cast<const void*>(object+offsets[i]),sizeof(int));
    return result;
}
}
