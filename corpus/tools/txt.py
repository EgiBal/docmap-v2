import sys,pypdf
for f in sys.argv[1:]:
    r=pypdf.PdfReader(f); n=len(r.pages)
    t=[len(r.pages[i].extract_text() or '') for i in range(min(n,6))]
    print(f,n,t)
