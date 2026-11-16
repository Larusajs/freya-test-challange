import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timedelta, timezone
from app import store
from app.config import settings


class DeliveryRulesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original = settings.database_path
        settings.database_path = str(Path(self.directory.name) / 'test.sqlite3')
        store.initialize()

    def tearDown(self):
        settings.database_path = self.original
        self.directory.cleanup()

    def new_call(self, customer_id):
        call = store.create_call(customer_id)
        store.confirm_recipient(call, 'self')
        return call

    def verified_call(self, customer_id):
        call = self.new_call(customer_id)
        dob = next(c[3] for c in store.CUSTOMERS if c[0] == customer_id)
        self.assertTrue(store.verify(call, dob)['verified'])
        return call

    def test_seed_is_idempotent_and_has_seven_places(self):
        store.initialize()
        data = store.dashboard()
        self.assertEqual(len(data['customers']), 8)
        self.assertEqual(sum(s['remaining'] for s in data['slots']), 7)
        self.assertNotIn('birth_date', data['customers'][0])

    def test_identity_required_before_read_and_write(self):
        call = self.new_call('c1')
        with self.assertRaises(store.RuleError):
            store.available_slots(call)
        with self.assertRaises(store.RuleError):
            store.book(call, 's1', True)

    def test_three_failed_attempts_are_persistent(self):
        call = self.new_call('c1')
        for _ in range(3):
            self.assertFalse(store.verify(call, '2000-01-01')['verified'])
        with self.assertRaises(store.RuleError):
            store.verify(call, '1988-03-14')
        self.assertEqual(store.dashboard()['calls'][0]['status'], 'verification_failed')

    def test_district_and_consent_are_enforced(self):
        call = self.verified_call('c1')
        self.assertEqual([s['id'] for s in store.available_slots(call)], ['s1', 's2'])
        with self.assertRaises(store.RuleError):
            store.book(call, 's3', True)
        with self.assertRaises(store.RuleError):
            store.book(call, 's1', False)

    def test_booking_is_idempotent_and_persists(self):
        call = self.verified_call('c1')
        first = store.book(call, 's1', True)
        again = store.book(call, 's1', True)
        self.assertEqual(first['booking_id'], again['booking_id'])
        store.initialize()
        self.assertEqual(store.dashboard()['slots'][0]['remaining'], 0)
        with self.assertRaises(store.RuleError):
            store.book(call, 's2', True)

    def test_concurrent_last_place_has_exactly_one_winner(self):
        calls = [self.verified_call('c1'), self.verified_call('c2')]
        def attempt(call):
            try:
                return store.book(call, 's1', True)
            except store.RuleError:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, calls))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(store.dashboard()['slots'][0]['remaining'], 0)

    def test_kadikoy_third_customer_has_no_capacity(self):
        store.book(self.verified_call('c1'), 's1', True)
        store.book(self.verified_call('c2'), 's2', True)
        call = self.verified_call('c3')
        self.assertEqual(store.available_slots(call), [])
        self.assertEqual(store.close_call(call, 'no_availability')['status'], 'no_availability')

    def test_closed_call_cannot_book(self):
        call = self.verified_call('c4')
        store.close_call(call, 'declined')
        with self.assertRaises(store.RuleError):
            store.book(call, 's3', True)

    def test_invalid_customer_and_date(self):
        with self.assertRaises(store.RuleError):
            self.new_call('missing')
        call = self.new_call('c1')
        with self.assertRaises(store.RuleError):
            store.verify(call, '1988-02-31')

    def callback_time(self):
        return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    def test_recipient_confirmation_required_for_verification_and_callback(self):
        call = store.create_call('c1')
        with self.assertRaises(store.RuleError):
            store.verify(call, '1988-03-14')
        with self.assertRaises(store.RuleError):
            store.request_callback(call, self.callback_time(), True)
        store.confirm_recipient(call, 'self')
        self.assertTrue(store.verify(call, '1988-03-14')['verified'])

    def test_wrong_recipient_or_details_cannot_access_booking_or_continue(self):
        store.book(self.verified_call('c1'), 's1', True)
        for outcome in ('other_person', 'incorrect_details'):
            call = store.create_call('c1')
            store.confirm_recipient(call, outcome)
            for operation in (
                lambda: store.verify(call, '1988-03-14'),
                lambda: store.existing_booking(call),
                lambda: store.book(call, 's1', True),
                lambda: store.request_callback(call, self.callback_time(), True),
                lambda: store.confirm_recipient(call, 'self'),
            ):
                with self.assertRaises(store.RuleError):
                    operation()
        self.assertEqual(store.dashboard()['customers'][0]['slot_id'], 's1')

    def test_existing_booking_is_returned_only_after_verification(self):
        original = store.book(self.verified_call('c1'), 's1', True)
        call = self.new_call('c1')
        with self.assertRaises(store.RuleError):
            store.existing_booking(call)
        failed = store.verify(call, '2000-01-01')
        self.assertNotIn('booking', failed)
        result = store.verify(call, '1988-03-14')
        self.assertEqual(result['booking']['booking_id'], original['booking_id'])
        self.assertEqual(result['booking']['start'], '09:00')
        self.assertEqual(result['booking']['district'], 'Kadıköy')
        self.assertEqual(store.existing_booking(call)['booking'], result['booking'])
        store.close_call(call, 'existing_booking_confirmed')
        self.assertEqual(store.dashboard()['calls'][0]['status'], 'existing_booking_confirmed')
        self.assertEqual(store.dashboard()['slots'][0]['remaining'], 0)

    def test_no_booking_and_unverified_completion(self):
        call = self.new_call('c1')
        with self.assertRaises(store.RuleError):
            store.close_call(call, 'existing_booking_confirmed')
        self.assertIsNone(store.verify(call, '1988-03-14')['booking'])
        with self.assertRaises(store.RuleError):
            store.close_call(call, 'existing_booking_confirmed')

    def test_recipient_migration_preserves_existing_booking(self):
        store.book(self.verified_call('c1'), 's1', True)
        with store.connection() as db:
            db.execute('ALTER TABLE calls DROP COLUMN recipient_status')
        store.initialize()
        with store.connection() as db:
            row = db.execute('SELECT recipient_status FROM calls').fetchone()
        self.assertEqual(row['recipient_status'], 'unknown')
        self.assertEqual(store.dashboard()['customers'][0]['slot_id'], 's1')

    def test_concurrent_migration_then_verification_on_legacy_call(self):
        call = store.create_call('c1')
        with store.connection() as db:
            db.execute('ALTER TABLE calls DROP COLUMN recipient_status')
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda _: store.initialize(), range(2)))
        # Migration never assumes an unverified caller is the cardholder.
        with self.assertRaises(store.RuleError):
            store.verify(call, '1988-03-14')
        store.confirm_recipient(call, 'self')
        self.assertTrue(store.verify(call, '1988-03-14')['verified'])

    def test_callback_without_identity_is_persistent_and_does_not_book(self):
        call = self.new_call('c1')
        when = self.callback_time()
        first = store.request_callback(call, when, True)
        self.assertEqual(store.request_callback(call, when, True)['callback_id'], first['callback_id'])
        store.initialize()
        data = store.dashboard()
        self.assertEqual(data['callbacks'][0]['phone'], '0532 000 00 01')
        self.assertEqual(data['calls'][0]['status'], 'callback_requested')
        self.assertEqual(sum(s['remaining'] for s in data['slots']), 7)
        with self.assertRaises(store.RuleError):
            store.verify(call, '1988-03-14')
        with self.assertRaises(store.RuleError):
            store.book(call, 's1', True)

    def test_callback_rejects_invalid_time_and_missing_consent(self):
        call = self.new_call('c1')
        for when in ('later', '2099-01-01T12:00:00', '2000-01-01T12:00:00+03:00'):
            with self.assertRaises(store.RuleError):
                store.request_callback(call, when, True)
        with self.assertRaises(store.RuleError):
            store.request_callback(call, self.callback_time(), False)
        self.assertEqual(store.dashboard()['callbacks'], [])
        self.assertEqual(store.dashboard()['calls'][0]['status'], 'started')

    def test_callback_only_one_pending_per_customer_and_resolution(self):
        first, second = self.new_call('c1'), self.new_call('c1')
        request = store.request_callback(first, self.callback_time(), True)
        with self.assertRaises(store.RuleError):
            store.request_callback(second, self.callback_time(), True)
        store.resolve_callback(request['callback_id'], 'completed')
        store.resolve_callback(request['callback_id'], 'completed')
        with self.assertRaises(store.RuleError):
            store.resolve_callback(request['callback_id'], 'cancelled')
        store.request_callback(second, self.callback_time(), True)
        self.assertEqual(len(store.dashboard()['callbacks']), 2)

    def test_closed_call_cannot_request_callback(self):
        call = self.new_call('c1')
        store.close_call(call, 'declined')
        with self.assertRaises(store.RuleError):
            store.request_callback(call, self.callback_time(), True)

    def test_concurrent_callback_requests_have_one_winner(self):
        calls = [self.new_call('c1'), self.new_call('c1')]
        when = self.callback_time()
        def attempt(call):
            try:
                return store.request_callback(call, when, True)
            except store.RuleError:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sum(r is not None for r in executor.map(attempt, calls)), 1)

if __name__ == '__main__':
    unittest.main()
