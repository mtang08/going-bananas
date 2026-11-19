import pytest
from fastapi import HTTPException

from app.errors import AppError, fail


def test_fail_raises_app_error_with_code() -> None:
    with pytest.raises(AppError) as caught:
        fail('session_not_found', 'Session not found', 404)
    error = caught.value
    assert error.code == 'session_not_found'
    assert error.message == 'Session not found'
    assert error.status_code == 404
    assert error.detail == {'code': 'session_not_found', 'message': 'Session not found'}
    assert isinstance(error, HTTPException)


def test_app_error_keeps_fields_and_default_status() -> None:
    error = AppError('proposal_invalid', 'Invalid', fields=[
        {'code': 'x', 'path': 'changes.0', 'message': 'bad'},
    ])
    assert error.status_code == 422
    assert error.detail['fields'][0]['path'] == 'changes.0'
