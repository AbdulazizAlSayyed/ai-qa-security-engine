"""Requirements registry business logic.

    Route -> RequirementService -> MongoDB: requirements
                   |
                   '-> AIAnalysisService.complete() -> AIProvider   (candidates only)

Every method is scoped to one target. A requirement is addressed by its
target *and* its id, and a mismatched pair is a 404 rather than a successful
read, so a statement written for one application can never be reached
through another.

Two properties are worth stating plainly, because the rest of the module is
built to keep them true.

**The registry owns the keys.** ``REQ-NNN`` is allocated here, monotonically
within a target, and never by a caller. A key is never reused, never
renumbered and never moved between targets, so a reference written in a
ticket today still means the same statement next year.

**The model never writes anything.** :meth:`extract_from_brd` returns
candidates and persists nothing at all - no requirement, no draft, no row in
any collection. The only way a candidate becomes a requirement is
:meth:`import_approved`, which takes a payload a human sent and runs it
through the same create path a hand-written requirement uses.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo import DESCENDING, ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.engines.ai.provider import AIProviderError, ProviderErrorCategory
from app.engines.requirements import openapi_import
from app.engines.requirements.models import EXTRACTION_VERSION
from app.engines.requirements.prompts import SYSTEM_PROMPT, build_user_prompt
from app.engines.requirements.validation import (
    ExtractionValidationError,
    validate_extraction,
)
from app.models.requirement import (
    FIRST_KEY_NUMBER,
    LIST_SORT,
    criterion_id,
    criterion_number,
    document_to_response,
    ensure_indexes,
    get_collection,
    requirement_key,
)
from app.schemas.requirement import (
    AcceptanceCriterion,
    RequirementCreate,
    RequirementSource,
    RequirementUpdate,
)
from app.services.ai_analysis_service import AIAnalysisService
from app.services.target_service import TargetService

logger = logging.getLogger(__name__)

#: How many times a create retries when two requests allocate the same key at
#: the same moment. The unique index is what detects the race; this is what
#: recovers from it.
KEY_ALLOCATION_ATTEMPTS = 5


class RequirementServiceError(Exception):
    """Base class for requirements registry failures."""


class InvalidRequirementIdError(RequirementServiceError):
    """The supplied id is not a well-formed MongoDB ObjectId."""


class RequirementNotFoundError(RequirementServiceError):
    """No such requirement exists on that target."""


class RequirementPersistenceError(RequirementServiceError):
    """MongoDB failed, so the change could not be made or recorded."""


class InvalidOpenApiDocumentError(RequirementServiceError):
    """The supplied text is not an OpenAPI document this platform can read."""


class RequirementExtractionError(RequirementServiceError):
    """The extraction ran and produced nothing usable.

    ``category`` is the provider's own category when the provider failed, or
    ``invalid_response`` when the answer was rejected by validation. Nothing
    was stored either way - an extraction has nothing to store.
    """

    def __init__(self, category: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
        self.details = details or {}


def _now() -> datetime:
    """Current UTC time at MongoDB's millisecond precision, as elsewhere."""
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _to_object_id(requirement_id: str) -> ObjectId:
    if not ObjectId.is_valid(requirement_id):
        raise InvalidRequirementIdError(
            f"{requirement_id!r} is not a valid requirement id."
        )
    return ObjectId(requirement_id)


def _stored_criteria_sequence(document: Mapping[str, Any]) -> int:
    """The next free AC number for a requirement.

    Read from the document when it is there. Derived from the criteria
    themselves when it is not, so a record written before this field existed
    still never reuses a number.
    """
    stored = document.get("criteria_sequence")
    if isinstance(stored, int) and stored >= 1:
        return stored
    highest = 0
    for criterion in document.get("acceptance_criteria") or []:
        if isinstance(criterion, Mapping):
            number = criterion_number(str(criterion.get("id") or ""))
            if number and number > highest:
                highest = number
    return highest + 1


def normalize_criteria(
    criteria: Sequence[AcceptanceCriterion],
    *,
    known_ids: Iterable[str] = (),
    sequence: int = 1,
) -> tuple[list[dict[str, str]], int]:
    """Give every criterion a stable ``AC-NNN`` id.

    An id the client echoes back is honoured when the requirement really has
    it; anything else - an omitted id, an invented one, a duplicate within
    the same request - gets the next free number. Numbers only ever go up, so
    deleting a criterion does not free its id for a different statement to
    take over later.

    Returns the criteria as they will be stored, and the new high-water mark.
    """
    known = set(known_ids)
    used: set[str] = set()
    next_number = max(int(sequence), FIRST_KEY_NUMBER)
    normalized: list[dict[str, str]] = []

    for criterion in criteria:
        supplied = (criterion.id or "").strip()
        if supplied and supplied in known and supplied not in used:
            identifier = supplied
        else:
            identifier = criterion_id(next_number)
            next_number += 1
        used.add(identifier)
        normalized.append({"id": identifier, "text": criterion.text})

    return normalized, next_number


class RequirementService:
    """CRUD over the requirements of one target at a time, plus candidates."""

    def __init__(
        self,
        db: AsyncDatabase,
        targets: TargetService,
        analysis: AIAnalysisService,
    ) -> None:
        self._collection = get_collection(db)
        self._db = db
        self._targets = targets
        self._analysis = analysis

    async def ensure_indexes(self) -> None:
        await ensure_indexes(self._db)

    async def _require_target(self, target_id: str) -> dict[str, Any]:
        """Resolve the target through the registry, or raise its own error."""
        return await self._targets.get(target_id)

    # --- key allocation -----------------------------------------------------

    async def _next_key_number(self, target_id: str) -> int:
        """One past the highest key this target currently holds.

        The maximum, not the count: deleting REQ-002 out of the middle of a
        registry leaves REQ-003 as the highest, so the next requirement is
        REQ-004 and the gap stays a gap. Deleting the *highest* requirement
        does lower the maximum, so its number is issued again to the next
        create - the series is monotonic over the live registry rather than
        over everything that has ever existed. Keeping a counter that
        outlived deletion would need somewhere to store it, and Phase 13 adds
        exactly one collection.

        Two requirements can never share a key whatever happens here: the
        unique index decides that, and :meth:`_insert` retries on the race.
        """
        try:
            highest = await self._collection.find_one(
                {"target_id": target_id},
                sort=[("key_number", DESCENDING)],
                projection={"key_number": 1},
            )
        except PyMongoError as exc:
            raise RequirementPersistenceError(
                f"Could not read the requirement series: {type(exc).__name__}"
            ) from exc
        if highest is None:
            return FIRST_KEY_NUMBER
        return int(highest.get("key_number", 0)) + 1

    # --- writes -------------------------------------------------------------

    async def create(self, target_id: str, payload: RequirementCreate) -> dict[str, Any]:
        """Write one requirement, allocating its key."""
        target = await self._require_target(target_id)
        return await self._insert(target["id"], payload)

    async def _insert(
        self,
        target_id: str,
        payload: RequirementCreate,
        *,
        extraction_id: str = "",
    ) -> dict[str, Any]:
        criteria, sequence = normalize_criteria(payload.acceptance_criteria)
        timestamp = _now()

        base = payload.model_dump(mode="json")
        base["acceptance_criteria"] = criteria
        base["criteria_sequence"] = sequence
        # Set by the service, never by the body of a create: a client cannot
        # claim a requirement came out of an extraction it did not review.
        base["extraction_id"] = extraction_id
        # The target comes from the path, never from the body.
        base["target_id"] = target_id
        base["created_at"] = timestamp
        base["updated_at"] = timestamp

        last_error: DuplicateKeyError | None = None
        for _ in range(KEY_ALLOCATION_ATTEMPTS):
            number = await self._next_key_number(target_id)
            document = dict(base)
            document["key_number"] = number
            document["key"] = requirement_key(number)
            try:
                await self._collection.insert_one(document)
            except DuplicateKeyError as exc:
                # Someone else took this key between the read and the write.
                # Look again rather than guessing the next one.
                last_error = exc
                continue
            except PyMongoError as exc:
                raise RequirementPersistenceError(
                    f"Could not write the requirement: {type(exc).__name__}"
                ) from exc

            logger.info(
                "Wrote requirement %s (%s) for target %s from %s",
                document["key"],
                document["_id"],
                target_id,
                document["source"],
            )
            return document_to_response(document)

        raise RequirementPersistenceError(
            "Could not allocate a requirement key after "
            f"{KEY_ALLOCATION_ATTEMPTS} attempts; something else is writing to this "
            "target's registry. Try again."
        ) from last_error

    async def update(
        self, target_id: str, requirement_id: str, payload: RequirementUpdate
    ) -> dict[str, Any]:
        """Apply a partial update to one requirement of one target."""
        target = await self._require_target(target_id)
        changes = payload.changes()

        if not changes:
            return await self.get(target_id, requirement_id)

        if payload.acceptance_criteria is not None:
            current = await self._read(target["id"], requirement_id)
            known = [
                str(item.get("id"))
                for item in current.get("acceptance_criteria") or []
                if isinstance(item, Mapping) and item.get("id")
            ]
            criteria, sequence = normalize_criteria(
                payload.acceptance_criteria,
                known_ids=known,
                sequence=_stored_criteria_sequence(current),
            )
            changes["acceptance_criteria"] = criteria
            changes["criteria_sequence"] = sequence

        changes["updated_at"] = _now()

        try:
            document = await self._collection.find_one_and_update(
                {"_id": _to_object_id(requirement_id), "target_id": target["id"]},
                {"$set": changes},
                return_document=ReturnDocument.AFTER,
            )
        except PyMongoError as exc:
            raise RequirementPersistenceError(
                f"Could not update the requirement: {type(exc).__name__}"
            ) from exc

        if document is None:
            raise RequirementNotFoundError(
                f"No requirement with id {requirement_id} on target {target_id}."
            )

        logger.info(
            "Updated requirement %s on target %s (%s)",
            document.get("key"),
            target_id,
            ", ".join(sorted(changes)),
        )
        return document_to_response(document)

    async def delete(self, target_id: str, requirement_id: str) -> dict[str, Any]:
        """Remove one requirement, and report which key is now gone.

        Deleting out of the middle of a registry leaves a gap that is never
        filled. Deleting the highest-numbered requirement does free its
        number for the next create - see :meth:`_next_key_number`. Marking a
        requirement ``deprecated`` keeps both the record and the key, which
        is the better move when anything already refers to it.
        """
        target = await self._require_target(target_id)
        try:
            document = await self._collection.find_one_and_delete(
                {"_id": _to_object_id(requirement_id), "target_id": target["id"]}
            )
        except PyMongoError as exc:
            raise RequirementPersistenceError(
                f"Could not delete the requirement: {type(exc).__name__}"
            ) from exc
        if document is None:
            raise RequirementNotFoundError(
                f"No requirement with id {requirement_id} on target {target_id}."
            )
        logger.info(
            "Deleted requirement %s from target %s", document.get("key"), target_id
        )
        return document_to_response(document)

    # --- reads --------------------------------------------------------------

    async def _read(self, target_id: str, requirement_id: str) -> dict[str, Any]:
        try:
            document = await self._collection.find_one(
                {"_id": _to_object_id(requirement_id), "target_id": target_id}
            )
        except PyMongoError as exc:
            raise RequirementPersistenceError(
                f"Could not read the requirement: {type(exc).__name__}"
            ) from exc
        if document is None:
            raise RequirementNotFoundError(
                f"No requirement with id {requirement_id} on target {target_id}."
            )
        return document

    async def get(self, target_id: str, requirement_id: str) -> dict[str, Any]:
        """One requirement, looked up by target *and* id."""
        target = await self._require_target(target_id)
        return document_to_response(await self._read(target["id"], requirement_id))

    async def list_for_target(
        self,
        target_id: str,
        *,
        status: str | None = None,
        priority: str | None = None,
        area: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """Every requirement of one target, REQ-001 first, optionally filtered.

        The filters are plain equality on indexed fields. There is no text
        search: a registry is read in order, and a half-working search would
        make a reader think they had seen everything.
        """
        target = await self._require_target(target_id)
        query: dict[str, Any] = {"target_id": target["id"]}
        for field, value in (
            ("status", status),
            ("priority", priority),
            ("area", area),
            ("source", source),
        ):
            if value is not None:
                query[field] = value

        try:
            documents = (
                await self._collection.find(query).sort(LIST_SORT).to_list(length=None)
            )
        except PyMongoError as exc:
            raise RequirementPersistenceError(
                f"Could not read the registry: {type(exc).__name__}"
            ) from exc
        return [document_to_response(document) for document in documents]

    async def count_for_target(self, target_id: str) -> int:
        """How many requirements a target has. Used by the delete guard."""
        return await self._collection.count_documents({"target_id": target_id})

    # --- candidates ---------------------------------------------------------
    #
    # Nothing below writes to MongoDB. These methods read a document the
    # operator supplied, propose requirements, and return them. The document
    # itself is used to build one prompt and then dropped: it is not stored,
    # not logged and not echoed back, because a business document belongs to
    # whoever pasted it.

    async def extract_from_brd(self, target_id: str, document: str) -> dict[str, Any]:
        """Propose requirements from a business document. Persists nothing.

        Goes through :meth:`AIAnalysisService.complete`, which is the single
        path to the configured provider, so an extraction is subject to the
        same provider abstraction, the same error categories and the same
        "no vendor SDK outside the provider" rule as every other model call
        in this platform.
        """
        target = await self._require_target(target_id)
        extraction_id = uuid.uuid4().hex

        logger.info(
            "Requirement extraction %s started: target=%s provider=%s model=%s chars=%d",
            extraction_id,
            target["id"],
            self._analysis.provider_name,
            self._analysis.provider_model or "-",
            len(document),
        )

        try:
            reply = await self._analysis.complete(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_user_prompt(document),
            )
        except AIProviderError as exc:
            logger.warning(
                "Requirement extraction %s failed (%s)", extraction_id, exc.category.value
            )
            raise RequirementExtractionError(exc.category.value, exc.message) from exc
        except Exception as exc:  # a provider bug is still just a failed extraction
            logger.exception("Requirement extraction %s: unexpected provider exception", extraction_id)
            raise RequirementExtractionError(
                ProviderErrorCategory.PROVIDER_ERROR.value,
                f"The AI provider failed unexpectedly ({type(exc).__name__}).",
            ) from exc

        try:
            output = validate_extraction(reply.text)
        except ExtractionValidationError as exc:
            logger.warning(
                "Requirement extraction %s rejected (%s)", extraction_id, exc.code
            )
            raise RequirementExtractionError(
                ProviderErrorCategory.INVALID_RESPONSE.value, exc.message, exc.details
            ) from exc

        logger.info(
            "Requirement extraction %s completed: %d candidate(s), %d note(s)",
            extraction_id,
            len(output.candidates),
            len(output.notes),
        )

        notes = list(output.notes)
        notes.append(
            "These are proposals. Nothing was written to the registry - review, edit "
            "and import the ones you accept."
        )

        return {
            "target_id": target["id"],
            "source": RequirementSource.BRD.value,
            "extraction_id": extraction_id,
            "provider": self._analysis.provider_name,
            "model": reply.model or self._analysis.provider_model,
            "candidates": [candidate.model_dump() for candidate in output.candidates],
            "notes": notes,
            "document_chars": len(document),
        }

    async def extract_from_openapi(self, target_id: str, document: str) -> dict[str, Any]:
        """Propose requirements from an OpenAPI document. Offline; no model.

        The document is parsed where it stands. Nothing is fetched, no
        operation it describes is called, and no ``$ref`` is dereferenced.
        """
        target = await self._require_target(target_id)
        extraction_id = uuid.uuid4().hex

        try:
            candidates, notes = openapi_import.extract_candidates(document)
        except openapi_import.OpenApiDocumentError as exc:
            raise InvalidOpenApiDocumentError(str(exc)) from exc

        logger.info(
            "OpenAPI import %s: target=%s chars=%d candidates=%d (offline, no request sent)",
            extraction_id,
            target["id"],
            len(document),
            len(candidates),
        )

        notes = list(notes)
        notes.append(
            "These are proposals. Nothing was written to the registry - review, edit "
            "and import the ones you accept."
        )

        return {
            "target_id": target["id"],
            "source": RequirementSource.OPENAPI.value,
            "extraction_id": extraction_id,
            # Empty on purpose: no model was involved, and claiming one would
            # make this look like an inference when it is a parse.
            "provider": "",
            "model": "",
            "candidates": candidates,
            "notes": notes,
            "document_chars": len(document),
        }

    async def import_approved(
        self,
        target_id: str,
        requirements: Sequence[RequirementCreate],
        *,
        extraction_id: str = "",
    ) -> list[dict[str, Any]]:
        """Write requirements a human reviewed and accepted.

        This is the whole approval mechanism, and it is deliberately dull:
        each entry is an ordinary :class:`RequirementCreate`, validated by the
        same schema a hand-written one goes through, and written by the same
        code path. A candidate the reviewer rejected is simply not in the
        list; an edit the reviewer made is what arrives here. A rejected
        proposal leaves no trace, because a proposal nobody accepted is not a
        fact about the target - what is kept is what a person stood behind.

        ``extraction_id`` is stored on each requirement so the run that
        proposed it can be found in the logs. It records where the text came
        from, and nothing about whether it is correct.
        """
        target = await self._require_target(target_id)

        created: list[dict[str, Any]] = []
        for index, payload in enumerate(requirements, start=1):
            try:
                created.append(
                    await self._insert(
                        target["id"], payload, extraction_id=extraction_id
                    )
                )
            except RequirementPersistenceError as exc:
                raise RequirementPersistenceError(
                    f"{len(created)} requirement(s) were written before entry {index} "
                    f"failed, and they are still there: {exc}"
                ) from exc

        logger.info(
            "Imported %d approved requirement(s) for target %s: %s",
            len(created),
            target["id"],
            ", ".join(item["key"] for item in created),
        )
        return created


#: Named so the extraction contract version is visible from the service.
__all__ = [
    "EXTRACTION_VERSION",
    "InvalidOpenApiDocumentError",
    "InvalidRequirementIdError",
    "RequirementExtractionError",
    "RequirementNotFoundError",
    "RequirementPersistenceError",
    "RequirementService",
    "RequirementServiceError",
    "normalize_criteria",
]
