"""Build the Android tutorial (HTML + PDF) from android/README.md; no device/network IO."""
from pathlib import Path
import html
import re
import sys
from PIL import Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate,Paragraph,Spacer,Image as PDFImage,PageBreak,
                                Table,TableStyle,KeepTogether)

ROOT=Path(__file__).resolve().parents[1]
DOCS=ROOT/'android'
SOURCE=DOCS/'README.md'
FONT=Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')
VERSION='hotfix54 / 2026-10-21'


def blocks(text):
    lines=text.splitlines();i=0
    while i<len(lines):
        line=lines[i]
        if not line.strip():i+=1;continue
        if line.startswith('```'):
            code=[];i+=1
            while i<len(lines) and not lines[i].startswith('```'):code.append(lines[i]);i+=1
            yield 'code','\n'.join(code);i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].startswith('|'):
                cells=[c.strip() for c in lines[i].strip('|').split('|')]
                if not all(re.fullmatch(r'-+',c) for c in cells):rows.append(cells)
                i+=1
            yield 'table',rows;continue
        if re.fullmatch(r'!\[([^]]*)\]\(([^)]+)\)',line):
            # Consecutive screenshots are shown side by side.
            images=[]
            while i<len(lines):
                match=re.fullmatch(r'!\[([^]]*)\]\(([^)]+)\)',lines[i])
                if not match:break
                images.append(match.groups());i+=1
            yield 'images',images;continue
        for prefix,kind in (('### ','h3'),('## ','h2'),('# ','h1')):
            if line.startswith(prefix):yield kind,line[len(prefix):];i+=1;break
        else:
            if re.match(r'^(?:- |[0-9]+\. )',line):yield 'item',line;i+=1;continue
            paragraph=[line];i+=1
            while i<len(lines) and lines[i].strip() and not re.match(r'^(?:#|```|!\[|\||- |[0-9]+\. )',lines[i]):
                paragraph.append(lines[i]);i+=1
            yield 'p',' '.join(paragraph)


def inline(text,pdf=False):
    escaped=html.escape(text)
    escaped=re.sub(r'\[([^]]+)\]\(([^)]+)\)',lambda m:('<link href="'+m[2]+'" color="#176180">'+m[1]+'</link>') if pdf else ('<a href="'+m[2]+'">'+m[1]+'</a>'),escaped)
    escaped=re.sub(r'\*\*(.+?)\*\*',r'<b>\1</b>',escaped)
    escaped=re.sub(r'`([^`]+)`',r'<font color="#1b5570">\1</font>' if pdf else r'<code>\1</code>',escaped)
    return escaped


def build_html(parts):
    toc=[];body=[];opened=False;index=0
    for kind,value in parts:
        if kind in ('h1','h2'):
            if opened:body.append('</section>')
            anchor='s'+str(index);index+=1;body.append('<section id="'+anchor+'">');opened=True
            body.append('<'+kind+'>'+inline(value)+'</'+kind+'>');toc.append('<a href="#'+anchor+'">'+html.escape(value)+'</a>')
        elif kind=='h3':body.append('<h3>'+inline(value)+'</h3>')
        elif kind=='images':
            body.append('<div class="shots">'+''.join('<figure><img src="'+html.escape(src)+'" alt="'+html.escape(alt)+'" loading="lazy"><figcaption>'+html.escape(alt)+'</figcaption></figure>' for alt,src in value)+'</div>')
        elif kind=='code':body.append('<pre>'+html.escape(value)+'</pre>')
        elif kind=='table':
            head,*rows=value
            body.append('<table><tr>'+''.join('<th>'+inline(c)+'</th>' for c in head)+'</tr>'+''.join('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in row)+'</tr>' for row in rows)+'</table>')
        else:body.append('<p'+(' class="step"' if kind=='item' else '')+'>'+inline(value)+'</p>')
    if opened:body.append('</section>')
    css='''*{box-sizing:border-box}body{margin:0;background:#eef3f8;color:#20364c;font:17px/1.85 system-ui,sans-serif}nav{position:fixed;left:0;top:0;width:270px;height:100vh;overflow:auto;padding:24px;background:#142841;color:white}nav a{display:block;color:#d9e8f6;padding:6px 0;font-size:14px;text-decoration:none}main{max-width:1100px;margin-left:270px;padding:35px}section{background:white;border:1px solid #dce5ee;border-radius:16px;margin:0 0 25px;padding:30px}h1{font-size:30px;line-height:1.45}h2{font-size:25px;color:#163f63}h3{font-size:20px;color:#1d5277;margin-top:26px}a{color:#076d9b;overflow-wrap:anywhere}code{background:#eff5fa;padding:2px 5px;border-radius:4px;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:18px;background:#152b44;color:#e4eff9;border-radius:10px;font:14px/1.7 ui-monospace,monospace}.step{border-left:3px solid #74b9bd;padding-left:14px}.shots{display:flex;flex-wrap:wrap;gap:18px;margin:20px 0}.shots figure{margin:0;width:260px}.shots img{width:100%;border:1px solid #cfdbe6;border-radius:14px}figcaption{font-size:13px;color:#607a90;line-height:1.5;margin-top:6px}table{border-collapse:collapse;margin:16px 0;width:100%}th,td{border:1px solid #d5e0ea;padding:8px 12px;text-align:left}th{background:#eef4f9}@media(max-width:900px){nav{position:relative;width:auto;height:auto}nav a{display:inline-block;margin-right:14px}main{margin:0;padding:12px}section{padding:18px}.shots figure{width:46%}}'''
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>安卓适配图文教程</title><style>'+css+'</style><nav><h3>安卓适配图文教程</h3>'+''.join(toc)+'</nav><main>'+''.join(body)+'</main></html>'
    (DOCS/'安卓适配图文教程.html').write_text(page)


def build_pdf(parts):
    pdfmetrics.registerFont(TTFont('ManualCJK',str(FONT)))
    pdfmetrics.registerFontFamily('ManualCJK',normal='ManualCJK',bold='ManualCJK',italic='ManualCJK',boldItalic='ManualCJK')
    common=dict(fontName='ManualCJK',wordWrap='CJK',textColor=colors.HexColor('#233d53'))
    normal=ParagraphStyle('Body',fontSize=10.2,leading=16,spaceAfter=8,**common)
    item=ParagraphStyle('Item',parent=normal,leftIndent=10,spaceAfter=5)
    caption=ParagraphStyle('Caption',fontSize=7.8,leading=11,alignment=1,**common)
    h2=ParagraphStyle('H2',fontSize=18,leading=25,spaceAfter=14,**common)
    h3=ParagraphStyle('H3',fontSize=13.5,leading=20,spaceBefore=8,spaceAfter=8,**common)
    title=ParagraphStyle('Title',fontSize=23,leading=31,spaceAfter=16,**common)
    code=ParagraphStyle('Code',fontSize=8,leading=12,spaceAfter=10,borderPadding=8,backColor=colors.HexColor('#edf3f7'),**common)
    cell=ParagraphStyle('Cell',fontSize=9.2,leading=13,**common)
    story=[]
    for kind,value in parts:
        if kind=='h1':story.append(Paragraph(inline(value,True),title))
        elif kind=='h2':story+= [PageBreak(),Paragraph(inline(value,True),h2)]
        elif kind=='h3':story.append(Paragraph(inline(value,True),h3))
        elif kind=='images':
            for start in range(0,len(value),3):
                group=value[start:start+3];cells=[]
                for alt,src in group:
                    width,height=Image.open(DOCS/src).size;w=150;h=w*height/width
                    cells.append([PDFImage(str(DOCS/src),width=w,height=h),Spacer(1,4),Paragraph(html.escape(alt),caption)])
                table=Table([cells],colWidths=[168]*len(group))
                table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('ALIGN',(0,0),(-1,-1),'CENTER')]))
                story+= [KeepTogether(table),Spacer(1,10)]
        elif kind=='code':story.append(Paragraph('<br/>'.join(html.escape(l).replace(' ','&#160;') for l in value.splitlines()),code))
        elif kind=='table':
            data=[[Paragraph(inline(c,True),cell) for c in row] for row in value]
            widths=[150,359] if len(data[0])==2 else [509/len(data[0])]*len(data[0])
            table=Table(data,colWidths=widths)
            table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#c9d6e2')),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eef4f9')),('VALIGN',(0,0),(-1,-1),'TOP')]))
            story+= [table,Spacer(1,10)]
        else:story.append(Paragraph(inline(value,True),item if kind=='item' else normal))
    def footer(canvas,doc):
        canvas.setFont('ManualCJK',8);canvas.setFillColor(colors.HexColor('#60768b'))
        canvas.drawString(43,22,'Royale HTML Replay · Android · '+VERSION);canvas.drawRightString(552,22,str(doc.page))
    SimpleDocTemplate(str(DOCS/'安卓适配图文教程.pdf'),pagesize=(595.28,841.89),rightMargin=43,leftMargin=43,topMargin=40,bottomMargin=43,
                      title='安卓适配图文教程',author='Clashroyal Replay Project').build(story,onFirstPage=footer,onLaterPages=footer)


def main():
    parts=list(blocks(SOURCE.read_text()))
    missing=[src for kind,value in parts if kind=='images' for _,src in value if not (DOCS/src).is_file()]
    if missing:sys.exit('missing images: '+', '.join(missing))
    build_html(parts);build_pdf(parts)
    print('HTML and PDF generated:',sum(len(v) for k,v in parts if k=='images'),'screenshots')


if __name__=='__main__':main()
