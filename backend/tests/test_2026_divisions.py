import unittest
import uuid

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Division, Organization, OrganizationDivisionParticipation, Team
from app.routes.api import ensure_league_defined_divisions


class Fall2026DivisionStructureTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.org = Organization(id=uuid.uuid4(), name='Org', is_active=True)
        self.db.add(self.org)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _add_division(self, group: str, name: str, sort_order: int, team_count: int = 0) -> Division:
        division = Division(
            id=uuid.uuid4(),
            division_group=group,
            name=name,
            sort_order=sort_order,
            required_field_layout_type='THIRTY_YARD_WIDTH',
            is_active=True,
        )
        self.db.add(division)
        self.db.flush()
        if team_count:
            participation = OrganizationDivisionParticipation(
                id=uuid.uuid4(),
                organization_id=self.org.id,
                division_id=division.id,
                is_participating=True,
                team_count=team_count,
                is_active=True,
            )
            teams = [
                Team(
                    id=uuid.uuid4(),
                    organization_id=self.org.id,
                    division_id=division.id,
                    name=f'{group} {name} Team {index}',
                    is_active=True,
                )
                for index in range(team_count)
            ]
            self.db.add_all([participation, *teams])
        self.db.commit()
        return division

    def test_ensure_divisions_renames_coed_and_preserves_references(self):
        old_coed = self._add_division('COED', 'K/1st', 1, team_count=2)
        old_girls_names = ['K/1st', '2nd/3rd', '4th/5th', '6th/7th/8th']
        for index, name in enumerate(old_girls_names, start=1):
            self._add_division('GIRLS', name, index)

        ensure_league_defined_divisions(self.db)

        active = self.db.query(Division).filter(Division.is_active.is_(True)).order_by(Division.sort_order).all()
        self.assertEqual([f'{division.division_group} {division.name}' for division in active], [
            'COED K-1',
            'COED 2-3',
            'COED 4-5',
            'COED 6-7',
            'COED 8',
            'GIRLS K-2',
            'GIRLS 3-5',
            'GIRLS 6-8',
        ])
        self.assertEqual(sum(1 for division in active if division.division_group == 'COED'), 5)
        self.assertEqual(sum(1 for division in active if division.division_group == 'GIRLS'), 3)
        self.assertEqual(self.db.query(Division).filter(Division.is_active.is_(True)).count(), 8)

        renamed_coed = self.db.query(Division).filter(Division.division_group == 'COED', Division.name == 'K-1').one()
        self.assertEqual(renamed_coed.id, old_coed.id)
        self.assertEqual(self.db.query(OrganizationDivisionParticipation).filter(OrganizationDivisionParticipation.division_id == old_coed.id).count(), 1)
        self.assertEqual(self.db.query(Team).filter(Team.division_id == old_coed.id).count(), 2)

        inactive_old_girls = self.db.query(Division).filter(Division.division_group == 'GIRLS', Division.name.in_(old_girls_names)).all()
        self.assertEqual(len(inactive_old_girls), 4)
        self.assertTrue(all(not division.is_active for division in inactive_old_girls))

        duplicate_active_count = self.db.query(
            Division.division_group,
            Division.name,
            func.count(Division.id),
        ).filter(Division.is_active.is_(True)).group_by(Division.division_group, Division.name).having(func.count(Division.id) > 1).count()
        self.assertEqual(duplicate_active_count, 0)
