// The add sheet: pick what happened, fill in the few fields that template needs, save.
import { type FormEvent, useState } from "react";

import { toMinor } from "./amount";
import { type Book, type Person, type Template, post } from "./api";
import { TEMPLATES } from "./templates";
import { Field, Sheet } from "./ui";

/** What the sheet opens with. `person: "new"` opens it ready to name a new person. */
export type Preset = { template?: Template; person?: string };

const METHODS = [
  ["", "Not recorded"],
  ["cash", "Cash"],
  ["bank_transfer", "Bank transfer (Zelle etc.)"],
  ["card", "Card"],
  ["other", "Other"],
] as const;

export function AddTransaction(props: {
  book: Book;
  preset: Preset;
  onClose: () => void;
  onDone: () => void;
}) {
  const { book } = props;
  const [templateId, setTemplateId] = useState<Template>(props.preset.template ?? "spend");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(book.summary.as_of); // the server's "today" for this user
  const [memo, setMemo] = useState("");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [category, setCategory] = useState("");
  const [person, setPerson] = useState(props.preset.person ?? "");
  const [newPerson, setNewPerson] = useState("");
  const [method, setMethod] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const spec = TEMPLATES.find((t) => t.id === templateId)!;
  const accountsFor = (subtypes: string[]) =>
    book.accounts.filter((acct) => acct.is_active && subtypes.includes(acct.subtype));
  const categories = book.categories.filter((c) => c.kind === spec.category && !c.is_archived);

  const choose = (id: Template) => {
    setTemplateId(id);
    // The account and category lists differ per template, so earlier picks are cleared.
    setA("");
    setB("");
    setCategory("");
    setError(null);
  };

  const save = async (event: FormEvent) => {
    event.preventDefault(); // stop the browser's own form submit, which would reload the page
    const amountMinor = toMinor(amount);
    if (amountMinor === null) return setError("Enter an amount like 12.50.");
    setSaving(true);
    setError(null);
    try {
      let personId = person;
      if (spec.person && person === "new") {
        personId = (await post<Person>("/counterparties", { name: newPerson })).id;
        setPerson(personId); // if the next step fails, a retry must not create them again
      }
      // The field names match the Python request models; the server rejects anything extra.
      await post(`/transactions/${spec.id}`, {
        amount_minor: amountMinor,
        occurred_on: date,
        memo,
        [spec.a.key]: a,
        ...(spec.b && { [spec.b.key]: b }),
        ...(spec.category && { category_id: category }),
        ...(spec.person && { counterparty_id: personId }),
        ...(method && { method }),
      });
      props.onDone();
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  return (
    <Sheet title="Add transaction" onClose={props.onClose}>
      <div className="template-grid">
        {TEMPLATES.map((t) => (
          <button
            key={t.id}
            type="button"
            className={t.id === templateId ? "template active" : "template"}
            onClick={() => choose(t.id)}
          >
            <span className={`glyph t-${t.id}`} aria-hidden="true">
              {t.glyph}
            </span>
            {t.label}
          </button>
        ))}
      </div>
      <p className="muted small">{spec.blurb}</p>

      <form onSubmit={save} className="form">
        <Field label="Amount">
          <input
            className="amount-input num"
            inputMode="decimal"
            placeholder="0.00"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            autoFocus
            required
          />
        </Field>

        {spec.person && (
          <Field label="Person">
            <select value={person} onChange={(e) => setPerson(e.target.value)} required>
              <option value="" disabled>
                Choose…
              </option>
              {book.people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
              <option value="new">+ New person…</option>
            </select>
          </Field>
        )}
        {spec.person && person === "new" && (
          <Field label="Their name">
            <input value={newPerson} onChange={(e) => setNewPerson(e.target.value)} required />
          </Field>
        )}

        <Field label={spec.a.label}>
          <select value={a} onChange={(e) => setA(e.target.value)} required>
            <option value="" disabled>
              Choose…
            </option>
            {accountsFor(spec.a.subtypes).map((acct) => (
              <option key={acct.id} value={acct.id}>
                {acct.name} · {acct.balance.display}
              </option>
            ))}
          </select>
        </Field>
        {spec.b && (
          <Field label={spec.b.label}>
            <select value={b} onChange={(e) => setB(e.target.value)} required>
              <option value="" disabled>
                Choose…
              </option>
              {accountsFor(spec.b.subtypes).map((acct) => (
                <option key={acct.id} value={acct.id}>
                  {acct.name} · {acct.balance.display}
                </option>
              ))}
            </select>
          </Field>
        )}

        {spec.category && (
          <Field label="Category">
            <select value={category} onChange={(e) => setCategory(e.target.value)} required>
              <option value="" disabled>
                Choose…
              </option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
        )}

        <div className="pair">
          <Field label="Date">
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
          <Field label="How">
            <select value={method} onChange={(e) => setMethod(e.target.value)}>
              {METHODS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Note">
          <input value={memo} onChange={(e) => setMemo(e.target.value)} placeholder="Optional" />
        </Field>

        {error && <p className="form-error">{error}</p>}
        <button className="primary" disabled={saving}>
          {saving ? "Saving…" : `Save ${spec.label.toLowerCase()}`}
        </button>
      </form>
    </Sheet>
  );
}
