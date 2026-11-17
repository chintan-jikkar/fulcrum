// The friends ledger (P3): everyone you lend to or borrow from, and for the person picked, a
// table of every transaction with them and where you stood after each one. All the figures,
// the running position included, come from the server (CLAUDE.md §6: no money math here).
import { useEffect, useState } from "react";

import type { Preset } from "./AddTransaction";
import { type Book, type FriendLedger, loadFriendLedger, type Template } from "./api";
import { LABELS } from "./templates";

const ACTIONS: { template: Template; label: string }[] = [
  { template: "lend", label: "Lend" },
  { template: "friend_repay", label: "They repaid" },
  { template: "borrow", label: "Borrow" },
  { template: "repay_friend", label: "Repay" },
];

const METHOD: Record<string, string> = {
  cash: "Cash",
  bank_transfer: "Bank transfer",
  card: "Card",
  other: "Other",
};

/** "owes you $40.00", "you owe $12.00", "settled up". `amount` is the server's absolute figure. */
function standing(minor: number, amount: string): string {
  if (minor > 0) return `owes you ${amount}`;
  if (minor < 0) return `you owe ${amount}`;
  return "settled up";
}

const tone = (minor: number) => (minor > 0 ? "num pos" : minor < 0 ? "num neg" : "num muted");

function LedgerTable({ ledger }: { ledger: FriendLedger }) {
  if (ledger.rows.length === 0) return <p className="muted">Nothing with {ledger.name} yet.</p>;
  return (
    // The wrapper scrolls sideways on a phone instead of squeezing the columns.
    <div className="table-wrap">
      <table className="ledger">
        <thead>
          <tr>
            <th>Date</th>
            <th>What</th>
            <th>How</th>
            <th className="right">Change</th>
            <th className="right">Balance after</th>
          </tr>
        </thead>
        <tbody>
          {ledger.rows.map((r) => (
            <tr key={r.transaction_id} className={r.voided ? "voided" : undefined}>
              <td className="num">{r.occurred_on}</td>
              <td>
                {LABELS[r.template].label}
                {r.memo && <span className="muted"> · {r.memo}</span>}
                {r.voided && <span className="tag">void</span>}
              </td>
              <td>{r.method ? METHOD[r.method] : <span className="muted">—</span>}</td>
              <td className={`right ${r.voided ? "num" : tone(r.change.minor)}`}>
                {r.change.minor > 0 ? "+" : ""}
                {r.change.display}
              </td>
              <td className={`right ${tone(r.position_after.minor)}`}>
                {r.position_after.display}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted small">
        Balance after: + means they owe you, − means you owe them. A void stays listed but moves
        nothing.
      </p>
    </div>
  );
}

export function Friends(props: {
  book: Book;
  onAdd: (preset: Preset) => void;
}) {
  const { book } = props;
  const friends = book.summary.friends;
  // Start on someone you are not settled with, if there is anyone.
  const [picked, setPicked] = useState<string | null>(
    () => (friends.find((f) => f.position.minor !== 0) ?? friends[0])?.counterparty_id ?? null,
  );
  const [ledger, setLedger] = useState<FriendLedger | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Fetch the picked person's ledger, and again whenever the book reloads (after a new
  // transaction). `cancelled` stops a slow older answer from replacing a newer one.
  useEffect(() => {
    if (!picked) return;
    let cancelled = false;
    loadFriendLedger(picked)
      .then((l) => !cancelled && (setLedger(l), setError(null)))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [picked, book]);

  const person = friends.find((f) => f.counterparty_id === picked);

  return (
    <>
      <div className="section-head">
        <h1>Friends</h1>
        <button className="link" onClick={() => props.onAdd({ template: "lend", person: "new" })}>
          + Add person
        </button>
      </div>
      {friends.length === 0 && <p className="muted">Nobody yet. Lend or borrow to add a person.</p>}

      <div className="friends-layout">
        <nav className="people glass" aria-label="People">
          {friends.map((f) => (
            <button
              key={f.counterparty_id}
              className={f.counterparty_id === picked ? "person-row on" : "person-row"}
              aria-current={f.counterparty_id === picked ? "true" : undefined}
              onClick={() => setPicked(f.counterparty_id)}
            >
              <span className="avatar">{f.name.slice(0, 1)}</span>
              <span className="person-name">{f.name}</span>
              <span className={`small ${tone(f.position.minor)}`}>
                {standing(f.position.minor, f.amount.display)}
              </span>
            </button>
          ))}
        </nav>

        {person && (
          <section className="panel glass person">
            <header className="person-head">
              <span className="avatar large">{person.name.slice(0, 1)}</span>
              <div>
                <h2>{person.name}</h2>
                <span className={tone(person.position.minor)}>
                  {standing(person.position.minor, person.amount.display)}
                </span>
              </div>
              <div className="actions">
                {ACTIONS.map((a) => (
                  <button
                    key={a.template}
                    className="pill"
                    onClick={() =>
                      props.onAdd({ template: a.template, person: person.counterparty_id })
                    }
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            </header>
            {error && <p className="form-error">{error}</p>}
            {ledger?.counterparty_id === picked ? (
              <LedgerTable ledger={ledger} />
            ) : (
              !error && <p className="muted">Loading…</p>
            )}
          </section>
        )}
      </div>
    </>
  );
}
