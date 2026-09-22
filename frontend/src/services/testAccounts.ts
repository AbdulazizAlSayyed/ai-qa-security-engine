import { apiDelete, apiGet, apiPatch, apiPost } from "@/services/api";
import type {
  TestAccount,
  TestAccountCreate,
  TestAccountDeleteResult,
  TestAccountUpdate,
} from "@/types/testAccount";

/**
 * Accounts are always addressed through their target. There is no route that
 * reaches one without naming the target it belongs to, which is what keeps an
 * identity registered for one application out of another's reach.
 */
const base = (targetId: string) => `/targets/${targetId}/test-accounts`;

export function listTestAccounts(
  targetId: string,
  signal?: AbortSignal,
): Promise<TestAccount[]> {
  return apiGet<TestAccount[]>(base(targetId), { signal });
}

export function getTestAccount(
  targetId: string,
  accountId: string,
  signal?: AbortSignal,
): Promise<TestAccount> {
  return apiGet<TestAccount>(`${base(targetId)}/${accountId}`, { signal });
}

export function createTestAccount(
  targetId: string,
  body: TestAccountCreate,
): Promise<TestAccount> {
  // The API answers 201 on a successful create.
  return apiPost<TestAccount>(base(targetId), body, { acceptStatuses: [201] });
}

export function updateTestAccount(
  targetId: string,
  accountId: string,
  body: TestAccountUpdate,
): Promise<TestAccount> {
  return apiPatch<TestAccount>(`${base(targetId)}/${accountId}`, body);
}

export function deleteTestAccount(
  targetId: string,
  accountId: string,
): Promise<TestAccountDeleteResult> {
  return apiDelete<TestAccountDeleteResult>(`${base(targetId)}/${accountId}`);
}
