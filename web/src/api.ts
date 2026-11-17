// Talking to the Python API.
//
// The types here are generated from the API's OpenAPI schema (`npm run gen:api`), so if a route
// or a field changes in Python, `npm run typecheck` fails here instead of the page breaking.
import createClient from "openapi-fetch";

import type { components, paths } from "../../packages/api-client/schema";

export type Schemas = components["schemas"];
export type Account = Schemas["AccountOut"];
export type Summary = Schemas["Summary"];
export type Txn = Schemas["TransactionRow"];
export type Category = Schemas["CategoryOut"];
export type Person = Schemas["CounterpartyOut"];
export type Template = Txn["template"];
export type Subtype = Account["subtype"];
export type Profile = Schemas["Profile"];
export type Brand = Schemas["BrandOut"];
export type MerchantTotal = Schemas["MerchantTotal"];
export type FriendLedger = Schemas["FriendLedger"];

// In development Vite forwards /api/... to the Python server (see vite.config.ts).
export const BASE = "/api";
const client = createClient<paths>({ baseUrl: BASE });

/** Everything the screens show, fetched together so they always agree with each other. */
export type Book = {
  accounts: Account[];
  summary: Summary;
  transactions: Txn[];
  categories: Category[];
  people: Person[];
  profile: Profile;
};

export async function loadBook(): Promise<Book> {
  const [accounts, summary, transactions, categories, people, profile] = await Promise.all([
    client.GET("/accounts"),
    client.GET("/summary"),
    client.GET("/transactions"),
    client.GET("/categories"),
    client.GET("/counterparties"),
    client.GET("/me"),
  ]);
  if (
    !accounts.data ||
    !summary.data ||
    !transactions.data ||
    !categories.data ||
    !people.data ||
    !profile.data
  ) {
    throw new Error("The API did not answer. Is it running?");
  }
  return {
    accounts: accounts.data,
    summary: summary.data,
    transactions: transactions.data,
    categories: categories.data,
    people: people.data,
    profile: profile.data,
  };
}

/** One person's history with a running position (the friends ledger). Fetched when opened. */
export async function loadFriendLedger(counterpartyId: string): Promise<FriendLedger> {
  const { data } = await client.GET("/counterparties/{counterparty_id}/ledger", {
    params: { path: { counterparty_id: counterpartyId } },
  });
  if (!data) throw new Error("Could not load this person's ledger.");
  return data;
}

/** What the server said was wrong, in words fit to show next to the form. */
function errorMessage(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  return `The server answered ${status}.`;
}

/**
 * POST with an Idempotency-Key (CLAUDE.md §6).
 *
 * Each call makes one key. If the network drops, the same request is sent again with the SAME
 * key, and the server answers with what it stored the first time, so a retry can never write a
 * second transaction.
 */
export async function post<T>(path: string, body?: object): Promise<T> {
  const key = crypto.randomUUID();
  for (let attempt = 1; ; attempt++) {
    let response: Response;
    try {
      response = await fetch(BASE + path, {
        method: "POST",
        headers: { "Idempotency-Key": key, "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch {
      if (attempt < 3) continue;
      throw new Error("Could not reach the server. Try again; nothing will be saved twice.");
    }
    const data: unknown = await response.json().catch(() => null);
    if (response.ok) return data as T;
    throw new Error(errorMessage(data, response.status));
  }
}
