from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from enum import Enum
from typing import TypedDict

from tenacity import retry, stop_after_attempt, wait_exponential

from app.services.vector_store import VectorStoreService

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 50
_DEFAULT_MAX_CONCURRENT_DELETES = 10
_DEFAULT_PAGE_SIZE = 1_000


class ReconStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    DRY_RUN = "dry_run"


class ReconciliationResult(TypedDict):
    tenant_id: str
    orphaned_documents_removed: list[str]
    orphaned_removal_failed: list[str]
    orphaned_documents_would_remove: list[str] 
    missing_documents_flagged: list[str]
    total_active_vectors_scanned: int
    status: ReconStatus


class ReconciliationError(Exception):
    pass


class VectorReconciliationService:
    def __init__(
        self,
        vector_store: VectorStoreService,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        max_concurrent_deletes: int = _DEFAULT_MAX_CONCURRENT_DELETES,
        page_size: int = _DEFAULT_PAGE_SIZE,
    ) -> None:
        self.vector_store = vector_store
        self.batch_size = batch_size
        self.page_size = page_size
        self._deletion_semaphore = asyncio.Semaphore(max_concurrent_deletes)

    @property
    def tenant_id(self) -> str:
        return self.vector_store.tenant_id

    async def reconcile_tenant(
        self,
        authoritative_document_ids: set[str],
        dry_run: bool = False,
    ) -> ReconciliationResult:
        if not authoritative_document_ids:
            logger.warning(
                "reconcile_tenant called with an empty authoritative set for tenant '%s'. "
                "Every indexed document would be treated as an orphan. "
                "Pass at least one document ID, or verify the caller is correct.",
                self.tenant_id,
            )

        logger.info(
            "Starting vector reconciliation for tenant '%s' (authoritative docs: %d, dry_run: %s).",
            self.tenant_id,
            len(authoritative_document_ids),
            dry_run,
        )

        indexed_document_ids = await self._fetch_indexed_document_ids()

        orphaned_ids = indexed_document_ids - authoritative_document_ids
        missing_ids = authoritative_document_ids - indexed_document_ids

        logger.info(
            "Reconciliation analysis for tenant '%s': %d orphan(s), %d missing.",
            self.tenant_id,
            len(orphaned_ids),
            len(missing_ids),
        )

        if dry_run:
            return ReconciliationResult(
                tenant_id=self.tenant_id,
                orphaned_documents_removed=[],
                orphaned_removal_failed=[],
                orphaned_documents_would_remove=list(orphaned_ids),
                missing_documents_flagged=list(missing_ids),
                total_active_vectors_scanned=len(indexed_document_ids),
                status=ReconStatus.DRY_RUN,
            )

        purged, failed = await self._purge_in_batches(orphaned_ids)

        status = ReconStatus.SUCCESS if not failed else ReconStatus.PARTIAL_FAILURE
        return ReconciliationResult(
            tenant_id=self.tenant_id,
            orphaned_documents_removed=purged,
            orphaned_removal_failed=failed,
            orphaned_documents_would_remove=[],
            missing_documents_flagged=list(missing_ids),
            total_active_vectors_scanned=len(indexed_document_ids),
            status=status,
        )

    async def _fetch_indexed_document_ids(self) -> set[str]:
        indexed: set[str] = set()
        try:
            async for page in self.vector_store.list_document_ids_paginated(
                page_size=self.page_size
            ):
                indexed.update(page)
        except Exception as exc:
            logger.error(
                "Failed to retrieve indexed document IDs for tenant '%s': %s",
                self.tenant_id,
                exc,
            )
            raise ReconciliationError(
                "Aborting reconciliation: index metadata unreachable."
            ) from exc
        return indexed

    async def _purge_in_batches(
        self, orphaned_ids: set[str]
    ) -> tuple[list[str], list[str]]:
        purged: list[str] = []
        failed: list[str] = []

        orphaned_list = list(orphaned_ids)
        for i in range(0, len(orphaned_list), self.batch_size):
            batch = orphaned_list[i : i + self.batch_size]
            tasks = [self._purge_document(doc_id) for doc_id in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            batch_purged = sum(1 for r in results if not isinstance(r, Exception))
            logger.debug(
                "Batch %d–%d for tenant '%s': purged %d/%d.",
                i,
                i + len(batch),
                self.tenant_id,
                batch_purged,
                len(batch),
            )

            for doc_id, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error(
                        "Failed to purge orphaned vectors for document '%s' (tenant '%s'): %s",
                        doc_id,
                        self.tenant_id,
                        result,
                    )
                    failed.append(doc_id)
                else:
                    purged.append(doc_id)

        return purged, failed

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    async def _purge_document(self, document_id: str) -> None:
        async with self._deletion_semaphore:
            logger.debug(
                "Purging vectors for document '%s' (tenant '%s').",
                document_id,
                self.tenant_id,
            )
            await self.vector_store.delete_by_document_id_async(document_id)