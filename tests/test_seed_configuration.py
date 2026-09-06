import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from database.scripts import generate_seed_data as seed
from database.scripts import generate_test_payloads as payloads


class SeedConfigurationTests(unittest.TestCase):
    def test_seed_and_payload_baselines_are_aligned(self):
        self.assertEqual(seed.BASE_CUSTOMERS, 200_000)
        self.assertEqual(seed.BASE_ORDERS, 200_000)
        self.assertEqual(payloads.BASE_CUSTOMERS, seed.BASE_CUSTOMERS)
        self.assertEqual(payloads.BASE_ORDERS, seed.BASE_ORDERS)
        self.assertEqual(payloads.CREATE_ORDERS, seed.BASE_ORDERS)

    def test_committed_seed_matches_deterministic_template(self):
        self.assertEqual(seed.SEED_SQL.read_text(encoding="utf-8"), seed.SEED_TEMPLATE)

    def test_seed_limits_warmup_growth_to_five_percent(self):
        fixed_200_requests = 200 * 300
        expected_customer_creates = fixed_200_requests * 10 // 100
        expected_order_creates = fixed_200_requests * 15 // 100
        self.assertLessEqual(expected_customer_creates / seed.BASE_CUSTOMERS, 0.05)
        self.assertLessEqual(expected_order_creates / seed.BASE_ORDERS, 0.05)

    def test_customer_identifiers_do_not_truncate_at_the_seed_limit(self):
        self.assertIn("'cliente.base.' || lpad(gs::text, 6, '0')", seed.SEED_TEMPLATE)

    def test_contract_fixtures_use_the_enlarged_seed_boundary(self):
        contract_script = (ROOT / "scripts" / "contract_test_api.py").read_text(encoding="utf-8")
        state_capture = (ROOT / "database" / "scripts" / "capture_contract_state.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("BASE_CUSTOMERS = 200_000", contract_script)
        self.assertIn('"total": BASE_CUSTOMERS', contract_script)
        self.assertIn("cliente.base.000001@example.com", contract_script)
        for boundary in ("id > 200000", "id > 400000"):
            self.assertIn(boundary, state_capture)


if __name__ == "__main__":
    unittest.main()
