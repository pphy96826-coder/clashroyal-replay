#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <initializer_list>

namespace private_map {
enum Stage : unsigned { IDLE, ALLOCATED, PARSING, PARSED, MAP_PARSED, CLEANING, FREED,
                        REJECTED, INVARIANT_FAILED, EXCEPTION };
enum AuditPoint : unsigned { BEGIN, OUTER_ALLOCATED, NAMES_READY, CSV0_READY, CSV1_READY,
    CSV_CHECKED, LAYOUT_READY, LAYOUT_BOUND, GEOMETRY_READY, GEOMETRY_CHECKED,
    LAYOUT_RESET, LAYOUT_STRINGS_CLEAN, LAYOUT_FREED, CSV0_CLEAN, CSV0_FREED,
    CSV1_CLEAN, CSV1_FREED, NAMES_CLEAN, FINISHED, AUDIT_POINT_COUNT };
struct Result {
    std::atomic<unsigned> stage{IDLE}, csv_constructed{0}, csv_cleaned{0},
        layout_constructed{0}, layout_cleaned{0}, freed{0}, width{0}, height{0},
        csv_mismatches{0}, geometry_mismatches{0};
    std::atomic<uintptr_t> retained{0};
};
struct Calls {
    void* (*allocate)(size_t);
    void (*deallocate)(void*);
    void (*string_construct)(void*, const char*);
    void (*string_cleanup)(void*);
    void (*csv_construct)(void*, const char*, int, void*);
    void (*csv_cleanup)(void*);
    void* (*section)(void*, void*);
    void* (*table)(void*);
    int (*cell)(void*, int);
    void (*layout_construct)(void*, void*);
    void (*layout_bind)(void*, void*, void*);
    void (*layout_map)(void*);
    void (*layout_reset)(void*);
    bool (*readable)(uintptr_t, size_t);
    uintptr_t services;
    void (*audit)(void*, unsigned) noexcept{};
    void* audit_context{};
};
template<class T> T field(void* p, size_t off) {
    T v{}; std::memcpy(&v, static_cast<unsigned char*>(p) + off, sizeof(v)); return v;
}
// Only private objects. No shared ResourceManager, Services cache publication,
// Battle binding, game-mode mutation, replay input or tick/deployment.
inline void run(const Calls& c, Result& r, const char* first, int first_size,
                const char* second, int second_size, const int* expected,
                unsigned width, unsigned height) noexcept {
    void* csv[2]{}; void* layout{};
    alignas(16) unsigned char names[3][16]{};
    const auto audit=[&](AuditPoint point) noexcept {
        if(c.audit)c.audit(c.audit_context,point);
    };
    try {
        if (!first || !second || !expected || first_size <= 0 || second_size <= 0 ||
            !width || !height || width > 128 || height > 128) { r.stage.store(REJECTED); return; }
        audit(BEGIN);
        // Allocate all outer objects before any native constructor.
        csv[0] = c.allocate(0x68); csv[1] = c.allocate(0x68); layout = c.allocate(0xb0);
        if (!csv[0] || !csv[1] || !layout) {
            for (auto* p : csv) if (p) c.deallocate(p);
            if (layout) c.deallocate(layout);
            r.stage.store(REJECTED); return;
        }
        r.retained.store(3); r.stage.store(ALLOCATED);
        std::memset(csv[0], 0, 0x68); std::memset(csv[1], 0, 0x68); std::memset(layout, 0, 0xb0);
        audit(OUTER_ALLOCATED);
        c.string_construct(names[0], "locations/dragon_arena.csv");
        c.string_construct(names[1], "tilemaps/tilemap.csv");
        c.string_construct(names[2], "Map");
        audit(NAMES_READY);
        r.stage.store(PARSING);
        c.csv_construct(csv[0], first, first_size, names[0]); r.csv_constructed.fetch_add(1);
        audit(CSV0_READY);
        c.csv_construct(csv[1], second, second_size, names[1]); r.csv_constructed.fetch_add(1);
        audit(CSV1_READY);
        r.stage.store(PARSED);
        auto* section = c.section(csv[1], names[2]);
        if (!section || !c.readable(reinterpret_cast<uintptr_t>(section), 0x68)) {
            r.stage.store(INVARIANT_FAILED); return;
        }
        auto* table = c.table(section);
        if (!table || !c.readable(reinterpret_cast<uintptr_t>(table), 0x64) ||
            field<unsigned>(table, 0x34) != width || field<unsigned>(table, 0x54) != height) {
            r.stage.store(INVARIANT_FAILED); return;
        }
        const auto rows = field<uintptr_t>(table, 0x48);
        if (!c.readable(rows, height * 8)) { r.stage.store(INVARIANT_FAILED); return; }
        for (unsigned y = 0; y < height; ++y) {
            auto* row = reinterpret_cast<void*>(field<uintptr_t>(reinterpret_cast<void*>(rows), y*8));
            if (!row || !c.readable(reinterpret_cast<uintptr_t>(row), 0x10) ||
                field<uintptr_t>(row, 0) != reinterpret_cast<uintptr_t>(table) ||
                field<unsigned>(row, 8) != y) { r.stage.store(INVARIANT_FAILED); return; }
            for (unsigned x = 0; x < width; ++x)
                if (c.cell(row, x) != expected[y*width+x]) r.csv_mismatches.fetch_add(1);
        }
        if (r.csv_mismatches.load()) { r.stage.store(INVARIANT_FAILED); return; }
        audit(CSV_CHECKED);
        c.layout_construct(layout, reinterpret_cast<void*>(c.services)); r.layout_constructed.store(1);
        audit(LAYOUT_READY);
        c.layout_bind(layout, csv[0], csv[1]);
        audit(LAYOUT_BOUND);
        // Map-only stage: full Objects/Background/initial-tower parse is separate.
        c.layout_map(layout); r.stage.store(MAP_PARSED);
        audit(GEOMETRY_READY);
        r.width.store(field<unsigned>(layout, 0xa8)); r.height.store(field<unsigned>(layout, 0xac));
        const auto low = field<uintptr_t>(layout, 0x98), high = field<uintptr_t>(layout, 0xa0);
        if (r.width.load() != width || r.height.load() != height ||
            field<uintptr_t>(layout, 0x88) != reinterpret_cast<uintptr_t>(table) ||
            !c.readable(low, width*height*4) || !c.readable(high, width*height*4)) {
            r.stage.store(INVARIANT_FAILED); return;
        }
        for (unsigned i=0; i<width*height; ++i) {
            if (field<int>(reinterpret_cast<void*>(low), i*4) != (expected[i]&0x7f) ||
                field<int>(reinterpret_cast<void*>(high), i*4) != (expected[i]&0x380))
                r.geometry_mismatches.fetch_add(1);
        }
        if (r.geometry_mismatches.load()) { r.stage.store(INVARIANT_FAILED); return; }
        // Map-only never appends these four borrowed-row/type containers.
        for (size_t off : {size_t{0x28}, size_t{0x38}, size_t{0x48}, size_t{0x58}})
            if (field<uintptr_t>(layout, off) || field<uint64_t>(layout, off+8)) {
                r.stage.store(INVARIANT_FAILED); return;
            }
        audit(GEOMETRY_CHECKED);
        r.stage.store(CLEANING);
        c.layout_reset(layout); r.layout_cleaned.store(1);
        audit(LAYOUT_RESET);
        if (field<uintptr_t>(layout, 0x98) || field<uintptr_t>(layout, 0xa0) ||
            field<uintptr_t>(layout, 0x68) || field<uintptr_t>(layout, 0x80) ||
            field<uintptr_t>(layout, 0x88)) { r.stage.store(INVARIANT_FAILED); return; }
        c.string_cleanup(static_cast<unsigned char*>(layout)+8);
        c.string_cleanup(static_cast<unsigned char*>(layout)+0x18);
        audit(LAYOUT_STRINGS_CLEAN);
        c.deallocate(layout); r.retained.fetch_sub(1);
        audit(LAYOUT_FREED);
        for (unsigned i=0; i<2; ++i) {
            c.csv_cleanup(csv[i]); r.csv_cleaned.fetch_add(1);
            audit(i==0?CSV0_CLEAN:CSV1_CLEAN);
            c.deallocate(csv[i]); r.retained.fetch_sub(1);
            audit(i==0?CSV0_FREED:CSV1_FREED);
        }
        for (auto& name : names) c.string_cleanup(name);
        audit(NAMES_CLEAN);
        r.freed.store(1); r.stage.store(FREED);
        audit(FINISHED);
    } catch (...) {
        r.stage.store(EXCEPTION); // No speculative cleanup of half-native objects.
    }
}
} // namespace private_map
