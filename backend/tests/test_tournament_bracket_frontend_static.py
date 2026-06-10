from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BRACKET_COMPONENT = ROOT / 'frontend' / 'src' / 'components' / 'TournamentBracket.tsx'
ADMIN_TOURNAMENT_PAGE = ROOT / 'frontend' / 'src' / 'app' / '(dashboard)' / 'admin' / 'tournaments' / 'page.tsx'
PUBLIC_TOURNAMENT_PAGE = ROOT / 'frontend' / 'src' / 'app' / 'tournaments' / 'page.tsx'


def test_visual_bracket_component_renders_rounds_left_to_right_with_game_boxes():
    source = BRACKET_COMPONENT.read_text()
    assert "grid-flow-col" in source
    assert "auto-cols-[19rem]" in source
    assert "rounds.map" in source
    assert "Game {game.game_number}" in source
    assert "TeamRow game={game} slot={1}" in source
    assert "TeamRow game={game} slot={2}" in source
    assert "Winner" in source
    assert "BYE · Auto-Advance" in source


def test_bracket_exports_use_visual_svg_layout_for_pdf_png_and_svg():
    source = BRACKET_COMPONENT.read_text()
    assert "Download PDF" in source
    assert "Download PNG" in source
    assert "Download SVG" in source
    assert "buildBracketSvg" in source
    assert "svgToCanvas" in source
    assert "pdfFromJpegDataUrl" in source
    assert "image/png" in source
    assert "application/pdf" in source
    assert "image/svg+xml" in source
    assert "Round" not in source.split("function buildBracketSvg", 1)[0] or "round.round_name" in source


def test_admin_tournament_page_keeps_schedule_view_and_adds_bracket_view_with_downloads():
    source = ADMIN_TOURNAMENT_PAGE.read_text()
    assert "Schedule View" in source
    assert "Bracket View" in source
    assert "<table" in source
    assert "<TournamentBracket divisions={tournament.divisions} tournamentTitle={tournament.name} />" in source
    assert "Publish Tournament" in source
    assert "Unpublish" in source


def test_public_tournament_page_uses_read_only_published_bracket_with_downloads():
    source = PUBLIC_TOURNAMENT_PAGE.read_text()
    assert "/public/tournaments/${id}/bracket" in source
    assert "Published Tournament Bracket" in source
    assert "publicView tournamentTitle={bracket.name}" in source
    assert "unpublished score workflow details are hidden" in source
