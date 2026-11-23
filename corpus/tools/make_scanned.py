import fitz,sys
src,dst=sys.argv[1],sys.argv[2]
d=fitz.open(src);o=fitz.open()
for p in d:
    pix=p.get_pixmap(dpi=110,colorspace=fitz.csGRAY)
    np_=o.new_page(width=p.rect.width,height=p.rect.height)
    np_.insert_image(np_.rect,stream=pix.tobytes("jpeg",jpg_quality=60))
o.save(dst,garbage=4,deflate=True)
