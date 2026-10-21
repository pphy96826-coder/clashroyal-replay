
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
struct ExpectedTower{unsigned id;int x,y,level,hp;bool king;};
static ExpectedTower bootstrap_towers[2][3];
#include "mumu_source_execution.h"
using namespace web_source;
alignas(16) unsigned char objects[7][0x210],definitions[7][0x48],healths[7][0x28],manager[0x28],domain[0x48],battle[0x200];
uintptr_t arrays[7],components[7],table[128];int destructions{};
template<class T>void put(void* p,size_t offset,T value){std::memcpy(static_cast<char*>(p)+offset,&value,sizeof(value));}
void deleted(void*){++destructions;}
bool readable(uintptr_t p,size_t n){
 for(auto r:{std::pair<uintptr_t,size_t>{(uintptr_t)objects,sizeof(objects)}, {(uintptr_t)definitions,sizeof(definitions)},
   {(uintptr_t)healths,sizeof(healths)},{(uintptr_t)manager,sizeof(manager)},{(uintptr_t)domain,sizeof(domain)},
   {(uintptr_t)battle,sizeof(battle)},{(uintptr_t)arrays,sizeof(arrays)},{(uintptr_t)components,sizeof(components)},
   {(uintptr_t)table,sizeof(table)}})if(p>=r.first&&p+n>=p&&p+n<=r.first+r.second)return true;
 return false;
}
void require(bool condition,const char* message){if(!condition){std::fprintf(stderr,"FAIL: %s\n",message);std::exit(1);}}
void setup(unsigned a,unsigned b,unsigned ka,unsigned kb){
 std::memset(objects,0,sizeof(objects));std::memset(definitions,0,sizeof(definitions));std::memset(healths,0,sizeof(healths));
 put(domain,0x40,(uintptr_t)manager);put(manager,0x14,6);put(manager,8,(uintptr_t)arrays);
 table[0]=(uintptr_t)deleted;table[1]=(uintptr_t)deleted;
 for(int i=0;i<7;++i){int owner=i/3;if(i==6)owner=0;int slot=i%3;unsigned id=slot?(owner?b:a):(owner?kb:ka);int x=slot?(slot==1?3500:14500):9000;int y=slot?6500:3000;if(owner)y=32000-y;
  arrays[i]=(uintptr_t)objects[i];components[i]=(uintptr_t)healths[i];
  put(objects[i],0x48,(uintptr_t)definitions[i]);put(definitions[i],0x40,id);
  put(objects[i],0x78,owner);put(objects[i],0x7c,x);put(objects[i],0x80,y);
  put(objects[i],0x24,1);put(objects[i],0x18,(uintptr_t)&components[i]);
  put(healths[i],0,(uintptr_t)table);put(healths[i],0x10,slot?100+i:7728);put(healths[i],0x20,7728);
  if(i<6)bootstrap_towers[owner][slot]={id,x,y,15,7728,slot==0};
 }
}
int main(){
 unsigned ids[]={35000001u,1485117103u,2545895475u,3191249505u};int cases=0;
 Calls c{(uintptr_t)table-0x1c26f70,0,readable,nullptr,nullptr};
 for(int a=0;a<4;++a)for(int b=0;b<4;++b){
  unsigned ka=a==3?1471932914u:35000000u,kb=b==3?1471932914u:35000000u;
  setup(ids[a],ids[b],ka,kb);Result result;
  require(watch_towers(c,result,(uintptr_t)domain)&&result.tower_watch_count==6,"all six watched");
  auto json=battle_diagnostics(c,(uintptr_t)domain,(uintptr_t)battle,&result);
  size_t pos=0;int count=0;while((pos=json.find("\"owner\":",pos))!=std::string::npos){++count;++pos;}require(count==6,"all six diagnostic records");
  put(healths[4],0x10,0);int previous=destructions;
  tower_destructor(healths[4]);require(destructions==previous+1&&result.tower_watch[4].destroyed,"destructor delegated exactly once");
  require(static_cast<unsigned>(result.tower_watch[4].id)==ids[b],"hashed destroyed ID retained");
  require(unwatch_towers(c,result),"living health vtables restored");
  for(int i=0;i<6;++i)if(i!=4)require(field<uintptr_t>((uintptr_t)healths[i])==(uintptr_t)table,"original vtable restored");
  for(int fault=0;fault<6;++fault){setup(ids[a],ids[b],ka,kb);Result bad;
   if(fault==0)put(definitions[5],0x40,123456u);
   if(fault==1)put(objects[5],0x78,2);
   if(fault==2)put(objects[5],0x7c,1234);
   if(fault==3)arrays[5]=arrays[4];
   if(fault==4)put(healths[5],0,(uintptr_t)0);
   if(fault==5)put(manager,0x14,7);
   require(!watch_towers(c,bad,(uintptr_t)domain),"invalid identity/missing/duplicate/seventh rejected");
   for(int i=0;i<6;++i)if(!(fault==4&&i==5))require(field<uintptr_t>((uintptr_t)healths[i])==(uintptr_t)table,"failed watch does not modify health vtables");
  }
  ++cases;
 }
 std::printf("{\"tower_pair_cases\":%d,\"negative_cases\":%d,\"destructor_cases\":%d,\"native_observer_fixture_verified\":true}\n",cases,cases*6,cases);return 0;
}
