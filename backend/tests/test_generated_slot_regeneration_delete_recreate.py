import unittest
import uuid
from datetime import date, time

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import FieldInstance, GameSlot, HostLocation, HostingAvailability, Organization, TurfWave
from app.routes.api import _regenerate_generated_slots


class GeneratedSlotRegenerationDeleteRecreateTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine('sqlite+pysqlite:///:memory:', future=True)
        Base.metadata.create_all(engine)
        self.db: Session = sessionmaker(bind=engine)()
        self.org = Organization(id=uuid.uuid4(), name='Turf Org', is_active=True)
        self.host = HostLocation(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            name='Turf Host',
            surface_type='TURF_STADIUM',
            is_active=True,
        )
        self.availability = HostingAvailability(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            host_location_id=self.host.id,
            available_date=date(2026, 9, 12),
            start_time=time(9, 0),
            end_time=time(11, 0),
            is_available=True,
        )
        self.db.add_all([self.org, self.host, self.availability])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _regenerate(self):
        return _regenerate_generated_slots(
            self.db,
            self.availability,
            self.host.id,
            turf_layout_blocks_override=[('TWO_SMALL_ONE_MEDIUM', 1), ('ONE_SMALL_ONE_LARGE', 1)],
        )

    def test_repeated_turf_regeneration_delete_recreates_unique_chronological_artifacts(self):
        first_metrics = self._regenerate()
        self.db.commit()
        first_slot_ids = {slot_id for (slot_id,) in self.db.query(GameSlot.id).all()}
        first_wave_ids = {wave_id for (wave_id,) in self.db.query(TurfWave.id).all()}
        first_field_ids = {field_id for (field_id,) in self.db.query(FieldInstance.id).all()}

        second_metrics = self._regenerate()
        self.db.commit()

        second_slot_ids = {slot_id for (slot_id,) in self.db.query(GameSlot.id).all()}
        second_wave_ids = {wave_id for (wave_id,) in self.db.query(TurfWave.id).all()}
        second_field_ids = {field_id for (field_id,) in self.db.query(FieldInstance.id).all()}
        waves = self.db.query(TurfWave).filter(TurfWave.hosting_availability_id == self.availability.id).order_by(TurfWave.start_time).all()
        field_names = [name for (name,) in self.db.query(FieldInstance.field_name).filter(FieldInstance.hosting_availability_id == self.availability.id).all()]

        self.assertEqual(first_metrics['new_slots_created'], 5)
        self.assertEqual(second_metrics['new_slots_created'], 5)
        self.assertEqual(second_metrics['slots_regenerated'], 5)
        self.assertEqual(second_metrics['diagnostics']['generated_slots_deleted'], 5)
        self.assertEqual(second_metrics['diagnostics']['field_instances_deleted_or_retired'], 5)
        self.assertEqual(second_metrics['diagnostics']['turf_waves_deleted'], 2)
        self.assertEqual(second_metrics['diagnostics']['turf_waves_created'], 2)
        self.assertTrue(second_metrics['diagnostics']['wave_sequence_validation_passed'])
        self.assertTrue(second_metrics['diagnostics']['field_name_uniqueness_validation_passed'])
        self.assertEqual([wave.sequence_number for wave in waves], [1, 2])
        self.assertEqual([wave.start_time for wave in waves], sorted(wave.start_time for wave in waves))
        self.assertEqual(len(field_names), len(set(field_names)))
        self.assertFalse(first_slot_ids & second_slot_ids)
        self.assertFalse(first_wave_ids & second_wave_ids)
        self.assertFalse(first_field_ids & second_field_ids)
        self.assertEqual(self.db.query(GameSlot).join(GameSlot.field_instance).filter(FieldInstance.hosting_availability_id == self.availability.id).count(), 5)
        self.assertEqual(self.db.query(GameSlot).filter(GameSlot.turf_wave_id.isnot(None)).count(), 5)
        duplicate_sequences = self.db.query(TurfWave.sequence_number, func.count(TurfWave.id)).filter(
            TurfWave.hosting_availability_id == self.availability.id,
        ).group_by(TurfWave.sequence_number).having(func.count(TurfWave.id) > 1).all()
        self.assertEqual(duplicate_sequences, [])

    def test_regeneration_preserves_manual_field_instances_and_renames_generated_collision(self):
        manual = FieldInstance(
            id=uuid.uuid4(),
            host_location_id=self.host.id,
            hosting_availability_id=self.availability.id,
            instance_date=self.availability.available_date,
            field_name='Wave 1 TWO_SMALL_ONE_MEDIUM 0900 Small Field 1',
            field_type='SMALL',
            is_active=True,
            is_generated=False,
        )
        self.db.add(manual)
        self.db.commit()

        metrics = self._regenerate()
        self.db.commit()

        self.db.refresh(manual)
        generated_names = [
            name
            for (name,) in self.db.query(FieldInstance.field_name).filter(
                FieldInstance.hosting_availability_id == self.availability.id,
                FieldInstance.is_generated.is_(True),
            ).all()
        ]
        all_names = [name for (name,) in self.db.query(FieldInstance.field_name).filter(FieldInstance.hosting_availability_id == self.availability.id).all()]

        self.assertTrue(manual.is_active)
        self.assertFalse(manual.is_generated)
        self.assertIn('Wave 1 TWO_SMALL_ONE_MEDIUM 0900 Small Field 1 @ 0900', generated_names)
        self.assertEqual(len(all_names), len(set(all_names)))
        self.assertTrue(metrics['diagnostics']['field_name_uniqueness_validation_passed'])


if __name__ == '__main__':
    unittest.main()
