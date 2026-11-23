import sys; sys.path.insert(0,'.')
from gov_text import text,blocks
from pptx import Presentation
from pptx.util import Pt
def build(path,out,deck_title,maxslides,maxitems=5):
    d,b=text(path); bl=blocks(b)
    secs=[];cur=None
    for t,x in bl:
        if t in('h2','h3'): cur=[x,[]];secs.append(cur)
        elif cur is not None: cur[1].append(x)
    url="https://www.gov.uk/"+path.strip('/')
    pr=Presentation(); 
    s=pr.slides.add_slide(pr.slide_layouts[0]); s.shapes.title.text=deck_title
    s.placeholders[1].text="Slides assembled verbatim from the GOV.UK page below (Open Government Licence v3.0)\n"+url
    n=0
    for h,items in secs:
        if not items or n>=maxslides: continue
        s=pr.slides.add_slide(pr.slide_layouts[1]); s.shapes.title.text=h
        tf=s.placeholders[1].text_frame; tf.text=items[0]
        for it in items[1:maxitems]: tf.add_paragraph().text=it
        for p in tf.paragraphs:
            for r in p.runs: r.font.size=Pt(16)
        s.notes_slide.notes_text_frame.text="Source: "+url
        n+=1
    pr.save(out); print(out,len(pr.slides.slides) if hasattr(pr.slides,'slides') else len(pr.slides))
R="D:/docmap/corpus/raw/"
build("government/publications/fisheries-annual-report-2024-to-2025-how-we-spend-fishing-licence-income/fisheries-annual-report-2024-to-2025-how-we-spend-fishing-licence-income",R+"fin-03-fisheries-licence-income-2024-25.pptx","Fisheries annual report 2024 to 2025: how we spend fishing licence income",6,6)
build("government/publications/environment-agency-pay-gap/environment-agency-pay-gap-2025",R+"hr-04-ea-pay-gap-2025.pptx","Environment Agency: pay gap 2025",7,5)
build("guidance/download-environmental-data",R+"dig-05-access-environmental-data.pptx","Access environmental data (Defra Data Services Platform)",5,6)
