"""Prepare display-only check crops from the exact screenshot and recorded coordinates."""
import hashlib
import json
import math
from pathlib import Path


def valid_box(box, size):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    if not all(isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n) for n in box):
        return False
    left, top, right, bottom = box
    return 0 <= left < right <= size[0] and 0 <= top < bottom <= size[1]


def context_crop(boxes, size, padding=24):
    """Keep exact mark coordinates; only the surrounding view is expanded/clipped."""
    if not boxes:
        return [0, 0, *size]
    if not all(valid_box(box, size) for box in boxes):
        raise ValueError('Invalid evidence box')
    left = min(box[0] for box in boxes)
    top = min(box[1] for box in boxes)
    right = max(box[2] for box in boxes)
    bottom = max(box[3] for box in boxes)
    width = min(size[0], max(180, right - left + padding * 2))
    height = min(size[1], max(110, bottom - top + padding * 2))
    x = max(0, min((left + right - width) / 2, size[0] - width))
    y = max(0, min((top + bottom - height) / 2, size[1] - height))
    return [x, y, x + width, y + height]


class CheckEvidenceBuilder:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.images = {}
        self.documents = {}

    def path(self, name):
        path = (self.root / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(self.root):
            raise ValueError('Evidence file must be inside the report')
        return path

    def image(self, name, expected_hash, expected_size=None):
        if name not in self.images:
            payload = self.path(name).read_bytes()
            if payload[:8] != b'\x89PNG\r\n\x1a\n':
                raise ValueError('Expected PNG screenshot')
            size = [int.from_bytes(payload[16:20], 'big'), int.from_bytes(payload[20:24], 'big')]
            self.images[name] = (hashlib.sha256(payload).hexdigest(), size)
        digest, size = self.images[name]
        if not expected_hash or digest != expected_hash or (expected_size and size != list(expected_size)):
            raise ValueError('Screenshot identity or dimensions changed')
        return {'file': name, 'sha256': digest, 'image_size': size}

    def document(self, name, expected_hash):
        if name not in self.documents:
            payload = self.path(name).read_bytes()
            self.documents[name] = (hashlib.sha256(payload).hexdigest(), json.loads(payload))
        digest, document = self.documents[name]
        if not expected_hash or digest != expected_hash:
            raise ValueError('DOM evidence changed')
        return document

    @staticmethod
    def finish(image, marks, label, source, status, focus=None):
        size = image['image_size']
        boxes = [mark['bbox_px'] for mark in marks if mark['kind'] == 'rect']
        crop = context_crop(focus if focus is not None else boxes, size)
        return {**image, 'crop_px': crop, 'marks': marks, 'label': label, 'source': source, 'status': status}

    def spacing(self, check, venue):
        facts = check.get('facts', {})
        if not facts.get('screenshot_file'):
            return None
        image = self.image(facts['screenshot_file'], facts['screenshot_sha256'], [390, 844])
        measured = facts.get('measurement_status') == 'measured'
        verified = facts.get('semantic_boundary_verified') is True
        if measured:
            dom = self.document(facts['dom_file'], facts['dom_sha256'])
            if dom['venue'] != venue:
                raise ValueError('DOM evidence belongs to another venue')
            measurement = dom['measurement']
            source = measurement['source']
            if source['viewport_css_px'] != {'width': 390, 'height': 844} or source['visual_viewport']['scale'] != 1:
                raise ValueError('Unsupported screenshot coordinate scale')
            targets = {element['id']: element for element in measurement['elements']}
            upper, tab = targets['upper-module'], targets['category-tabs']
            if upper['status'] != 'measured' or tab['status'] != 'measured':
                raise ValueError('Missing DOM boundary')
            upper, tab = upper['rect_css_px'], tab['rect_css_px']
            y1, y2 = upper['bottom'], tab['top']
            if not math.isclose(y2 - y1, facts['distance_css_px']):
                raise ValueError('DOM gap does not match check')
            for rect in (upper, tab):
                if not all(math.isfinite(rect[key]) for key in ('left', 'right', 'top', 'bottom')):
                    raise ValueError('Invalid DOM coordinates')
            # Off-screen boundaries cannot be pointed out on this capture.
            if not all(0 <= y <= 844 for y in (y1, y2)):
                return self.finish(image, [], '边界未同时出现在截图中，无法精确框选。', 'live_h5_dom', 'context')
            left = max(0, min(upper['left'], tab['left']))
            right = min(390, max(upper['right'], tab['right']))
            if left >= right:
                raise ValueError('DOM boundaries outside screenshot')
            marks = [
                {'kind': 'line', 'start_px': [left, y1], 'end_px': [right, y1], 'label': '上方模块底部', 'color': '#2563eb'},
                {'kind': 'line', 'start_px': [left, y2], 'end_px': [right, y2], 'label': '分类Tab顶部', 'color': '#059669', 'dashed': True},
            ]
            if y1 != y2:
                marks.insert(0, {'kind': 'rect', 'bbox_px': [left, min(y1, y2), right, max(y1, y2)], 'label': '实测间距', 'filled': True})
            focus = [[left, max(0, min(y1, y2) - 35), right, min(844, max(y1, y2) + 45)]]
            label = f"{facts['upper_module']} → 分类Tab：{facts['distance_css_px']:g}px"
            label += '；蓝线为模块底部，绿虚线为Tab顶部。' if verified else '；仅标出候选DOM边界，业务模块身份仍待确认。'
            return self.finish(image, marks, label, 'live_h5_dom', 'localized' if verified else 'candidate', focus)
        bbox = facts.get('evidence_bbox_px')
        if valid_box(bbox, image['image_size']) and bbox != [0, 0, *image['image_size']]:
            return self.finish(image, [{'kind': 'rect', 'bbox_px': bbox, 'label': '待确认候选区域'}],
                               '本轮间距截图中的候选区域，尚无可判定的间距。', 'live_h5_capture', 'candidate')
        return self.finish(image, [], '本轮间距截图仅作参考，未定位可判定的模块交界。', 'live_h5_capture', 'context')

    def prepare(self, check, capture, venue):
        if check.get('enabled') is False or check['status'] == 'disabled':
            return {'state': 'disabled', 'items': [], 'note': ''}
        if check['rule_id'] == 'OV-009':
            live = self.spacing(check, venue)
            if live:
                return {'state': live['status'], 'items': [live], 'note': ''}
        screens = {screen['number']: screen for screen in capture['screens']}
        groups = {}
        for evidence in check.get('evidence', []):
            screen = screens[evidence['screen']]
            if evidence['file'] != screen['file'] or evidence['sha256'] != screen['sha256']:
                raise ValueError('Check evidence belongs to another screenshot')
            size = [screen['width'], screen['height']]
            image = self.image(screen['file'], screen['sha256'], size)
            bbox = evidence['bbox_px']
            if not valid_box(bbox, size):
                raise ValueError('Invalid check evidence coordinates')
            group = groups.setdefault(screen['number'], {**image, 'marks': []})
            if bbox != [0, 0, *size] and not any(m['bbox_px'] == bbox for m in group['marks']):
                label = '像素取样点' if check['rule_id'] == 'OV-010' else '审核记录中的检查区域'
                group['marks'].append({'kind': 'rect', 'bbox_px': bbox, 'label': label})
        items = []
        for number, group in groups.items():
            marks = group.pop('marks')
            label = f'原截图 {number} · ' + ('框线对应审核记录坐标' if marks else '整屏参考，尚无局部定位')
            items.append(self.finish(group, marks, label, 'original_capture', 'localized' if marks else 'context'))
        if not items:
            # Missing evidence is shown as context, never invented as an issue box.
            for screen in capture['screens']:
                image = self.image(screen['file'], screen['sha256'], [screen['width'], screen['height']])
                items.append(self.finish(image, [], f"原截图 {screen['number']} · 未定位", 'original_capture', 'missing'))
            return {'state': 'missing', 'items': items, 'note': '该项没有局部定位证据；以下为会场参考截图，可补充人工框选。'}
        state = 'localized' if any(item['marks'] for item in items) else 'context'
        return {'state': state, 'items': items, 'note': '' if state == 'localized' else '现有证据覆盖整屏，不能标出具体问题对象；可补充人工框选。'}
