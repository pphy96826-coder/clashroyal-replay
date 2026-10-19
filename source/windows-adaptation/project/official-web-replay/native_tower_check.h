#pragma once
// Inspect only the newly created private/local Battle. Never replace a tower
// definition or mutate the shared catalog to make a source appear supported.
template<class Tower,class Readable>
bool native_towers_match(uintptr_t base,uintptr_t domain,uintptr_t battle,
                         const Tower (&expected)[2][3],const unsigned (&support)[2][2],
                         Readable within,uint64_t* evidence=nullptr){
    for(unsigned side=0;side<2;++side){
        auto deck=read<uintptr_t>(battle+0x88+side*8);
        if(!within(deck,0x58))return false;
        int n=read<int>(deck+0x4c);
        if(support[side][0]==169000000){if(n!=0)return false;}
        else{
            auto array=read<uintptr_t>(deck+0x40);
            if(n!=1||!within(array,8))return false;
            auto card=read<uintptr_t>(array);
            if(!within(card,0x30)||read<unsigned>(card+0x20)!=support[side][1])return false;
            auto definition=read<uintptr_t>(card+0x18);
            if(!within(definition,0x48)||read<unsigned>(definition+0x40)!=support[side][0])return false;
        }
    }
    auto manager=read<uintptr_t>(domain+0x40);
    if(!within(manager,0x28)||read<int>(manager+0x14)!=6)return false;
    auto array=read<uintptr_t>(manager+8);
    if(!within(array,48))return false;
    unsigned seen=0;
    for(unsigned i=0;i<6;++i){
        auto object=read<uintptr_t>(array+i*8);
        if(!within(object,0x210))return false;
        auto definition=read<uintptr_t>(object+0x48);
        if(!within(definition,0x48))return false;
        auto id=read<unsigned>(definition+0x40);
        int owner=read<int>(object+0x78),x=read<int>(object+0x7c),y=read<int>(object+0x80);
        if(owner<0||owner>1)return false;
        int match=-1;
        for(unsigned j=0;j<3;++j){auto& e=expected[owner][j];
            if(e.id==id&&e.x==x&&e.y==y&&read<int>(object+0x120)==e.level)match=owner*3+j;
        }
        if(match<0||(seen&(1u<<match)))return false;
        seen|=1u<<match;
        int n=read<int>(object+0x24);auto components=read<uintptr_t>(object+0x18);
        if(n<1||n>64||!within(components,n*8))return false;
        uintptr_t health=0;
        for(int j=0;j<n;++j){auto c=read<uintptr_t>(components+j*8);
            if(c&&within(c,0x24)&&read<uintptr_t>(c)==base+0x1c26f70){if(health)return false;health=c;}
        }
        if(!health)return false;
        int hp=read<int>(health+0x10),maximum=read<int>(health+0x20);
        if(hp<=0||hp>50000||hp!=maximum)return false;
        // Type-specific HP from the real native initialization matrix. This
        // is an assertion only, never a write into native health components.
        if(hp!=expected[owner][match%3].hp)return false;
        if(evidence){auto out=evidence+match*8;out[0]=owner;out[1]=id;out[2]=x;out[3]=y;
            out[4]=hp;out[5]=maximum;out[6]=read<int>(object+0x120);out[7]=expected[owner][match%3].king;}
    }
    return seen==63;
}
