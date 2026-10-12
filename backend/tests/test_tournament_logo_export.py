import base64
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from PIL import Image

from app.routes import api
from app.services.community_logo_export import uploaded_logo_export_asset


def png():
    stream = io.BytesIO()
    Image.new('RGBA', (100, 50), (210, 0, 180, 128)).save(stream, format='PNG')
    return stream.getvalue()


def test_uploaded_bytes_match_the_public_asset_and_no_private_path_is_exposed(tmp_path):
    content = png()
    (tmp_path / 'logo.png').write_bytes(content)
    result = uploaded_logo_export_asset('logo.png', tmp_path, 2 * 1024 * 1024)
    assert base64.b64decode(result['data_url'].split(',')[1]) == content
    assert result['error'] is None
    assert str(tmp_path) not in str(result)
    with Image.open(io.BytesIO(content)) as image:
        assert image.size == (100, 50)


def test_missing_invalid_oversized_and_unreadable_assets_have_explicit_diagnostics(tmp_path):
    assert uploaded_logo_export_asset('missing.png', tmp_path, 1024)['error'] == 'ASSET_MISSING'
    (tmp_path / 'invalid.png').write_text('not an image')
    assert uploaded_logo_export_asset('invalid.png', tmp_path, 1024)['error'] == 'INVALID_IMAGE'
    (tmp_path / 'big.png').write_bytes(png())
    assert uploaded_logo_export_asset('big.png', tmp_path, 1)['error'] == 'ASSET_TOO_LARGE'
    with patch.object(Path, 'open', side_effect=PermissionError):
        assert uploaded_logo_export_asset('big.png', tmp_path, 1024)['error'] == 'ASSET_UNREADABLE'


def test_all_divisions_share_canonical_sources_and_deduplicate_uploads_across_rounds(tmp_path):
    (tmp_path / 'logo.png').write_bytes(png())
    org = SimpleNamespace(id=uuid.uuid4(), name='Westosha', logo_filename='logo.png')
    absent = SimpleNamespace(id=uuid.uuid4(), name='Prairie Ridge', logo_filename=None, logo_url=None)
    divisions = []
    serialized = []
    for group in ['GIRLS', 'COED']:
        division_id, roster_id = uuid.uuid4(), uuid.uuid4()
        games = [SimpleNamespace(team_1=SimpleNamespace(organization=org), team_2=SimpleNamespace(organization=absent)) for _ in range(3)]
        divisions.append(SimpleNamespace(id=division_id, games=games))
        serialized.append({'id': str(division_id), 'division_id': str(roster_id), 'division_group': group,
                           'games': [{'round_number': i, 'round_name': name, 'game_number': i} for i, name in enumerate(['Play-in', 'Semifinal', 'Championship'], 1)]})
    tournament = SimpleNamespace(divisions=divisions)
    source = api._community_logo_browser_url(org)
    with patch.object(api, '_tournament_dict', return_value={'divisions': serialized}), patch.object(api, '_resolved_community_logo_storage_dir', return_value=tmp_path), patch.object(api, 'uploaded_logo_export_asset', wraps=uploaded_logo_export_asset) as read:
        payload = api._tournament_bracket_dict(tournament)
    assert read.call_count == 1
    for division in payload['divisions']:
        assert list(division['logo_assets']) == [source]
        assert division['logo_assets'][source]['community_name'] == 'Westosha'
        assert division['logo_assets'][source]['data_url'].startswith('data:image/png;base64,')
        assert len(division['rounds']) == 3
        assert len(division['games']) == 3
