"""Prepare configured upload bytes for client exports without a second asset request."""
import base64
import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError


def uploaded_logo_export_asset(filename: str, storage_dir: Path, max_bytes: int) -> dict:
    # Match the public logo endpoint's basename resolution. Never return paths.
    path = storage_dir / Path(filename).name
    try:
        with path.open('rb') as stream:
            content = stream.read(max_bytes + 1)
        if len(content) > max_bytes:
            return {'data_url': None, 'error': 'ASSET_TOO_LARGE'}
        with Image.open(io.BytesIO(content)) as image:
            if image.format != 'PNG':
                return {'data_url': None, 'error': 'INVALID_IMAGE'}
            image.verify()
        return {'data_url': 'data:image/png;base64,' + base64.b64encode(content).decode('ascii'), 'error': None}
    except FileNotFoundError:
        return {'data_url': None, 'error': 'ASSET_MISSING'}
    except (UnidentifiedImageError, ValueError, SyntaxError):
        return {'data_url': None, 'error': 'INVALID_IMAGE'}
    except OSError:
        return {'data_url': None, 'error': 'ASSET_UNREADABLE'}
