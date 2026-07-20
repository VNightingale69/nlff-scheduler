import argparse, json
from app.database import SessionLocal
from app.services.orphaned_teams_cleanup import cleanup_orphaned_teams

def main():
    parser = argparse.ArgumentParser(description='Report or clean teams whose organization_id has no matching organization.')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--dry-run', action='store_true', default=True)
    group.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    db = SessionLocal()
    try:
        result = cleanup_orphaned_teams(db, apply=args.apply)
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        db.close()

if __name__ == '__main__':
    main()
