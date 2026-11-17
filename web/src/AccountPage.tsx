// One account on its own page: what it holds, its details, and every transaction that touched it.
// It lives at #/account/<id>, so a tile can be opened in a new browser tab too (⌘-click).
import { type FormEvent, useState } from "react";

import { Activity } from "./Activity";
import type { Preset } from "./AddTransaction";
import { toMinor } from "./amount";
import { type Account, type Book, type Brand, post } from "./api";
import { CardArt, COLOURS, DESIGNS, MiniCard, NEUTRAL_CARD } from "./cards";
import { AccountMark, Field } from "./ui";

/** "Due today", "Due tomorrow", "Due in 4 days". Counting days is calendar work, not money. */
export function dueText(days: number): string {
  if (days === 0) return "Due today";
  if (days === 1) return "Due tomorrow";
  return `Due in ${days} days`;
}

/** Edit what the user knows about the account. Only changed fields are sent; what is saved
 * stays until it is changed here again. */
function Details(props: {
  account: Account;
  banks: Account[]; // the banks that could pay this card off
  issuers: Brand[]; // banks the user can pick as the one that issued it
  onPreview: (design: string) => void; // the card at the top shows the design being picked
  onDone: () => void;
  onChanged: () => void;
}) {
  const { account } = props;
  const isCard = account.subtype === "credit_card";
  const credit = account.credit;
  const [name, setName] = useState(account.name);
  const [last4, setLast4] = useState(account.last4 ?? "");
  const [limit, setLimit] = useState("");
  const [due, setDue] = useState(credit?.due_day?.toString() ?? "");
  const [statement, setStatement] = useState(credit?.statement_day?.toString() ?? "");
  const [design, setDesign] = useState(credit?.design ?? "");
  const [paidFrom, setPaidFrom] = useState(credit?.linked_bank_id ?? "");
  const [issuer, setIssuer] = useState(account.brand?.key ?? "");
  const pickIssuer = (key: string) => {
    setIssuer(key);
    // A BofA card is most likely paid from a BofA account: suggest it if nothing is set yet.
    const same = props.banks.find((b) => b.brand?.key === key);
    if (isCard && !paidFrom && same) setPaidFrom(same.id);
  };
  // Picking a colour or a design shows it on the card at the top before it is saved.
  const pick = (value: string) => {
    setDesign(value);
    props.onPreview(value);
  };
  const [error, setError] = useState<string | null>(null);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    const body: Record<string, unknown> = {};
    if (name.trim() && name.trim() !== account.name) body.name = name;
    if (last4 && last4 !== account.last4) body.last4 = last4;
    if (issuer && issuer !== account.brand?.key) body.issuer = issuer;
    if (isCard) {
      if (limit.trim()) {
        const minor = toMinor(limit);
        if (minor === null) return setError("Enter the limit like 5000.00.");
        body.limit_minor = minor;
      }
      if (due && Number(due) !== credit?.due_day) body.due_day = Number(due);
      if (statement && Number(statement) !== credit?.statement_day)
        body.statement_day = Number(statement);
      if (design && design !== credit?.design) body.card_design = design;
      if (paidFrom && paidFrom !== credit?.linked_bank_id) body.linked_bank_id = paidFrom;
    }
    if (Object.keys(body).length === 0) return props.onDone();
    try {
      await post(`/accounts/${account.id}`, body);
      props.onChanged();
      props.onDone();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <form className="panel glass account-details" onSubmit={save}>
      <h2>Edit {account.name}</h2>
      <Field label="Name">
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </Field>
      {isCard && (
        <>
          <span className="muted small">Colour</span>
          <div className="colours" role="radiogroup" aria-label="Card colour">
            {COLOURS.map((c) => (
              <button
                type="button"
                key={c.color}
                role="radio"
                aria-checked={design === c.color}
                aria-label={c.name}
                title={c.name}
                className={design === c.color ? "colour-pick on" : "colour-pick"}
                style={{ background: c.color }}
                onClick={() => pick(c.color)}
              />
            ))}
            {/* Any colour at all: the browser's own colour picker, behind a rainbow swatch. */}
            <label
              className={
                design.startsWith("#") && !COLOURS.some((c) => c.color === design)
                  ? "colour-pick custom on"
                  : "colour-pick custom"
              }
              title="Any colour"
            >
              <input
                type="color"
                value={design.startsWith("#") ? design : NEUTRAL_CARD}
                onChange={(e) => pick(e.target.value)}
                aria-label="Any colour"
              />
            </label>
          </div>
          <span className="muted small">Design</span>
          <div className="designs" role="radiogroup" aria-label="Card design">
            {DESIGNS.map((d) => (
              <button
                type="button"
                key={d.key}
                role="radio"
                aria-checked={design === d.key}
                className={design === d.key ? "design-pick on" : "design-pick"}
                onClick={() => pick(d.key)}
              >
                <MiniCard design={d.key} />
                <span className="small">{d.name}</span>
              </button>
            ))}
          </div>
        </>
      )}
      <Field label="Issued by">
        <select value={issuer} onChange={(e) => pickIssuer(e.target.value)}>
          <option value="" disabled>
            Choose the bank…
          </option>
          {props.issuers.map((b) => (
            <option key={b.key} value={b.key}>
              {b.name}
            </option>
          ))}
        </select>
      </Field>
      <div className="pair">
        <Field label="Last 4 digits">
          <input
            className="num"
            inputMode="numeric"
            maxLength={4}
            pattern="[0-9]{4}"
            placeholder="0000"
            value={last4}
            // Strip anything but digits as it is typed; four is the most Parity will ever keep.
            onChange={(e) => setLast4(e.target.value.replace(/\D/g, "").slice(0, 4))}
            autoComplete="off"
          />
        </Field>
        {isCard && (
          <Field label="Credit limit">
            <input
              className="num"
              inputMode="decimal"
              placeholder={credit?.limit ? credit.limit.display : "5000.00"}
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
            />
          </Field>
        )}
      </div>
      {isCard && (
        <Field label="Paid off from">
          <select value={paidFrom} onChange={(e) => setPaidFrom(e.target.value)}>
            <option value="" disabled>
              Choose a bank account…
            </option>
            {props.banks.map((bank) => (
              <option key={bank.id} value={bank.id}>
                {bank.name}
              </option>
            ))}
          </select>
        </Field>
      )}
      {isCard && (
        <div className="pair">
          <Field label="Payment due day">
            <input
              type="number"
              min={1}
              max={31}
              placeholder="e.g. 21"
              value={due}
              onChange={(e) => setDue(e.target.value)}
            />
          </Field>
          <Field label="Statement closes day">
            <input
              type="number"
              min={1}
              max={31}
              placeholder="e.g. 28"
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
            />
          </Field>
        </div>
      )}
      <p className="muted small">
        Parity keeps only the last four digits. Never enter a full card number or security code.
      </p>
      {error && <p className="form-error">{error}</p>}
      <div className="form-actions">
        <button type="button" className="pill" onClick={props.onDone}>
          Cancel
        </button>
        <button className="primary">Save</button>
      </div>
    </form>
  );
}

export function AccountPage(props: {
  book: Book;
  id: string;
  onChanged: () => void;
  onVoid: (id: string) => void;
  onAdd: (preset: Preset) => void; // opens the add-transaction sheet, e.g. to pay this card
}) {
  const { book } = props;
  const account = book.accounts.find((a) => a.id === props.id);
  // The edit panel is closed until the ✎ button opens it. `preview` is the design being tried.
  const [editing, setEditing] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const close = () => {
    setEditing(false);
    setPreview(null);
  };
  if (!account) {
    return (
      <>
        <a className="back link" href="#">
          ‹ Back
        </a>
        <p className="muted">This account is not here.</p>
      </>
    );
  }
  // ponytail: filtered from the newest 200 transactions the app already loaded. Add an
  // ?account_id= filter to GET /transactions once one account has older history than that.
  const rows = book.transactions.filter((t) => t.legs.some((l) => l.account_id === account.id));
  const credit = account.credit;
  const isCard = account.subtype === "credit_card";

  return (
    <div className="account-page">
      <a className="back link" href="#">
        ‹ Back
      </a>
      <header className="account-head">
        <AccountMark account={account} />
        <h1>{account.name}</h1>
        {!account.is_active && <span className="tag">archived</span>}
      </header>

      <div className="account-top">
        {/* Cash has no number or due date, so it has nothing to edit. */}
        <div className="editable">
          {account.is_active && account.subtype !== "cash" && (
            <button
              className="corner-edit"
              onClick={() => (editing ? close() : setEditing(true))}
              aria-label={editing ? "Close editing" : `Edit ${account.name}`}
              aria-expanded={editing}
              title={editing ? "Close" : "Edit design and details"}
            >
              {editing ? "✕" : "✎"}
            </button>
          )}
          {isCard ? (
            <CardArt card={account} design={preview} />
          ) : (
            <section className="hero glass">
              <span className="eyebrow">{account.subtype === "cash" ? "Cash" : "Balance"}</span>
              <span className={account.balance.minor < 0 ? "num hero-num neg" : "num hero-num"}>
                {account.balance.display}
              </span>
              {account.last4 && <span className="muted small">Ending in {account.last4}</span>}
            </section>
          )}
        </div>
        {isCard && credit && (
          <section className="panel glass card-facts">
            <div>
              <span className="eyebrow">Owed</span>
              <span className="num big">{account.balance.display}</span>
            </div>
            {credit.limit ? (
              <>
                <div>
                  <span className="eyebrow">Left to spend</span>
                  <span className="num big">{credit.available?.display}</span>
                  <span className="muted small">
                    of {credit.limit.display} · {credit.utilization_display} used
                  </span>
                </div>
                {/* utilization_bps comes from the server; /100 only turns it into a CSS %. */}
                <div className="bar">
                  <span
                    style={{ width: `${Math.min(credit.utilization_bps ?? 0, 10000) / 100}%` }}
                  />
                </div>
              </>
            ) : (
              <span className="muted small">No limit set. Add one with ✎.</span>
            )}
            <div>
              <span className="eyebrow">Payment</span>
              {credit.next_due_on && credit.days_until_due != null ? (
                <span className={credit.days_until_due <= 3 ? "due soon" : "due"}>
                  {dueText(credit.days_until_due)} · {credit.next_due_on}
                </span>
              ) : (
                <span className="muted small">Add the due day with ✎ to get a reminder.</span>
              )}
              {credit.statement_day && (
                <span className="muted small">Statement closes on day {credit.statement_day}</span>
              )}
              <span className="muted small">
                {credit.linked_bank_name
                  ? `Paid off from ${credit.linked_bank_name}`
                  : "No bank set to pay it off. Add one with ✎."}
              </span>
            </div>
            {account.is_active && (
              <button
                className="primary"
                onClick={() =>
                  props.onAdd({
                    template: "card_payment",
                    a: account.id,
                    b: credit.linked_bank_id ?? undefined,
                  })
                }
              >
                Pay card
              </button>
            )}
          </section>
        )}
      </div>

      {editing && (
        <Details
          key={account.id}
          account={account}
          banks={book.accounts.filter((a) => a.is_active && a.subtype === "bank")}
          issuers={book.issuers}
          onPreview={setPreview}
          onDone={close}
          onChanged={props.onChanged}
        />
      )}

      <h2>Transactions</h2>
      <Activity rows={rows} today={book.summary.as_of} onVoid={props.onVoid} />
    </div>
  );
}
