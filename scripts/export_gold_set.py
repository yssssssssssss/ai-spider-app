"""Export frozen evidence and latest human labels; never alter audit data."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def gold_label(review):
    if review['verdict'] == 'recapture':
        return None
    if review['verdict'] == 'false_positive':
        return review.get('corrected_status') or 'pass'
    return 'fail'


def export_run(db, run, output):
    from app import models
    from app.config import settings
    from app.services.audit_analytics import latest_reviews
    from app.services.audit_evidence import asset_path

    if output.exists() and any(output.iterdir()):
        raise ValueError('Output directory must be empty; frozen gold sets are not overwritten')
    output.mkdir(parents=True, exist_ok=True)
    selected = [(t, latest_reviews(t)) for t in run.targets]
    selected = [(t, reviews) for t, reviews in selected if any(gold_label(r) for r in reviews.values())]
    if not selected:
        raise ValueError('No reviewed targets without recapture')
    assets = {a.sha256: a for a in db.query(models.AuditEvidenceAsset).filter(models.AuditEvidenceAsset.sha256.in_(
        {i['asset'] for t, _ in selected for f in t.findings_json for i in (f.get('evidence') or {}).get('items', []) if i.get('asset')})).all()}
    image_ids = {i['image_id'] for t, _ in selected for f in t.findings_json for i in (f.get('evidence') or {}).get('items', []) if i.get('image_id')}
    images = {str(i.id): i for i in db.query(models.Image).filter(models.Image.id.in_(image_ids)).all()} if image_ids else {}
    roots = []
    for job in db.query(models.AuditJob).filter_by(audit_run_id=run.id).all():
        work = job.executor_ref_json.get('work_dir')
        if work:
            roots.extend([Path(work) / 'audit', Path(work) / 'capture'])
    for key in ('source_dir', 'source_path'):
        if run.source_ref_json.get(key):
            roots.append(Path(run.source_ref_json[key]))
    manifest = {'schema_version': 1, 'run_id': str(run.id), 'spec_version_id': str(run.spec_version_id), 'targets': []}
    venues = []
    for target, reviews in selected:
        record = str(target.id)
        folder = output / 'venues' / record
        folder.mkdir(parents=True)
        items = [i for f in target.findings_json for i in (f.get('evidence') or {}).get('items', [])]
        original_capture, source_folder = None, None
        for item in items:
            relative = Path(item.get('file') or '')
            if not item.get('file') or relative.is_absolute() or '..' in relative.parts:
                continue
            for root in roots:
                candidate = (root / relative.parent / 'capture.json').resolve()
                if candidate.is_relative_to(root.resolve()) and candidate.is_file():
                    original_capture = json.loads(candidate.read_text())
                    source_folder = candidate.parent
                    break
            if original_capture:
                break
        venue = deepcopy(original_capture['venue']) if original_capture else {
            'venue_id': target.business_key or record, 'venue_name': target.name, 'project_id': '',
        }
        venue['record_id'] = record
        # QR identity checks belong to live capture. Gold replays use frozen image hashes.
        venue.pop('qr_file', None)
        capture = deepcopy(original_capture) if original_capture else {}
        capture.update(venue=venue, screens=[])
        seen = set()
        for item in items:
            key = item.get('asset') or item.get('image_id')
            if not key or key in seen:
                continue
            seen.add(key)
            if item.get('asset'):
                asset = assets.get(key)
                if asset is None:
                    raise ValueError(f'Missing registered evidence asset: {key}')
                source = asset_path(asset)
                width, height = asset.width, asset.height
                digest = key
            else:
                image = images[key]
                source = Path(image.file_path)
                if not source.is_absolute():
                    source = Path(settings.PROJECT_ROOT) / source
                from PIL import Image
                with Image.open(source) as picture:
                    width, height = picture.size
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise ValueError(f'Evidence hash mismatch: {key}')
            number = item.get('screen') or len(capture['screens']) + 1
            relative = f'venues/{record}/screen-{len(capture["screens"]) + 1}{source.suffix}'
            shutil.copyfile(source, output / relative)
            original_screen = next((s for s in (original_capture or {}).get('screens', []) if s['sha256'] == digest), {})
            capture['screens'].append({**original_screen, 'number': number, 'file': relative, 'sha256': digest,
                                       'width': width, 'height': height, 'scroll_y': original_screen.get('scroll_y', 0)})
        if not capture['screens']:
            raise ValueError(f'Reviewed target has no stored screenshots: {target.id}')
        entry = {'target_id': record, 'record_id': record, 'name': target.name, 'business_key': target.business_key,
                 'findings': target.findings_json, 'latest_reviews': list(reviews.values()),
                 'gold_labels': {rid: label for rid, review in reviews.items() if (label := gold_label(review)) is not None},
                 'capture_file': f'venues/{record}/capture.json', 'screenshots': capture['screens']}
        if source_folder and (source_folder / 'dom-snapshot.json').is_file():
            shutil.copyfile(source_folder / 'dom-snapshot.json', folder / 'dom-snapshot.json')
            entry['dom_snapshot'] = f'venues/{record}/dom-snapshot.json'
        write_json(folder / 'capture.json', capture)
        write_json(folder / 'findings.json', target.findings_json)
        write_json(folder / 'reviews.json', entry['latest_reviews'])
        manifest['targets'].append(entry)
        venues.append(venue)
    write_json(output / 'catalog.json', {'venues': venues, 'selected_venue_count': len(venues)})
    write_json(output / 'spec-version.json', {'rules_json': run.spec_version.rules_json, 'source_json': run.spec_version.source_json})
    write_json(output / 'manifest.json', manifest)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=UUID)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    from app.database import SessionLocal
    from app.services.audit_workspace import load_run
    try:
        with SessionLocal() as db:
            run = load_run(db, args.run)
            if run is None:
                raise ValueError('Audit run not found')
            manifest = export_run(db, run, args.out.resolve())
            print(f'Exported {len(manifest["targets"])} targets to {args.out / "manifest.json"}')
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
