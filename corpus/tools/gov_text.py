import json,urllib.request,re,sys,html
def text(path):
    d=json.load(urllib.request.urlopen("https://www.gov.uk/api/content/"+path.strip('/')))
    b=d['details'].get('body') or ''
    return d,b
def blocks(b):
    # yield (tag,text) for h2/h3/p/li
    out=[]
    for m in re.finditer(r'<(h2|h3|p|li)[^>]*>(.*?)</\1>',b,re.S):
        t=html.unescape(re.sub(r'<[^>]+>','',m.group(2))).strip()
        if t: out.append((m.group(1),t))
    return out
if __name__=="__main__":
    d,b=text(sys.argv[1]); 
    for t,x in blocks(b)[:int(sys.argv[2])]: print(t,'|',x[:220])
