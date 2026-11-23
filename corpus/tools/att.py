import sys,json,urllib.request
for p in sys.argv[1:]:
    try:
        d=json.load(urllib.request.urlopen("https://www.gov.uk/api/content/"+p.strip('/')))
    except Exception as e:
        print(p,"ERR",e);continue
    print("##",p,d['title'],d.get('details',{}).get('first_public_at','')[:10])
    for a in d['details'].get('attachments',[]):
        print(" ",a.get('content_type'),a.get('file_size'),a['url'],'|',a.get('title'))
