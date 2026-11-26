"""A run or connection test that fails because the model account has no credit says so plainly."""
from pydantic_ai.exceptions import ModelQuotaExceededError

from app.agents import loop
from app.models import connection


def _no_credit() -> ModelQuotaExceededError:
    return ModelQuotaExceededError(model_name="any-model", message="insufficient_quota")


def test_an_agent_run_stopped_by_no_credit_says_an_admin_must_add_credit():
    assert loop.failure_sentence(_no_credit(), during_setup=False) == (
        "The model account has no credit left, so an admin needs to add credit before trying again.")


def test_the_connection_test_says_the_same():
    assert connection.failure_sentence(_no_credit()) == (
        "The model account has no credit left, so an admin needs to add credit before trying again.")
