import json,urllib.request,urllib.parse,io,sys,pypdf
def get(u,n=None):
    req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
    return urllib.request.urlopen(req,timeout=40).read()
qs=["environment agency 2003 report","national rivers authority","environment agency 2001 guidance flood","environment agency 1999 strategy","environment agency 2005 annual report"]
seen=set()
for q in qs:
    u="https://www.gov.uk/api/search.json?"+urllib.parse.urlencode({'q':q+' environment agency pdf','count':30,'fields':'title,link'})
    r=json.loads(get(u))['results']
    for x in r:
        if x['link'] in seen: continue
        seen.add(x['link'])
        try: d=json.loads(get("https://www.gov.uk/api/content"+x['link']))
        except Exception: continue
        for a in d['details'].get('attachments',[]):
            if a.get('content_type')=='application/pdf' and (a.get('file_size') or 0)<4_000_000:
                try:
                    b=get(a['url']); rd=pypdf.PdfReader(io.BytesIO(b))
                    t=sum(len(rd.pages[i].extract_text() or '') for i in range(min(3,len(rd.pages))))
                    print(t,len(rd.pages),len(b),a['url'],x['title'][:50]);sys.stdout.flush()
                except Exception as e: pass
