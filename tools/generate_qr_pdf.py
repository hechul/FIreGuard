"""Portable A4 print sheet with embedded Korean fonts and exact 20mm QR images."""
from pathlib import Path
import sys

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qr_locations import QR_LOCATIONS


def main():
    font = Path('C:/Windows/Fonts/malgun.ttf')
    pdfmetrics.registerFont(TTFont('Korean', str(font)))
    output = ROOT / 'output/pdf/FireGuard_QR_A4_20mm.pdf'
    output.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output), pagesize=A4)
    c.setTitle('FireGuard - A4 QR - 20mm')
    c.setViewerPreference('PrintScaling', 'None')

    def text(x, y, value, size=10, centered=False):
        c.setFont('Korean', size)
        (c.drawCentredString if centered else c.drawString)(x*mm, y*mm, value)

    text(20, 273, 'FIREGUARD | 위치별 대피 안내 QR', 17)
    text(20, 261, 'A4 세로 / 실제 크기 100% / 용지에 맞춤 끄기', 10)
    text(20, 254, 'QR: 흰 여백 포함 20mm × 20mm. 점선을 따라 잘라 부착하세요.', 9)
    for i, loc in enumerate(QR_LOCATIONS):
        x, y = 40 + (i % 2)*70, 175 - (i // 2)*75
        c.setStrokeColorRGB(.55,.6,.65); c.setLineWidth(.4); c.setDash(2,2)
        c.rect(x*mm,y*mm,60*mm,65*mm)
        c.setDash(); c.setFillColorRGB(.08,.15,.21)
        text(x+30,y+57,'FIREGUARD',8,True)
        text(x+30,y+48,loc['label'],12,True)
        text(x+30,y+42,loc['id']+' | 현재 위치',8,True)
        c.drawImage(str(ROOT / 'static/images/qr' / (loc['id']+'.png')),
                    (x+20)*mm,(y+18)*mm,width=20*mm,height=20*mm)
        text(x+30,y+11,'카메라로 스캔하여',8,True)
        text(x+30,y+6,'이 위치의 대피경로를 확인하세요.',8,True)
    text(20,82,'인쇄 후 아래 선이 실제 5cm인지 자로 확인하세요.',10)
    c.setStrokeColorRGB(0,0,0); c.setLineWidth(.6)
    c.line(20*mm,73*mm,70*mm,73*mm)
    c.line(20*mm,73*mm,20*mm,76*mm); c.line(70*mm,73*mm,70*mm,76*mm)
    text(45,67,'50mm',9,True)
    text(20,55,'다른 PC에는 이 PDF 파일 하나만 옮기면 됩니다.',9)
    text(20,48,'QR 주변 흰 여백을 보존하고 부착 전에 스마트폰으로 확인하세요.',9)
    c.showPage(); c.save()
    reader = PdfReader(output)
    assert len(reader.pages) == 1
    assert abs(float(reader.pages[0].mediabox.width)-A4[0]) < .01
    assert abs(float(reader.pages[0].mediabox.height)-A4[1]) < .01
    for loc in QR_LOCATIONS:
        assert loc['label'] in reader.pages[0].extract_text()
    (ROOT / 'static/qr' / output.name).write_bytes(output.read_bytes())
    print(output)


if __name__ == '__main__':
    main()
