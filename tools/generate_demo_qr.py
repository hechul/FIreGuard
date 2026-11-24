"""Generate four printable SVG placards and standalone QR images, offline."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qrcode
from jinja2 import Environment, FileSystemLoader, select_autoescape
from qr_locations import QR_LOCATIONS, mobile_url


def qr_svg(url):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    size = len(matrix)
    pixels = ''.join(f'<rect x="{x}" y="{y}" width="1" height="1"/>'
                     for y, row in enumerate(matrix) for x, dark in enumerate(row) if dark)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
            f'width="20mm" height="20mm" role="img" aria-label="대피 안내 QR">'
            f'<rect width="{size}" height="{size}" fill="white"/>'
            f'<g fill="black" shape-rendering="crispEdges">{pixels}</g></svg>')


def main():
    root = Path(__file__).resolve().parents[1]
    images = root / 'static/images/qr'
    images.mkdir(parents=True, exist_ok=True)
    for location in QR_LOCATIONS:
        url = mobile_url(location['id'])
        svg = qr_svg(url)
        (images / f"{location['id']}.svg").write_text(svg, encoding='utf-8')
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=20, border=4)
        qr.add_data(url); qr.make(fit=True)
        image = qr.make_image(fill_color='black', back_color='white')
        dpi = image.size[0] * 25.4 / 20
        image.save(images / f"{location['id']}.png", dpi=(dpi, dpi))
    output = root / 'static/qr'
    output.mkdir(parents=True, exist_ok=True)
    env = Environment(loader=FileSystemLoader(root / 'templates'), autoescape=select_autoescape(['html']))
    template = env.get_template('qr_print.html')
    rendered = template.render(locations=[dict(loc, url=mobile_url(loc['id'])) for loc in QR_LOCATIONS],
                               url_for=lambda endpoint, filename: '../' + filename)
    (output / 'print.html').write_text(rendered, encoding='utf-8')
    print('Generated four SVG/PNG QR images and static/qr/print.html.')


if __name__ == '__main__':
    main()
