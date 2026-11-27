"""Exercise metric command receipts, retry behavior, and persisted state."""

from check_assessment_db import seed
from check_health_startup import run_database_test


if __name__ == "__main__":
    run_database_test("./internal/metriccli", seed)
