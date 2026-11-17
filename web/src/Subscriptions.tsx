// Subscriptions and other recurring charges (D-079). A rule only reminds: from a couple of days
// before the date it shows in "Due soon" on the Overview, where you say it was paid (that writes
// the spend), skip this one, or stop tracking it if you cancelled it with the company.
import { type FormEvent, useState } from "react";

import { toMinor } from "./amount";
import { type Book, post, type Rule } from "./api";
import { pickable } from "./Categories";
import { BrandTile, Field, Sheet } from "./ui";

const CADENCES = [
  ["monthly", "Every month"],
  ["yearly", "Every year"],
  ["weekly", "Every week"],
] as const;

/** "due today", "due tomorrow", "due in 3 days", "3 days overdue". Calendar words, no money. */
export function ruleDue(days: number): string {
  if (days < 0) return `${-days} day${days === -1 ? "" : "s"} overdue`;
  if (days === 0) return "due today";
  if (days === 1) return "due tomorrow";
  return `due in ${days} days`;
}

/** Add a subscription, or edit one (`rule` given). */
export function RuleSheet(props: {
  book: Book;
  rule?: Rule;
  onClose: () => void;
  onDone: () => void;
}) {
  const { book, rule } = props;
  const [name, setName] = useState(rule?.name ?? "");
  const [amount, setAmount] = useState("");
  const [funding, setFunding] = useState(rule?.funding_id ?? "");
  const subs = book.categories.find((c) => c.name === "Subscriptions" && c.kind === "expense");
  const [category, setCategory] = useState(rule?.category_id ?? subs?.id ?? "");
  const [cadence, setCadence] = useState<string>(rule?.cadence ?? "monthly");
  const [due, setDue] = useState(rule?.next_due_on ?? "");
  const [remind, setRemind] = useState(String(rule?.remind_days ?? 2));
  const [error, setError] = useState<string | null>(null);

  const accounts = book.accounts.filter(
    (a) => a.is_active && ["cash", "bank", "credit_card"].includes(a.subtype),
  );
  const categories = pickable(book.categories, "expense");

  const run = async (path: string, body?: object) => {
    setError(null);
    try {
      await post(path, body);
      props.onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const save = (event: FormEvent) => {
    event.preventDefault();
    const minor = amount.trim() ? toMinor(amount) : undefined;
    if (minor === null) return setError("Enter the amount like 15.49.");
    if (!rule && minor === undefined) return setError("Enter the amount.");
    const body = {
      name,
      ...(minor !== undefined && { amount_minor: minor }),
      funding_id: funding,
      category_id: category,
      cadence,
      next_due_on: due,
      remind_days: Number(remind),
    };
    void run(rule ? `/recurring/${rule.id}` : "/recurring", body);
  };

  return (
    <Sheet title={rule ? `Edit ${rule.name}` : "Add subscription"} onClose={props.onClose}>
      <form className="form" onSubmit={save}>
        <Field label="Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Netflix, Claude Pro, Spotify…"
            required
            autoFocus
          />
        </Field>
        <div className="pair">
          <Field label="Amount">
            <input
              className="num"
              inputMode="decimal"
              placeholder={rule ? rule.amount.display : "15.49"}
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
          </Field>
          <Field label="How often">
            <select value={cadence} onChange={(e) => setCadence(e.target.value)}>
              {CADENCES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="pair">
          <Field label="Next charge on">
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} required />
          </Field>
          <Field label="Remind me">
            <select value={remind} onChange={(e) => setRemind(e.target.value)}>
              {[0, 1, 2, 3, 5, 7].map((d) => (
                <option key={d} value={d}>
                  {d === 0 ? "On the day" : `${d} day${d === 1 ? "" : "s"} before`}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="pair">
          <Field label="Charged to">
            <select value={funding} onChange={(e) => setFunding(e.target.value)} required>
              <option value="" disabled>
                Choose…
              </option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Category">
            <select value={category} onChange={(e) => setCategory(e.target.value)} required>
              <option value="" disabled>
                Choose…
              </option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        {error && <p className="form-error">{error}</p>}
        <div className="form-actions">
          {rule &&
            (rule.is_active ? (
              <button
                type="button"
                className="pill"
                onClick={() => void run(`/recurring/${rule.id}/cancel`)}
                title="Stops the reminders. Cancel it with the company too."
              >
                Stop tracking
              </button>
            ) : (
              <button
                type="button"
                className="pill"
                onClick={() => void run(`/recurring/${rule.id}/resume`)}
              >
                Resume
              </button>
            ))}
          <button className="primary">{rule ? "Save" : "Add"}</button>
        </div>
      </form>
    </Sheet>
  );
}

/** A reminder in "Due soon": paid (writes the spend), skip this one, or open it to cancel. */
export function RuleReminder(props: {
  rule: Rule;
  onChanged: () => void;
  onOpen: (rule: Rule) => void;
}) {
  const { rule } = props;
  const [busy, setBusy] = useState(false);
  const act = async (action: "confirm" | "skip") => {
    setBusy(true);
    try {
      await post(`/recurring/${rule.id}/${action}`);
      props.onChanged();
    } catch (e) {
      window.alert((e as Error).message);
      setBusy(false);
    }
  };
  return (
    <div className="due-item">
      <BrandTile
        brand={rule.brand}
        fallback={<span className="brand-tile monogram">{rule.name.slice(0, 1)}</span>}
      />
      <span>
        <strong>{rule.name}</strong>{" "}
        <span className="due soon">{ruleDue(rule.days_until_due)}</span>
        <span className="muted small"> · {rule.funding_name}</span>
      </span>
      <span className="num">{rule.amount.display}</span>
      <span className="actions">
        <button className="pill solid" disabled={busy} onClick={() => void act("confirm")}>
          Paid
        </button>
        <button className="pill" disabled={busy} onClick={() => void act("skip")}>
          Skip
        </button>
        <button className="pill" disabled={busy} onClick={() => props.onOpen(rule)}>
          Cancel it?
        </button>
      </span>
    </div>
  );
}

/** Every subscription, soonest first. A row opens it for editing or cancelling. */
export function SubscriptionsPanel(props: {
  rules: Rule[];
  onAdd: () => void;
  onOpen: (rule: Rule) => void;
}) {
  const active = props.rules.filter((r) => r.is_active);
  const stopped = props.rules.filter((r) => !r.is_active);
  return (
    <section className="panel glass">
      <div className="section-head panel-head">
        <h2>Subscriptions</h2>
        <button className="link" onClick={props.onAdd}>
          + Add
        </button>
      </div>
      {props.rules.length === 0 && (
        <p className="muted">Add Netflix, Claude and the rest to be reminded before each charge.</p>
      )}
      {[...active, ...stopped].map((r) => (
        <button key={r.id} className="merchant-row" onClick={() => props.onOpen(r)}>
          <BrandTile
            brand={r.brand}
            fallback={<span className="brand-tile monogram">{r.name.slice(0, 1)}</span>}
          />
          <span className="merchant-name">
            {r.name}
            <span className="muted small">
              {r.is_active ? `${r.next_due_on} · ${ruleDue(r.days_until_due)}` : "not tracked"}
            </span>
          </span>
          <span className={r.is_active ? "num" : "num muted"}>{r.amount.display}</span>
        </button>
      ))}
    </section>
  );
}
