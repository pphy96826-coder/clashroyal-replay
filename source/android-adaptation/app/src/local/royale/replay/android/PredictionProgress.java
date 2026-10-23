package local.royale.replay.android;

import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Same real preparation/simulation stages as the native console; no fake percent. */
final class PredictionProgress {
    private static String actor(String name){
        if(name.equals("GoldenKnight"))return "黄金圣骑";
        if(name.equals("BossBandit"))return "首领大盗";
        if(name.equals("goblinstein_doctor"))return "哥布林科学怪人";
        if(name.equals("TombstoneHero_Monster_Passive"))return "英雄墓碑";
        return name;
    }
    private static String clock(long tick){long seconds=Math.max(0,tick/20);return String.format(Locale.ROOT,"%d:%02d",seconds/60,seconds%60);}
    static String text(JSONObject state,long now){
        JSONObject p=state.optJSONObject("prediction_progress");if(p==null)return "";
        String text=p.optString("phase","预测中")+" · 第 "+p.optInt("candidate",0)+" 次预演 · 种子 "+p.optLong("seed",0)
            +"\n本分支固定 "+p.optInt("choice_count",0)+" 处技能选择；本阶段 "+Math.max(0,now-p.optLong("phase_started_at",now))+" 秒";
        if(state.optBoolean("skill_pool_mode",false)){
            int size=state.optInt("skill_pool_size",0),limit=state.optInt("skill_pool_screen_limit",2);
            text+="\n技能候选池："+size+" 组；"+(size>0?"首轮最多 "+Math.min(size,limit)+"/"+size+" 组代表候选，其余延后":"正在原种子或首个合格种子建池");
            JSONObject allocation=state.optJSONObject("alns_allocation");
            if(allocation!=null)text+="\n最近一轮（种子 "+allocation.optLong("seed",p.optLong("seed",0))+"）累计验证 "+allocation.optInt("tested_combinations",0)+" 组，待验证 "+allocation.optInt("deferred_pool_candidates",0)+" 组；精修新增 "+allocation.optInt("refinement_used",0)+"/"+allocation.optInt("refinement_budget_total",24);
        }
        JSONObject mutation=p.optJSONObject("same_cost_alns");if(mutation!=null)text+="\n同费用组合搜索："+mutation.optString("phase",mutation.optString("operator"))+"，变异技能位置 "+positions(mutation.optJSONArray("changed_indices"));
        JSONObject last=p.optJSONObject("last");
        if(last!=null){
            text+="\n上一分支：模拟到 "+clock(last.optLong("tick",0))+"，成功执行 "+last.optInt("accepted",0)+"/"+last.optInt("event_count",0)+" 条";
            text+="\n"+last.optString("reason","");
            if(!last.optString("failure_explanation","").isEmpty())text+="\n"+last.optString("failure_explanation");
            JSONArray next=last.optJSONArray("next_actors");
            if(next!=null&&next.length()>0){String names="";for(int i=0;i<next.length();i++)names+=(i==0?"":" / ")+actor(next.optString(i));text+="："+names;}
            JSONArray elixir=last.optJSONArray("elixir");String values="";
            if(elixir!=null)for(int i=0;i<elixir.length();i++){
                JSONObject row=elixir.optJSONObject(i);if(row==null||row.isNull("page")||row.isNull("simulated"))continue;
                values+=(values.isEmpty()?"":"；")+(row.optInt("owner",0)==0?"蓝":"红")+String.format(Locale.ROOT," %.4f / 网页 %.2f",row.optDouble("simulated"),row.optDouble("page"));
            }
            if(!values.isEmpty())text+="\n溢出圣水："+values;
            JSONArray skills=last.optJSONArray("skills");
            if(skills!=null&&skills.length()>0){JSONObject skill=skills.optJSONObject(skills.length()-1);if(skill!=null)text+="\n最近技能："+clock(skill.optLong("tick",0))+" "+(skill.optInt("owner",0)==0?"蓝方 ":"红方 ")+actor(skill.optString("actor",""))+"（"+skill.optInt("cost",-1)+" 圣水）";}
        }
        JSONObject best=p.optJSONObject("best");
        text+=best==null?"\n尚无溢出圣水与网页一致的完整组合":"\n已见最小综合差距：六塔血差 "+best.optInt("hp_difference",0)+String.format(Locale.ROOT,"，终局差 %+.2f 秒",best.optDouble("time_difference_seconds",0))+"，综合差距 "+best.optInt("match_cost",0)+"（含终局时间和溢出圣水）";
        if(best!=null&&best.has("time_penalty"))text+="\n计分：塔血差 "+number(best,"hp_difference")+" + 时间罚分 "+number(best,"time_penalty")+" + 圣水罚分 "+number(best,"elixir_penalty");
        if(!p.optString("narration_error","").isEmpty())text+="\n部分播报不可用："+p.optString("narration_error");
        return text;
    }
    private static String number(JSONObject value,String key){return value.isNull(key)?"未知":value.optString(key,"未知");}
    private static String positions(JSONArray values){
        String result="";if(values!=null)for(int i=0;i<values.length();i++)result+=(i==0?"":"、")+(values.optInt(i,-1)+1);return result;
    }
    private PredictionProgress(){}
}
