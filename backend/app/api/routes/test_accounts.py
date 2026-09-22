"""Test account endpoints, nested under the target they belong to.

The nesting is the point. Every path names a target, the service queries on
both the target and the account, and there is no route that reaches an
account without saying which target it is on - so an identity registered for
one application cannot be read or changed through another.

Like the target routes these are deliberately thin: schemas validate, the
service decides, and ``app.main`` translates service errors into status
codes.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.dependencies import TestAccountServiceDep
from app.schemas.test_account import (
    TestAccountCreate,
    TestAccountDeleteResponse,
    TestAccountResponse,
    TestAccountUpdate,
)

router = APIRouter(prefix="/targets/{target_id}/test-accounts", tags=["test-accounts"])

_NOT_FOUND = {"description": "No such target, or no such account on that target."}
_BAD_ID = {"description": "The target or account id is not a well-formed ObjectId."}
_DUPLICATE = {"description": "The target already has an account with that name."}


@router.post(
    "",
    response_model=TestAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a test account for a target",
    responses={400: _BAD_ID, 404: _NOT_FOUND, 409: _DUPLICATE},
)
async def create_test_account(
    target_id: str, payload: TestAccountCreate, service: TestAccountServiceDep
) -> TestAccountResponse:
    """Record an identity a future phase may use against this target.

    The body carries no password and has no field for one:
    ``credential_reference`` names an environment variable instead.
    """
    return TestAccountResponse(**await service.create(target_id, payload))


@router.get(
    "",
    response_model=list[TestAccountResponse],
    summary="List a target's test accounts",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def list_test_accounts(
    target_id: str, service: TestAccountServiceDep
) -> list[TestAccountResponse]:
    """Every identity registered for this target, newest first."""
    return [
        TestAccountResponse(**account)
        for account in await service.list_for_target(target_id)
    ]


@router.get(
    "/{account_id}",
    response_model=TestAccountResponse,
    summary="Get one test account",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def get_test_account(
    target_id: str, account_id: str, service: TestAccountServiceDep
) -> TestAccountResponse:
    """Safe metadata for a single identity. Never a credential."""
    return TestAccountResponse(**await service.get(target_id, account_id))


@router.patch(
    "/{account_id}",
    response_model=TestAccountResponse,
    summary="Update a test account",
    responses={400: _BAD_ID, 404: _NOT_FOUND, 409: _DUPLICATE},
)
async def update_test_account(
    target_id: str,
    account_id: str,
    payload: TestAccountUpdate,
    service: TestAccountServiceDep,
) -> TestAccountResponse:
    """Change some fields, including ``enabled`` to take the identity out of use."""
    return TestAccountResponse(**await service.update(target_id, account_id, payload))


@router.delete(
    "/{account_id}",
    response_model=TestAccountDeleteResponse,
    summary="Delete a test account",
    responses={400: _BAD_ID, 404: _NOT_FOUND},
)
async def delete_test_account(
    target_id: str, account_id: str, service: TestAccountServiceDep
) -> TestAccountDeleteResponse:
    """Remove the identity from the registry."""
    await service.delete(target_id, account_id)
    return TestAccountDeleteResponse(deleted=True, id=account_id)
