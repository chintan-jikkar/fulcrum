// Split a bill (D-078). You paid the whole bill; shared items are split by units ("12 cases of
// water: 2 for Tara, 3 for Avi, the rest mine") and everything else on the bill is yours.
// Review asks the server to work the shares out (no money math here, CLAUDE.md §6); Save
// writes your share as a spend and each friend's as a lend on the same account.
import { type FormEvent, useState } from "react";

import { toMinor } from "./amount";
import { type Book, type Person, post, type SplitOut } from "./api";
import { pickable } from "./Categories";
import { Field, Sheet } from "./ui";

/** One shared item as typed: its price, and how many units each person gets ("me" is you). */
type Item = { label: string; amount: string; units: Record<string, string> };

const blankItem = (): Item => ({ label: "", amount: "", units: { me: "" } });

export function SplitBill(props: { book: Book; onClose: () => void; onDone: () => void }) {
  const { book } = props;
  const [total, setTotal] = useState("");
  const [memo, setMemo] = useState("");
  const [date, setDate] = useState(book.summary.as_of);
  const [funding, setFunding] = useState("");
  const [category, setCategory] = useState("");
  // Who is in on this bill. New people get created on the spot.
  const [people, setPeople] = useState<Person[]>([]);
  const [newName, setNewName] = useState("");
  const [items, setItems] = useState<Item[]>([blankItem()]);
  const [review, setReview] = useState<SplitOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const accounts = book.accounts.filter(
    (a) => a.is_active && ["cash", "bank", "credit_card"].includes(a.subtype),
  );
  const categories = pickable(book.categories, "expense");
  const others = book.people.filter((p) => !people.some((q) => q.id === p.id));

  // Any change after a review makes it stale, so it is cleared and Review shows again.
  const changed =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v);
      setReview(null);
    };

  const addPerson = async (id: string) => {
    if (id === "new") return;
    const person = book.people.find((p) => p.id === id);
    if (person) changed(setPeople)([...people, person]);
  };

  const createPerson = async () => {
    if (!newName.trim()) return;
    try {
      const person = await post<Person>("/counterparties", { name: newName.trim() });
      changed(setPeople)([...people, person]);
      setNewName("");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const setItem = (i: number, patch: Partial<Item>) =>
    changed(setItems)(items.map((it, j) => (j === i ? { ...it, ...patch } : it)));

  /** The request body, or an error message if something typed is not a number. */
  const body = (): Record<string, unknown> | string => {
    const totalMinor = toMinor(total);
    if (totalMinor === null) return "Enter the bill total like 84.20.";
    const out = [];
    for (const it of items) {
      const amount = toMinor(it.amount);
      if (amount === null) return "Enter each item's price like 29.94.";
      const count = (key: string) => Number.parseInt(it.units[key] || "0", 10) || 0;
      out.push({
        amount_minor: amount,
        my_units: count("me"),
        units: people
          .filter((p) => count(p.id) > 0)
          .map((p) => ({ counterparty_id: p.id, units: count(p.id) })),
      });
    }
    return {
      amount_minor: totalMinor,
      occurred_on: date,
      memo,
      funding_id: funding,
      category_id: category,
      items: out,
    };
  };

  const send = async (preview: boolean) => {
    const b = body();
    if (typeof b === "string") return setError(b);
    setError(null);
    setSaving(true);
    try {
      const out = await post<SplitOut>("/transactions/split", { ...b, preview });
      if (preview) setReview(out);
      else props.onDone();
    } catch (e) {
      setError((e as Error).message);
    }
    setSaving(false);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void send(!review); // first press reviews, the second saves what was reviewed
  };

  return (
    <Sheet title="Split a bill" onClose={props.onClose}>
      <form className="form" onSubmit={submit}>
        <div className="pair">
          <Field label="Bill total">
            <input
              className="amount-input num"
              inputMode="decimal"
              placeholder="0.00"
              value={total}
              onChange={(e) => changed(setTotal)(e.target.value)}
              autoFocus
              required
            />
          </Field>
          <Field label="Date">
            <input
              type="date"
              value={date}
              onChange={(e) => changed(setDate)(e.target.value)}
              required
            />
          </Field>
        </div>
        <Field label="What">
          <input
            value={memo}
            onChange={(e) => changed(setMemo)(e.target.value)}
            placeholder="Walmart groceries"
          />
        </Field>
        <div className="pair">
          <Field label="Paid with">
            <select value={funding} onChange={(e) => changed(setFunding)(e.target.value)} required>
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
          <Field label="Your share is">
            <select
              value={category}
              onChange={(e) => changed(setCategory)(e.target.value)}
              required
            >
              <option value="" disabled>
                Category…
              </option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <span className="muted small">Split with</span>
        <div className="split-people">
          {people.map((p) => (
            <span key={p.id} className="pill solid">
              {p.name}
              <button
                type="button"
                className="chip-x"
                aria-label={`Remove ${p.name}`}
                onClick={() => changed(setPeople)(people.filter((q) => q.id !== p.id))}
              >
                ✕
              </button>
            </span>
          ))}
          {others.length > 0 && (
            <select value="" onChange={(e) => void addPerson(e.target.value)} aria-label="Add">
              <option value="">+ Add someone…</option>
              {others.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          <input
            className="new-person"
            placeholder="New name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void createPerson();
              }
            }}
          />
          <button type="button" className="pill" onClick={() => void createPerson()}>
            Add
          </button>
        </div>

        <span className="muted small">
          Shared items, split by units. Anything else on the bill is yours.
        </span>
        {items.map((it, i) => (
          <fieldset key={i} className="split-item">
            <div className="pair">
              <input
                placeholder="Item, e.g. Water ×12"
                value={it.label}
                onChange={(e) => setItem(i, { label: e.target.value })}
                aria-label="Item"
              />
              <input
                className="num"
                inputMode="decimal"
                placeholder="Price"
                value={it.amount}
                onChange={(e) => setItem(i, { amount: e.target.value })}
                aria-label="Item price"
                required
              />
            </div>
            <div className="units">
              {[{ id: "me", name: "Me" }, ...people].map((p) => (
                <label key={p.id} className="unit">
                  <span className="small">{p.name}</span>
                  <input
                    type="number"
                    min={0}
                    step={1}
                    placeholder="0"
                    value={it.units[p.id] ?? ""}
                    onChange={(e) => setItem(i, { units: { ...it.units, [p.id]: e.target.value } })}
                  />
                </label>
              ))}
            </div>
            {items.length > 1 && (
              <button
                type="button"
                className="link small"
                onClick={() => changed(setItems)(items.filter((_, j) => j !== i))}
              >
                Remove item
              </button>
            )}
          </fieldset>
        ))}
        <button
          type="button"
          className="pill"
          onClick={() => changed(setItems)([...items, blankItem()])}
        >
          + Another item
        </button>

        {review && (
          <section className="split-review" aria-live="polite">
            <div className="split-line">
              <span>You</span>
              <span className="num">{review.mine.display}</span>
            </div>
            {review.shares.map((s) => (
              <div key={s.counterparty_id} className="split-line">
                <span>{s.name} owes you</span>
                <span className="num pos">{s.amount.display}</span>
              </div>
            ))}
            <p className="muted small">
              Friends' shares are rounded down to the cent; you keep the odd cents.
            </p>
          </section>
        )}
        {error && <p className="form-error">{error}</p>}
        <button className="primary" disabled={saving || people.length === 0}>
          {saving ? "Working…" : review ? "Save split" : "Review split"}
        </button>
      </form>
    </Sheet>
  );
}
