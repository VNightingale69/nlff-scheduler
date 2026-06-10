from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRACKET_COMPONENT = ROOT / 'frontend' / 'src' / 'components' / 'TournamentBracket.tsx'
ADMIN_TOURNAMENT_PAGE = ROOT / 'frontend' / 'src' / 'app' / '(dashboard)' / 'admin' / 'tournaments' / 'page.tsx'
PUBLIC_TOURNAMENT_PAGE = ROOT / 'frontend' / 'src' / 'app' / 'tournaments' / 'page.tsx'


def test_live_and_export_share_bracket_renderer_layout_source():
    source = BRACKET_COMPONENT.read_text()
    assert 'function SharedBracketRenderer' in source
    assert 'function buildBracketSvg' in source
    assert 'buildBracketLayout(rounds)' in source
    assert source.count('buildBracketLayout(rounds)') >= 2
    assert 'bracketConnectors(rounds, layout)' in source
    assert 'data-shared-bracket-renderer' in source


def test_visual_bracket_keeps_export_proportions_on_screen():
    source = BRACKET_COMPONENT.read_text()
    assert 'roundWidth: 300' in source
    assert 'roundGap: 64' in source
    assert 'gameHeight: 220' in source
    assert 'minHeight: layout.gameHeight' in source
    assert 'gameGap: 34' in source
    assert 'style={{ width: layout.width, height: layout.height, minWidth: layout.width }}' in source
    assert 'overflow-x-auto overflow-y-auto' in source
    assert 'data-testid=\'bracket-horizontal-scroll\'' in source


def test_round_headers_cards_connectors_and_metadata_use_shared_design():
    source = BRACKET_COMPONENT.read_text()
    assert 'round.round_name' in source
    assert 'Game {game.game_number}' in source
    assert 'TeamRow game={game} slot={1}' in source
    assert 'TeamRow game={game} slot={2}' in source
    assert 'Winner' in source
    assert 'BYE · Auto-Advance' in source
    assert 'connectorPath(start, end, layout)' in source
    assert 'Date:' in source
    assert 'Host:' in source
    assert 'Field:' in source


def test_download_exports_use_same_state_and_keep_pdf_png_svg_actions():
    source = BRACKET_COMPONENT.read_text()
    assert 'Download PDF' in source
    assert 'Download PNG' in source
    assert 'Download SVG' in source
    assert 'const svg = () => buildBracketSvg(title, division, publicView)' in source
    assert 'svgToCanvas(svg())' in source
    assert 'pdfFromJpegDataUrl' in source
    assert 'image/png' in source
    assert 'application/pdf' in source
    assert 'image/svg+xml' in source
    assert 'winner_team_name' in source
    assert 'winner_team_id' in source


def test_admin_tournament_page_keeps_schedule_view_and_adds_bracket_view_with_downloads():
    source = ADMIN_TOURNAMENT_PAGE.read_text()
    assert 'Schedule View' in source
    assert 'Bracket View' in source
    assert '<table' in source
    assert '<TournamentBracket divisions={tournament.divisions} tournamentTitle={tournament.name} />' in source
    assert 'Publish Tournament' in source
    assert 'Unpublish' in source


def test_public_tournament_page_uses_read_only_published_bracket_with_downloads():
    source = PUBLIC_TOURNAMENT_PAGE.read_text()
    assert '/public/tournaments/${id}/bracket' in source
    assert 'Published Tournament Bracket' in source
    assert 'publicView tournamentTitle={bracket.name}' in source
    assert 'unpublished score workflow details are hidden' in source
