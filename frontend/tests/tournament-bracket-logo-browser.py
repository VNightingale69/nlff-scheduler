"""Browser/PDF regression. Requires Chromium, Playwright, Pillow and PyMuPDF.
Run: python tests/tournament-bracket-logo-browser.py --output /path/to/artifacts
Synthetic logos exercise source handling without requiring production credentials.
"""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile

import fitz
from PIL import Image
from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
out = Path(args.output)
out.mkdir(parents=True, exist_ok=True)
frontend = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as scratch:
    fixture_path = Path(scratch) / 'fixture.json'
    subprocess.run(['node', 'tests/tournament-bracket-export.test.mjs'], cwd=frontend, env={**os.environ, 'BRACKET_FIXTURE_PATH': str(fixture_path)}, check=True)
    fixture = json.loads(fixture_path.read_text())

assets = {}
colors = [(210, 0, 180), (0, 150, 180), (240, 120, 0), (100, 40, 210)]
for name, fmt, dims, color in zip(['westosha.png', 'johnsburg.jpg', 'crystal.gif', 'antioch.webp'], ['PNG', 'JPEG', 'GIF', 'WEBP'], [(100, 50), (50, 100), (90, 60), (60, 90)], colors):
    buf = io.BytesIO()
    Image.new('RGB', dims, color).save(buf, format=fmt)
    assets[name] = (buf.getvalue(), 'image/' + {'JPEG': 'jpeg'}.get(fmt, fmt.lower()))
assets['vector.svg'] = (b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60"><rect width="120" height="60" fill="#d200b4"/></svg>', 'image/svg+xml')
names = ['Westosha Girls 6-8 Maroon', 'Johnsburg Girls 6-8 Gold', 'Johnsburg Girls 6-8 Blue', 'Crystal Lake Girls 6-8', 'Antioch Girls 6-8', 'Prairie Ridge Girls 6-8 White', 'Prairie Ridge Girls 6-8 Maroon', 'Community with unavailable logo']
sources = ['/api/public/organizations/westosha/logo/westosha.png', 'http://logos.test/johnsburg.jpg', 'http://logos.test/johnsburg.jpg', '/assets/crystal.gif', 'assets/antioch.webp', None, None, '/assets/missing.png']
division = fixture['division']
i = 0
for round_ in division['rounds']:
    for game in round_['games']:
        for slot in [1, 2]:
            game[f'team_{slot}_name'] = names[i % 8]
            game[f'team_{slot}_logo_url'] = sources[i % 8]
            i += 1
        game['winner_team_name'] = game['team_1_name']
# Consolation also includes a vector logo to exercise SVG source rasterization.
consolation = {**division['rounds'][-1]['games'][0], 'id': 'consolation', 'round_name': 'Consolation', 'team_1_logo_url': '/assets/vector.svg', 'team_1_source_game_id': None, 'team_2_source_game_id': None}
division['rounds'][-1]['games'].append(consolation)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
    page = browser.new_page()
    requests = {}
    def route(request):
        url = request.request.url
        if url.endswith('/index'):
            request.fulfill(status=200, content_type='text/html', body='<html><body></body></html>')
            return
        key = url.split('/')[-1]
        requests[key] = requests.get(key, 0) + 1
        if key in assets:
            data, mime = assets[key]
            request.fulfill(status=200, content_type=mime, headers={'Access-Control-Allow-Origin': '*'}, body=data)
        else:
            request.fulfill(status=404, body='Unavailable', headers={'Access-Control-Allow-Origin': '*'})
    page.route('http://bracket.test/**', route)
    page.route('http://logos.test/**', route)
    page.goto('http://bracket.test/index')
    page.evaluate('''fixture => {
      const logoExports={};
      new Function('require','exports',fixture.logoCode)(name=>name==='react'?{}:{API_URL:'http://bracket.test/api'},logoExports);
      const exports={};
      new Function('require','exports',fixture.code)(name=>name.includes('CommunityLogo')?logoExports:name.includes('displayFormat')?{formatDisplayDate:v=>v,formatDisplayTime:v=>v}:{publicFieldName:v=>v},exports);
      window.api=exports;
    }''', fixture)
    for iteration in range(3):
        if iteration == 2:
            # Backend-supplied uploads: all original asset requests now fail,
            # yet the same logo pixels must appear via embedded API bytes.
            division['logo_assets'] = {}
            for source in sources:
                if not source or source.endswith('missing.png'):
                    continue
                data, _ = assets[source.split('/')[-1]]
                buffer = io.BytesIO()
                Image.open(io.BytesIO(data)).convert('RGBA').save(buffer, format='PNG')
                division['logo_assets'][source] = {'data_url': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode(), 'error': None, 'community_name': source.split('/')[-1]}
            vector = io.BytesIO()
            Image.new('RGBA', (120, 60), (210, 0, 180, 255)).save(vector, format='PNG')
            division['logo_assets']['/assets/vector.svg'] = {'data_url': 'data:image/png;base64,' + base64.b64encode(vector.getvalue()).decode(), 'error': None, 'community_name': 'Vector'}
            division['logo_assets']['/assets/missing.png'] = {'data_url': None, 'error': 'ASSET_MISSING', 'community_name': 'Unavailable Community'}
            request_count = dict(requests)

        result = page.evaluate('''async division => {
          let warnings;
          const svg=await api.buildExportSvg('2026 Fall Flag Tournament',division,false,value=>{warnings=value});
          document.body.innerHTML=svg;
          const images=[...document.querySelectorAll('image')];
          if(!images.length || images.some(i=>!i.getAttribute('href').startsWith('data:image/png;base64,'))) throw Error('Logo is not embedded');
          const canvas=await api.svgToCanvas(svg);
          const layout=api.buildBracketLayout(division.rounds);
          const pixels=[];
          for(const round of division.rounds) for(const game of round.games) {
            const pos=layout.positions.get(game.id);
            let y=pos.y+58;
            for(const slot of [1,2]) {
              const pixel=[...canvas.getContext('2d').getImageData((pos.x+34)*2,(y+20)*2,1,1).data];
              pixels.push({name:game['team_'+slot+'_name'],source:game['team_'+slot+'_logo_url'],pixel});
              y+=api.teamRowHeight(game,slot)+6;
            }
          }
          const pdf=api.pdfFromJpegDataUrl(canvas.toDataURL('image/jpeg',0.92),canvas.width,canvas.height);
          const data=await new Promise(resolve=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.readAsDataURL(pdf)});
          return {svg,pixels,data,warnings,imageCount:images.length};
        }''', division)
        for entry in result['pixels']:
            r, g, b, a = entry['pixel']
            if entry['source'] and not entry['source'].endswith('missing.png'):
                assert max(r, g, b) - min(r, g, b) > 80, entry
        assert 'Maroon</text>' in result['svg'] and 'White</text>' in result['svg']
        assert 'Gold</text>' in result['svg'] and 'Blue</text>' in result['svg']
        if iteration == 2:
            assert requests == request_count, 'Uploaded logos must not request their original asset URLs'
            assert len(result['warnings']) == 1 and result['warnings'][0]['stage'] == 'storage'
        (out / f'girls-6-8-logos-{iteration + 1}.pdf').write_bytes(base64.b64decode(result['data']))
        (out / 'girls-6-8-logos.svg').write_text(result['svg'])
    assert all(1 <= requests[name] <= 2 for name in assets), requests
    assert requests['missing.png'] == 2, 'Missing sources must be retried on repeated exports'
    browser.close()

# Render the generated PDF, so visual review inspects the actual PDF artifact.
doc = fitz.open(out / 'girls-6-8-logos-3.pdf')
pix = doc[0].get_pixmap(matrix=fitz.Matrix(1, 1))
pix.save(out / 'girls-6-8-logos-pdf.png')
rendered = Image.open(out / 'girls-6-8-logos-pdf.png').convert('RGB')
for color in colors:
    pixels = rendered.tobytes()
    count = sum(all(abs(pixels[index + channel] - color[channel]) < 30 for channel in range(3)) for index in range(0, len(pixels), 3))
    assert count > 30, (color, count)
print('Browser and actual PDF regression passed: immediate/repeated exports, hosted/remote/path assets, PNG/JPEG/GIF/WebP/SVG, multiple rounds/consolation, missing fallback, full names and logo pixels. Backend embedded uploads also passed without any asset requests, with explicit missing-file warnings.')
