"""Generate the offline manual from one Markdown source; no device/network IO."""
from pathlib import Path
import html
import re
import textwrap
from PIL import Image,ImageDraw,ImageFont
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Image as PDFImage,PageBreak,KeepTogether

ROOT=Path(__file__).resolve().parents[1]
DOCS=ROOT/'docs'
FONT=Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')


def diagram(name,title,cards,footer):
    image=Image.new('RGB',(1400,520),'#eff4fa');draw=ImageDraw.Draw(image)
    big=ImageFont.truetype(str(FONT),36);normal=ImageFont.truetype(str(FONT),27);small=ImageFont.truetype(str(FONT),22)
    draw.text((44,28),title,font=big,fill='#142641')
    draw.text((44,82),'操作示意 / 非实机截图',font=small,fill='#526a84')
    count=len(cards);gap=40;left=42;width=(1316-gap*(count-1))//count
    for i,(head,lines) in enumerate(cards):
        x=left+i*(width+gap)
        draw.rounded_rectangle((x,144,x+width,420),radius=18,fill='white',outline='#cbd9e7',width=2)
        draw.rounded_rectangle((x+14,160,x+width-14,216),radius=10,fill='#174e77')
        draw.text((x+26,170),head,font=normal,fill='white')
        y=242
        for line in lines:
            # Fixed-length illustrations, checked visually after rendering.
            for wrapped in textwrap.wrap(line,width=max(10,int((width-42)/27))):
                draw.text((x+22,y),wrapped,font=normal,fill='#243c54');y+=40
        if i<count-1:
            center=x+width+gap//2;draw.text((center-12,288),'>',font=big,fill='#267f8c')
    draw.text((44,458),footer,font=small,fill='#435f78')
    image.save(DOCS/'images'/('manual-'+name+'.png'))


def pictures():
    (DOCS/'images').mkdir(exist_ok=True)
    diagram('routes','先选环境，再下载安装包',[
        ('安卓本机',['已有 Root 环境','游戏与控制台同系统']),('电脑本机',['Windows / Mac','绑定现有 MuMu']),('手机观看',['安卓 / iPhone','远程控制自己的电脑'])],
        '手机虚拟机须逐步验收；iOS 本机模拟仍是研究方向。')
    diagram('android','安卓控制台：首次播放的顺序',[
        ('1 游戏大厅',['先完成本人登录','不进入在线对局']),('2 选择 HTML',['确认已有 Root','允许悬浮进度卡']),('3 校验与开播',['等待完整预演','实际步进后看游戏'])],
        '失败时点“导出诊断”；不要反复提交或清除数据。')
    diagram('browser','普通浏览器登录，点击时才传输',[
        ('1 Replay 详情',['本人完成网站登录','等待完整回放数据']),('2 桥接按钮',['安卓：用户脚本','电脑：桌面扩展']),('3 控制台确认',['核对回放编号','已有对局则排队'])],
        '手机桥接发给同设备控制台；不会把手机 localhost 当成电脑。')
    diagram('guest','非 Root 手机：外层系统与客体分开',[
        ('外层手机',['保持非 Root','安装厂商虚拟机']),('虚拟安卓系统',['客体已有 Root','游戏 + 控制台 + HTML']),('兼容性验收',['游戏稳定进入大厅','短场完整核验与播放'])],
        '外层游戏不能服务客体控制台；MuMu ROM 不能直接当 VMOS 镜像。')
    diagram('windows','Windows：先完整环境，再同步更新',[
        ('1 完整解压',['三卷 ZIP + 合并脚本','保留 app / tools 结构']),('2 安装向导',['选择实际 MuMu 实例','保存 > 检查 > 准备']),('3 应用更新',['Update-Windows.cmd','目标是旧环境根目录'])],
        '不要替换 Windows 的专用 MuMu 翻译运行时；不覆盖播放中的文件。')
    diagram('mac','Mac：源码 Skill 的四步部署',[
        ('1 核验依赖',['Apple Silicon','Python / CLT / NDK']),('2 新目录安装',['绑定已有实例目录','本机编译签名 App']),('3 本机运行时',['本人确认调试准备','重新读取该机客户端'])],
        'doctor 通过不是回放成功；具体对局仍需可见播放核对。')
    diagram('remote','非 Root 安卓 / iPhone：远程观看自己的电脑',[
        ('电脑运行',['控制台 + 安卓模拟器','先验证本地播放']),('本人确认连接',['输入电脑设备 ID','不公开密码/验证码']),('手机观看',['接收画面与触控','不需要手机 Root'])],
        '电脑须保持运行；远程传输不是手机本机调用官方引擎。')
    diagram('export','三端导出诊断：不再找 Root 目录',[
        ('1 导出诊断',['安卓：页面下方','Mac/Win：导出诊断…']),('2 选择位置',['本机 Download','保存新的 ZIP 文件']),('3 私下发送',['等待“已保存”提示','附版本与错误截图'])],
        '无原始 HTML、游戏 APK 或浏览器 Cookie；仍含路径、进程和回放记录。')


def blocks(text):
    lines=text.splitlines();i=0
    while i<len(lines):
        line=lines[i]
        if not line.strip():i+=1;continue
        if line.startswith('```'):
            code=[];i+=1
            while i<len(lines) and not lines[i].startswith('```'):code.append(lines[i]);i+=1
            yield 'code','\n'.join(code);i+=1;continue
        match=re.fullmatch(r'!\[([^]]*)\]\(([^)]+)\)',line)
        if match:yield 'image',match.groups();i+=1;continue
        if line.startswith('## '):yield 'h2',line[3:];i+=1;continue
        if line.startswith('# '):yield 'h1',line[2:];i+=1;continue
        if re.match(r'^(?:- |[0-9]+\. )',line):yield 'item',line;i+=1;continue
        paragraph=[line];i+=1
        while i<len(lines) and lines[i].strip() and not re.match(r'^(?:#|```|!\[|- |[0-9]+\. )',lines[i]):paragraph.append(lines[i]);i+=1
        yield 'p',' '.join(paragraph)


def inline(text,pdf=False):
    escaped=html.escape(text)
    escaped=re.sub(r'\[([^]]+)\]\(([^)]+)\)',lambda m:('<link href="'+m[2]+'" color="#176180">'+m[1]+'</link>') if pdf else ('<a href="'+m[2]+'">'+m[1]+'</a>'),escaped)
    escaped=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',escaped)
    escaped=re.sub(r'`([^`]+)`',r'<font color="#1b5570">\1</font>' if pdf else r'<code>\1</code>',escaped)
    return escaped


def main():
    pictures();text=(DOCS/'全平台安装教程.md').read_text();parts=list(blocks(text))
    toc=[];body=[];opened=False;index=0
    for kind,value in parts:
        if kind in ('h1','h2'):
            if opened:body.append('</section>')
            anchor='section-'+str(index);index+=1;body.append('<section id="'+anchor+'">');opened=True
            body.append('<'+kind+'>'+inline(value)+'</'+kind+'>');toc.append('<a href="#'+anchor+'">'+html.escape(value)+'</a>')
        elif kind=='image':body.append('<figure><img src="'+html.escape(value[1])+'" alt="'+html.escape(value[0])+'"><figcaption>'+html.escape(value[0])+' · 操作示意</figcaption></figure>')
        elif kind=='code':body.append('<pre>'+html.escape(value)+'</pre>')
        else:body.append('<p'+(' class="step"' if kind=='item' else '')+'>'+inline(value)+'</p>')
    if opened:body.append('</section>')
    css='''*{box-sizing:border-box}body{margin:0;background:#eef3f8;color:#20364c;font:17px/1.85 system-ui,sans-serif}nav{position:fixed;left:0;top:0;width:270px;height:100vh;overflow:auto;padding:24px;background:#142841;color:white}nav a{display:block;color:#d9e8f6;padding:7px 0;font-size:14px;text-decoration:none}main{max-width:1180px;margin-left:270px;padding:35px}section{background:white;border:1px solid #dce5ee;border-radius:16px;margin:0 0 25px;padding:30px}h1{font-size:31px;line-height:1.45}h2{font-size:26px;line-height:1.5;color:#163f63}a{color:#076d9b;overflow-wrap:anywhere}code{background:#eff5fa;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:20px;background:#152b44;color:#e4eff9;border-radius:10px;font:14px/1.75 ui-monospace,monospace}.step{border-left:3px solid #74b9bd;padding-left:14px}img{max-width:100%;height:auto}figure{margin:22px 0}figcaption{font-size:13px;color:#607a90}b{color:#173b5b}@media(max-width:900px){nav{position:relative;width:auto;height:auto}nav a{display:inline-block;margin-right:16px}main{margin:0;padding:12px}section{padding:20px}}@media print{nav{display:none}main{margin:0;padding:0}section{page-break-before:always;border:0;padding:0}section:first-child{page-break-before:auto}a{color:inherit}pre{color:#20364c;background:#edf3f7}}'''
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>官服回放 · 全平台安装图文手册</title><style>'+css+'</style><nav><h3>全平台安装手册</h3>'+''.join(toc)+'</nav><main>'+''.join(body)+'</main></html>'
    (DOCS/'全平台安装教程.html').write_text(page)
    pdfmetrics.registerFont(TTFont('ManualCJK',str(FONT)))
    pdfmetrics.registerFontFamily('ManualCJK',normal='ManualCJK',bold='ManualCJK',italic='ManualCJK',boldItalic='ManualCJK')
    common=dict(fontName='ManualCJK',wordWrap='CJK',textColor=colors.HexColor('#233d53'))
    normal=ParagraphStyle('Body',fontSize=10.2,leading=16,spaceAfter=8,**common)
    item=ParagraphStyle('Item',parent=normal,leftIndent=10,firstLineIndent=-3,spaceAfter=6)
    heading=ParagraphStyle('Heading',fontSize=19,leading=26,spaceAfter=17,**common)
    title=ParagraphStyle('Title',fontSize=25,leading=33,spaceAfter=17,**common)
    code=ParagraphStyle('Code',fontSize=8.1,leading=12,spaceAfter=10,borderPadding=8,backColor=colors.HexColor('#edf3f7'),**common)
    story=[]
    for kind,value in parts:
        if kind=='h2':story.append(PageBreak());story.append(Paragraph(inline(value,True),heading))
        elif kind=='h1':story.append(Paragraph(inline(value,True),title))
        elif kind=='image':
            picture=PDFImage(str(DOCS/value[1]),width=500,height=185.72)
            story.extend([picture,Spacer(1,10)])
        elif kind=='code':story.append(Paragraph('<br/>'.join(html.escape(line).replace(' ','&#160;') for line in value.splitlines()),code))
        else:story.append(Paragraph(inline(value,True),item if kind=='item' else normal))
    def footer(canvas,doc):
        canvas.setFont('ManualCJK',8);canvas.setFillColor(colors.HexColor('#60768b'))
        canvas.drawString(43,22,'Royale HTML Replay / hotfix3 / 2026-10-19')
        canvas.drawRightString(552,22,str(doc.page))
    document=SimpleDocTemplate(str(DOCS/'全平台安装教程.pdf'),pagesize=(595.28,841.89),rightMargin=43,leftMargin=43,topMargin=40,bottomMargin=43,title='官服回放全平台安装图文手册',author='Clashroyal Replay Project')
    document.build(story,onFirstPage=footer,onLaterPages=footer)
    print('HTML, PDF and 8 illustrations generated')


if __name__=='__main__':main()
