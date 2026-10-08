"""Generate a small original SENTRA icon (no proprietary source assets)."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

def make_icon():
    size=256
    img=Image.new("RGBA",(size,size),(0,0,0,0))
    draw=ImageDraw.Draw(img)
    draw.rounded_rectangle((12,12,244,244),radius=57,fill="#24262B")
    draw.rounded_rectangle((12,12,244,244),radius=57,outline="#4A4E58",width=3)
    draw.line((58,204,198,204),fill="#70DCC6",width=9)
    font_path=Path("C:/Windows/Fonts/segoeuib.ttf")
    font=ImageFont.truetype(str(font_path),145) if font_path.exists() else ImageFont.load_default()
    bbox=draw.textbbox((0,0),"S",font=font)
    x=(size-(bbox[2]-bbox[0]))/2-bbox[0]
    y=(size-(bbox[3]-bbox[1]))/2-bbox[1]-14
    draw.text((x,y),"S",font=font,fill="#E7E9EA")
    dest=Path(__file__).parent/"assets"/"SENTRA.ico"
    img.save(dest,format="ICO",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    print(dest)

if __name__=="__main__":make_icon()
