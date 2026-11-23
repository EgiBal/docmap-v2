import sys,glob,os,pypdf,docx,openpyxl,pptx
for f in sorted(glob.glob('D:/docmap/corpus/raw/*')):
    n=os.path.basename(f);e=n.rsplit('.',1)[1];t=''
    try:
        if e=='pdf':
            r=pypdf.PdfReader(f);t=' '.join((r.pages[i].extract_text() or '') for i in range(min(3,len(r.pages))))
        elif e=='docx':
            t=' '.join(p.text for p in docx.Document(f).paragraphs[:40])
        elif e=='xlsx':
            wb=openpyxl.load_workbook(f,read_only=True);t='SHEETS:'+','.join(wb.sheetnames[:8])+' | '
            ws=wb[wb.sheetnames[0]]
            for i,row in enumerate(ws.iter_rows(values_only=True)):
                if i>12:break
                t+=' '.join(str(c) for c in row if c is not None)+' / '
        elif e=='pptx':
            t=' '.join(sh.text_frame.text for s in pptx.Presentation(f).slides for sh in s.shapes if sh.has_text_frame)
    except Exception as ex: t='ERR '+str(ex)
    print('##',n,'\n',' '.join(t.split())[:450])
