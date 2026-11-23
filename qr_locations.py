"""Fixed demonstration placards: scanning identifies a location, not GPS."""
PUBLIC_ORIGIN = 'https://fire-guard-seven.vercel.app'
QR_LOCATIONS = (
    {'id': 'N40', 'label': '매표소', 'placement': '매표소 내부 벽'},
    {'id': 'N19', 'label': '팝콘 매점', 'placement': '팝콘 매점 내부 벽'},
    {'id': 'N37', 'label': '5관', 'placement': '5관 내부 출입구 쪽 벽'},
    {'id': 'N33', 'label': '동측 분기점', 'placement': '동측 복도 분기점 벽'},
)


def mobile_url(node_id):
    if node_id not in {location['id'] for location in QR_LOCATIONS}:
        raise ValueError('등록되지 않은 QR 위치입니다.')
    return f'{PUBLIC_ORIGIN}/mobile/{node_id}'
