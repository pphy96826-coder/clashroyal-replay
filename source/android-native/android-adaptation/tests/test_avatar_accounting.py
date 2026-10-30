"""Compile the shipped layout reader against deliberately conflicting fields."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class AvatarAccountingTests(unittest.TestCase):
    def test_each_version_reads_current_spent_gained_leaked_in_the_same_order(self):
        source=r'''
#include "client_layout.h"
#include <cassert>
#include <array>
int main(){
    using namespace client_layout;
    for(auto layout:{avatar_3842,avatar_3852}){
        alignas(16) unsigned char memory[0x420];
        std::memset(memory,0x55,sizeof(memory));
        const std::array<int,4> expected{43210,30000,98765,0};
        const std::size_t offsets[]{layout.current,layout.spent,layout.gained,layout.leaked};
        for(unsigned i=0;i<4;++i)std::memcpy(memory+offsets[i],&expected[i],4);
        auto root=reinterpret_cast<std::uintptr_t>(memory);
        assert(elixir_snapshot(root,layout)==expected);
        auto wrong=layout.current==avatar_3842.current?avatar_3852:avatar_3842;
        assert(elixir_snapshot(root,wrong)!=expected);
        int leaked=123456;std::memcpy(memory+layout.leaked,&leaked,4);
        auto next=elixir_snapshot(root,layout);
        assert(next[0]==expected[0]&&next[1]==expected[1]&&next[2]==expected[2]&&next[3]==leaked);
    }
    static_assert(active_avatar.current==0x300,"pending adapter was enabled");
    static_assert(domain_3842.allocation_bytes==0x240&&domain_3852.allocation_bytes==0x248);
    static_assert(deal_3852.hand==0x220&&deal_3852.hand_count==0x22c);
    static_assert(deal_3852.queue==0x230&&deal_3852.queue_count==0x23c);
    static_assert(active_deal.hand==deal_3842.hand&&active_domain.allocation_bytes==0x240);
    alignas(16) std::uintptr_t methods[64]{};
    methods[unit_3842.ready_slot/8]=0x1234;
    methods[unit_3852.ready_slot/8]=0x5678;
    auto table=reinterpret_cast<std::uintptr_t>(methods);
    assert(ability_ready_method(table,unit_3842)==0x1234);
    assert(ability_ready_method(table,unit_3852)==0x5678);
    static_assert(unit_3842.ready_slot+8<=unit_3842.table_extent);
    static_assert(unit_3852.ready_slot+8<=unit_3852.table_extent);
    static_assert(active_unit.ready_slot==0x190,"pending unit layout was enabled");
    static_assert(controller_3842.presentation_handle==0x2b0);
    static_assert(controller_3852.presentation_handle==0x2c8);
    static_assert(active_controller.presentation_handle==controller_3842.presentation_handle);
    constexpr std::uintptr_t base=0x100000000;
    assert(contains_vtable(base,base+0x1c26f70,24,vtables_3842));
    assert(!contains_vtable(base,base+0x1d70000,24,vtables_3842));
    assert(contains_vtable(base,base+0x1d70000,24,vtables_3852));
    assert(!contains_vtable(base,base+vtables_3852.last-8,24,vtables_3852));
    assert(!contains_vtable(base,base-1,24,vtables_3852));
    assert(!contains_vtable(base,base+vtables_3852.first,~std::size_t(0),vtables_3852));
}
'''
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'test.cpp').write_text(source)
            # This host has a newer SDK than its installed linker's TAPI reader.
            # Select an existing compatible SDK for this host-only unit binary.
            sdk=Path('/Library/Developer/CommandLineTools/SDKs/MacOSX15.4.sdk')
            flags=['-isysroot',str(sdk),'-mmacosx-version-min=15.0'] if sdk.is_dir() else []
            subprocess.run([shutil.which('clang++'),*flags,'-std=c++17','-Wall','-Wextra','-Werror',
                            '-I'+str(ROOT/'runtime-source/official-web-replay'),str(path/'test.cpp'),
                            '-o',str(path/'check')],check=True,capture_output=True)
            subprocess.run([str(path/'check')],check=True,capture_output=True)

if __name__=='__main__':unittest.main()
