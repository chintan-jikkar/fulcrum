// One card per person: where you stand, quick actions, and the history behind the number.
import { Activity } from "./Activity";
import type { Preset } from "./AddTransaction";
import type { Book, Template } from "./api";

const ACTIONS: { template: Template; label: string }[] = [
  { template: "lend", label: "Lend" },
  { template: "friend_repay", label: "They repaid" },
  { template: "borrow", label: "Borrow" },
  { template: "repay_friend", label: "Repay" },
];

export function Friends(props: {
  book: Book;
  onAdd: (preset: Preset) => void;
  onVoid: (id: string) => void;
}) {
  const { book } = props;
  return (
    <>
      <div className="section-head">
        <h1>Friends</h1>
        <button className="link" onClick={() => props.onAdd({ template: "lend", person: "new" })}>
          + Add person
        </button>
      </div>
      {book.summary.friends.length === 0 && (
        <p className="muted">Nobody yet. Lend or borrow to add a person.</p>
      )}
      {book.summary.friends.map((f) => {
        // A person's history is every transaction with a leg on one of their two accounts.
        const theirs = new Set(
          book.accounts.filter((a) => a.counterparty_id === f.counterparty_id).map((a) => a.id),
        );
        const history = book.transactions.filter((t) =>
          t.legs.some((l) => theirs.has(l.account_id)),
        );
        return (
          <section key={f.counterparty_id} className="panel glass person">
            <header className="person-head">
              <span className="avatar large">{f.name.slice(0, 1)}</span>
              <div>
                <h2>{f.name}</h2>
                <span
                  className={
                    f.position.minor > 0 ? "num pos" : f.position.minor < 0 ? "num neg" : "muted"
                  }
                >
                  {f.position.minor > 0 && `owes you ${f.amount.display}`}
                  {f.position.minor < 0 && `you owe ${f.amount.display}`}
                  {f.position.minor === 0 && "settled up"}
                </span>
              </div>
              <div className="actions">
                {ACTIONS.map((a) => (
                  <button
                    key={a.template}
                    className="pill"
                    onClick={() =>
                      props.onAdd({
                        template: a.template,
                        person: f.counterparty_id,
                      })
                    }
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            </header>
            <Activity rows={history} today={book.summary.as_of} onVoid={props.onVoid} />
          </section>
        );
      })}
    </>
  );
}
