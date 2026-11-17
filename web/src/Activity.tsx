// The transaction list, grouped by day, with a search box and brand / category filters.
// Also used on the Friends screen, without the filters.
import { useState } from "react";

import type { Summary, Txn } from "./api";
import { dayLabel } from "./dates";
import { LABELS } from "./templates";
import { BrandTile } from "./ui";

/** What the list is narrowed to. Set from the chips here or from a click on the Overview. */
export type Filter = { kind: "brand"; key: string } | { kind: "category"; id: string } | null;

/** "Harbor Checking → Wallet", leaving out the two outside accounts the user never sees. */
function route(txn: Txn): string {
  const shown = txn.legs.filter((l) => l.subtype !== "world" && l.subtype !== "opening");
  // The leg with the negative amount is where the money came from.
  const from = shown.find((l) => l.amount.minor < 0);
  const to = shown.find((l) => l.amount.minor > 0);
  return [from?.account_name, to?.account_name].filter(Boolean).join(" → ");
}

function Row({ txn, onVoid }: { txn: Txn; onVoid: (id: string) => void }) {
  const { label, glyph } = LABELS[txn.template];
  const voided = txn.voided_at !== null;
  // net is the change in net worth. Zero means money only moved between your own accounts.
  const tone = txn.net.minor > 0 ? "pos" : txn.net.minor < 0 ? "neg" : "";
  const amount =
    txn.net.minor > 0
      ? `+${txn.net.display}`
      : txn.net.minor < 0
        ? txn.net.display
        : txn.amount.display;
  const details = [route(txn), txn.category?.name, txn.method?.replace("_", " ")].filter(Boolean);

  return (
    <li className={voided ? "row voided" : "row"}>
      <BrandTile
        brand={txn.brand}
        fallback={
          <span className={`glyph t-${txn.template}`} aria-hidden="true">
            {glyph}
          </span>
        }
      />
      <div className="row-main">
        <span className="row-title">
          {txn.memo || label}
          {voided && <span className="tag">void</span>}
        </span>
        <span className="muted small">
          {txn.memo ? `${label} · ` : ""}
          {details.join(" · ")}
        </span>
      </div>
      <span className={`num ${voided ? "" : tone}`}>{amount}</span>
      {!voided && (
        <button className="row-action" onClick={() => onVoid(txn.id)} title="Void this transaction">
          Void
        </button>
      )}
    </li>
  );
}

/** One string per filter, so two filters compare with ===. */
const filterId = (f: Filter) => (!f ? "" : f.kind === "brand" ? `b:${f.key}` : `c:${f.id}`);

function matches(txn: Txn, filter: Filter, query: string): boolean {
  if (filter?.kind === "brand" && txn.brand?.key !== filter.key) return false;
  if (filter?.kind === "category" && txn.category?.id !== filter.id) return false;
  if (!query) return true;
  const haystack = [txn.memo, txn.category?.name, txn.brand?.name, LABELS[txn.template].label]
    .join(" ")
    .toLowerCase();
  return haystack.includes(query.toLowerCase());
}

/** The chips and this month's figure for the picked one. Totals come from the server summary. */
function Filters(props: {
  rows: Txn[];
  summary: Summary;
  filter: Filter;
  setFilter: (f: Filter) => void;
}) {
  // Every brand and category that appears in the list, each once, in first-seen order.
  const brands = new Map<string, NonNullable<Txn["brand"]>>();
  const categories = new Map<string, string>();
  for (const t of props.rows) {
    if (t.brand) brands.set(t.brand.key, t.brand);
    if (t.category) categories.set(t.category.id, t.category.name);
  }
  const { filter, setFilter, summary } = props;
  const isOn = (f: NonNullable<Filter>) => filterId(filter) === filterId(f);
  const toggle = (f: NonNullable<Filter>) => setFilter(isOn(f) ? null : f);

  const month =
    filter?.kind === "brand"
      ? summary.month.merchants.find((m) => m.key === filter.key)
      : filter?.kind === "category"
        ? summary.month.categories.find((c) => c.id === filter.id)
        : undefined;

  return (
    <>
      <div className="filter-chips" role="group" aria-label="Filter by brand or category">
        <button className={filter ? "pill" : "pill solid"} onClick={() => setFilter(null)}>
          All
        </button>
        {[...brands.values()].map((b) => (
          <button
            key={b.key}
            className={isOn({ kind: "brand", key: b.key }) ? "pill solid" : "pill"}
            onClick={() => toggle({ kind: "brand", key: b.key })}
            aria-pressed={isOn({ kind: "brand", key: b.key })}
          >
            <BrandTile brand={b} fallback={null} />
            {b.name}
          </button>
        ))}
        {[...categories].map(([id, name]) => (
          <button
            key={id}
            className={isOn({ kind: "category", id }) ? "pill solid" : "pill"}
            onClick={() => toggle({ kind: "category", id })}
            aria-pressed={isOn({ kind: "category", id })}
          >
            {name}
          </button>
        ))}
      </div>
      {filter && (
        <p className="muted small filter-note">
          This month: <span className="num">{month ? month.total.display : "nothing yet"}</span>
          {month &&
            "count" in month &&
            ` across ${month.count} transaction${month.count === 1 ? "" : "s"}`}
        </p>
      )}
    </>
  );
}

export function Activity(props: {
  rows: Txn[];
  today: string;
  onVoid: (id: string) => void;
  // Given on the Activity screen; the Friends screen leaves these out and gets a plain list.
  summary?: Summary;
  filter?: Filter;
  setFilter?: (f: Filter) => void;
}) {
  const [query, setQuery] = useState("");
  const filter = props.filter ?? null;
  const rows = props.rows.filter((t) => matches(t, filter, query));

  // The rows arrive newest first, so one pass collects them into days in order.
  const days: { day: string; rows: Txn[] }[] = [];
  for (const row of rows) {
    const last = days[days.length - 1];
    if (last && last.day === row.occurred_on) last.rows.push(row);
    else days.push({ day: row.occurred_on, rows: [row] });
  }

  return (
    <>
      {props.summary && props.setFilter && (
        <>
          <input
            className="search"
            type="search"
            placeholder="Search memo, brand or category"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search transactions"
          />
          <Filters
            rows={props.rows}
            summary={props.summary}
            filter={filter}
            setFilter={props.setFilter}
          />
        </>
      )}
      {rows.length === 0 && (
        <p className="muted">{props.rows.length ? "Nothing matches." : "No transactions yet."}</p>
      )}
      <div className="days">
        {days.map(({ day, rows }) => (
          <section key={day}>
            <h3 className="day">{dayLabel(day, props.today)}</h3>
            <ul className="rows glass">
              {rows.map((t) => (
                <Row key={t.id} txn={t} onVoid={props.onVoid} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </>
  );
}
