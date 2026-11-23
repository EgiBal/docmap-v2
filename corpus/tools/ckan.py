import sys,json,urllib.request,urllib.parse
org,fmt=sys.argv[1],sys.argv[2]
q=sys.argv[3] if len(sys.argv)>3 else ''
u="https://ckan.publishing.service.gov.uk/api/3/action/package_search?"+urllib.parse.urlencode({'fq':f'organization:{org} res_format:{fmt}','q':q,'rows':40})
d=json.load(urllib.request.urlopen(u))['result']
print(d['count'])
for p in d['results']:
    for r in p['resources']:
        if r.get('format','').upper()==fmt.upper():
            print(p['title'][:70],'|',p.get('license_id'),'|',r['url'],'|',r.get('size'))
