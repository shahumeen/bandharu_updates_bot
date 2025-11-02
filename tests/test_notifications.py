import unittest

from models import (
    db,
    User,
    Port,
    Vessel,
    PortSubscription,
    VesselSubscription,
    PortLog,
    PortLogNotification,
)
from model_helpers import (
    initialize_db,
    get_users_to_notify_for_log,
)


class GetUsersToNotifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Ensure a clean slate for the database
        db.connect(reuse_if_open=True)
        try:
            db.drop_tables(
                [
                    PortLogNotification,
                    PortLog,
                    VesselSubscription,
                    PortSubscription,
                    Vessel,
                    User,
                    Port,
                ],
                safe=True,
            )
        except Exception:
            pass
        initialize_db(create_tables=True)

    @classmethod
    def tearDownClass(cls):
        db.close()

    def setUp(self):
        # Clean data between tests
        for model in [
            PortLogNotification,
            PortLog,
            VesselSubscription,
            PortSubscription,
            Vessel,
            User,
            Port,
        ]:
            model.delete().execute()

        # Common fixtures
        self.port_a = Port.create(name="Port A")
        self.port_b = Port.create(name="Port B")
        self.v1 = Vessel.create(id=101, name="V1")
        self.v2 = Vessel.create(id=202, name="V2")

        # Users
        # u1: vessel V1 + port A -> notify for A, not for B
        self.u1 = User.create(
            chat_id=1, chat_type="private", username=None, first_name="u1", last_name=None
        )
        VesselSubscription.create(user=self.u1, vessel=self.v1)
        PortSubscription.create(user=self.u1, port=self.port_a)

        # u2: vessel V1 + no ports -> notify for all ports
        self.u2 = User.create(
            chat_id=2, chat_type="private", username=None, first_name="u2", last_name=None
        )
        VesselSubscription.create(user=self.u2, vessel=self.v1)

        # u3: vessel V1 + port B -> notify for B, not A
        self.u3 = User.create(
            chat_id=3, chat_type="private", username=None, first_name="u3", last_name=None
        )
        VesselSubscription.create(user=self.u3, vessel=self.v1)
        PortSubscription.create(user=self.u3, port=self.port_b)

        # u4: group with main_port A, no vessel subs -> always notify for events at A
        self.u4 = User.create(
            chat_id=4, chat_type="group", username=None, first_name="group4", last_name=None, main_port=self.port_a
        )

        # u5: group with main_port A AND vessel V1 sub -> should appear once (dedup)
        self.u5 = User.create(
            chat_id=5, chat_type="group", username=None, first_name="group5", last_name=None, main_port=self.port_a
        )
        VesselSubscription.create(user=self.u5, vessel=self.v1)

        # u6: vessel V2 + port A -> should not get notifications for V1
        self.u6 = User.create(
            chat_id=6, chat_type="private", username=None, first_name="u6", last_name=None
        )
        VesselSubscription.create(user=self.u6, vessel=self.v2)
        PortSubscription.create(user=self.u6, port=self.port_a)

        # u7: subscribed to V1 and V2; has only port B subscription ->
        # should get V1 events at B, not at A
        self.u7 = User.create(
            chat_id=7, chat_type="private", username=None, first_name="u7", last_name=None
        )
        VesselSubscription.create(user=self.u7, vessel=self.v1)
        VesselSubscription.create(user=self.u7, vessel=self.v2)
        PortSubscription.create(user=self.u7, port=self.port_b)

        # u8: subscribed to V1; has both ports A and B subscriptions -> should get both
        self.u8 = User.create(
            chat_id=8, chat_type="private", username=None, first_name="u8", last_name=None
        )
        VesselSubscription.create(user=self.u8, vessel=self.v1)
        PortSubscription.create(user=self.u8, port=self.port_a)
        PortSubscription.create(user=self.u8, port=self.port_b)

    def test_arrival_at_port_a(self):
        log = PortLog.create(vessel=self.v1, port=self.port_a, event="arrival")
        users = get_users_to_notify_for_log(log)
        ids = sorted(u.chat_id for u in users)

        # Expect: u1 (v1 + port A), u2 (v1 + no ports), u4 (group main_port A), u5 (group main_port A & v1), u8 (v1 + port A)
        # Not: u3 (has port B, not A), u6 (subscribed to V2, not V1)
        expected = sorted([1, 2, 4, 5, 8])
        self.assertEqual(ids, expected)

        # Assert no duplicates
        self.assertEqual(len(ids), len(set(ids)))

    def test_arrival_at_port_b(self):
        log = PortLog.create(vessel=self.v1, port=self.port_b, event="arrival")
        users = get_users_to_notify_for_log(log)
        ids = sorted(u.chat_id for u in users)

        # Expect: u2 (v1 + no ports), u3 (v1 + port B), u5 (group with v1 + no ports)
        # Not: u1 (only port A), u4 (main_port A doesn't match), u6 (v2)
        # u7 has a port B sub, is subscribed to V1 -> included
        # u8 has port A and B subs, is subscribed to V1 -> included (for B)
        expected = sorted([2, 3, 5, 7, 8])
        self.assertEqual(ids, expected)
        self.assertEqual(len(ids), len(set(ids)))

    def test_departure_from_port_a(self):
        log = PortLog.create(vessel=self.v1, port=self.port_a, event="departure")
        users = get_users_to_notify_for_log(log)
        ids = sorted(u.chat_id for u in users)
        # Same routing applies for departures
        # u7 has only port B, so not included for A; u8 has port A, so included
        expected = sorted([1, 2, 4, 5, 8])
        self.assertEqual(ids, expected)
        self.assertEqual(len(ids), len(set(ids)))

    def test_multi_subscriptions_specific_cases(self):
        # V1 at A: u7 should NOT be included (only port B); u8 should be included (has A)
        log_a = PortLog.create(vessel=self.v1, port=self.port_a, event="arrival")
        ids_a = sorted(u.chat_id for u in get_users_to_notify_for_log(log_a))
        self.assertIn(8, ids_a)
        self.assertNotIn(7, ids_a)

        # V1 at B: both u7 and u8 included (both have port B)
        log_b = PortLog.create(vessel=self.v1, port=self.port_b, event="arrival")
        ids_b = sorted(u.chat_id for u in get_users_to_notify_for_log(log_b))
        self.assertIn(7, ids_b)
        self.assertIn(8, ids_b)

        # V2 at A: u7 is subscribed to V2 but only has port B -> should NOT be included
        log_v2_a = PortLog.create(vessel=self.v2, port=self.port_a, event="arrival")
        ids_v2_a = sorted(u.chat_id for u in get_users_to_notify_for_log(log_v2_a))
        self.assertNotIn(7, ids_v2_a)


if __name__ == "__main__":
    unittest.main()
