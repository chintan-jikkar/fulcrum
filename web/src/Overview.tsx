// The dashboard. Every number here is a string the API already formatted.
import type { Filter } from "./Activity";
import type { Account, Book } from "./api";
import { monthLabel } from "./dates";
import { BrandTile } from "./ui";

const KIND_LABEL: Record<string, string> = { cash: "Cash", bank: "Bank" };

/** The bank's tile if the API recognised the name, else a plain monogram of the first letter. */
function AccountMark({ account }: { account: Account }) {
  return (
    <BrandTile
      brand={account.brand}
      fallback={
        <span className="brand-tile monogram" aria-hidden="true">
          {account.subtype === "cash" ? "$" : account.name.slice(0, 1)}
        </span>
      }
    />
  );
}

/** A utilization ring. The arc length is geometry from basis points, not a money figure. */
function Ring({ bps }: { bps: number }) {
  const r = 22;
  const around = 2 * Math.PI * r;
  const filled = (around * Math.min(bps, 10000)) / 10000;
  // Under 30% is the usual healthy line; over 70% is shown as hot.
  const tone = bps >= 7000 ? "hot" : bps >= 3000 ? "warm" : "cool";
  return (
    <svg className={`ring ${tone}`} viewBox="0 0 56 56" aria-hidden="true">
      <circle className="ring-track" cx="28" cy="28" r={r} />
      <circle
        className="ring-fill"
        cx="28"
        cy="28"
        r={r}
        strokeDasharray={`${filled} ${around}`}
        transform="rotate(-90 28 28)"
      />
    </svg>
  );
}

function CardTile({ card }: { card: Account }) {
  const credit = card.credit;
  return (
    <article className="tile glass card-tile">
      {credit?.utilization_bps != null && <Ring bps={credit.utilization_bps} />}
      <div className="tile-body">
        <span className="tile-title">
          <AccountMark account={card} />
          <span className="tile-name">{card.name}</span>
        </span>
        <span className="num big">{card.balance.display}</span>
        <span className="muted small">
          {credit?.limit
            ? `owed · ${credit.available?.display} left of ${credit.limit.display} · ${credit.utilization_display} used`
            : "owed · no limit set"}
        </span>
      </div>
    </article>
  );
}

export function Overview({
  book,
  onAddAccount,
  onShow,
}: {
  book: Book;
  onAddAccount: () => void;
  onShow: (filter: Filter) => void; // open Activity narrowed to a brand or category
}) {
  const { summary } = book;
  const active = book.accounts.filter((a) => a.is_active);
  const money = active.filter((a) => a.subtype === "cash" || a.subtype === "bank");
  const cards = active.filter((a) => a.subtype === "credit_card");
  const spending = summary.month.categories.filter((c) => c.kind === "expense" && !c.parent_id);
  const friends = summary.friends.filter((f) => f.position.minor !== 0);

  return (
    <>
      <section className="hero glass">
        <span className="eyebrow">Net worth</span>
        <span className="num hero-num">{summary.net_worth.display}</span>
        <div className="chips">
          <span className="chip in">In {summary.month.income.display}</span>
          <span className="chip out">Out {summary.month.expense.display}</span>
          <span className="muted small">{monthLabel(summary.month.start)}</span>
        </div>
      </section>

      <div className="section-head">
        <h2>Cash &amp; bank</h2>
        <button className="link" onClick={onAddAccount}>
          + Add account
        </button>
      </div>
      {active.length === 0 && (
        <p className="muted">No accounts yet. Add one with its current balance to begin.</p>
      )}
      <div className="grid">
        {money.map((a) => (
          <article key={a.id} className="tile glass">
            <span className="tile-title">
              <AccountMark account={a} />
              <span className="tile-name">{a.name}</span>
              <span className="tag">{KIND_LABEL[a.subtype]}</span>
            </span>
            <span className={a.balance.minor < 0 ? "num big neg" : "num big"}>
              {a.balance.display}
            </span>
          </article>
        ))}
      </div>

      {cards.length > 0 && (
        <>
          <div className="section-head">
            <h2>Credit cards</h2>
            {summary.credit.limit && (
              <span className="muted small">
                {summary.credit.owed.display} owed of {summary.credit.limit.display} ·{" "}
                {summary.credit.utilization_display} used
              </span>
            )}
          </div>
          <div className="grid">
            {cards.map((c) => (
              <CardTile key={c.id} card={c} />
            ))}
          </div>
        </>
      )}

      <div className="columns">
        <section className="panel glass">
          <h2>Spending in {monthLabel(summary.month.start)}</h2>
          {spending.length === 0 && <p className="muted">Nothing spent yet this month.</p>}
          {spending.map((c) => (
            <button
              key={c.id}
              className="bar-row"
              onClick={() => onShow({ kind: "category", id: c.id })}
              title={`See ${c.name} in Activity`}
            >
              <div className="bar-label">
                <span>{c.name}</span>
                <span className="num">{c.total.display}</span>
              </div>
              {/* share_bps comes from the server; dividing by 100 only turns it into a CSS %. */}
              <div className="bar">
                <span style={{ width: `${c.share_bps / 100}%` }} />
              </div>
            </button>
          ))}
        </section>

        {summary.month.merchants.length > 0 && (
          <section className="panel glass">
            <h2>Where it went</h2>
            {summary.month.merchants.map((m) => (
              <button
                key={m.key}
                className="merchant-row"
                onClick={() => onShow({ kind: "brand", key: m.key })}
                title={`See ${m.name} in Activity`}
              >
                <BrandTile brand={m} fallback={null} />
                <span className="merchant-name">
                  {m.name}
                  <span className="muted small">
                    {m.count} transaction{m.count === 1 ? "" : "s"}
                  </span>
                </span>
                <span className="num">{m.total.display}</span>
              </button>
            ))}
          </section>
        )}

        <section className="panel glass">
          <h2>Friends</h2>
          {friends.length === 0 && <p className="muted">Everyone is settled up.</p>}
          {friends.map((f) => (
            <div key={f.counterparty_id} className="friend-row">
              <span className="avatar">{f.name.slice(0, 1)}</span>
              <span>{f.name}</span>
              <span className={f.position.minor > 0 ? "num pos" : "num neg"}>
                {f.position.minor > 0 ? "owes you " : "you owe "}
                {f.amount.display}
              </span>
            </div>
          ))}
        </section>
      </div>
    </>
  );
}
