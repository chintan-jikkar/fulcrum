// Add an account and, in the same step, its opening balance (CLAUDE.md §4: `opening`).
import { type FormEvent, useState } from "react";

import { toMinor } from "./amount";
import { type Account, type Brand, post } from "./api";
import { Field, Sheet } from "./ui";

export type Kind = "bank" | "cash" | "credit_card";

export function AddAccount(props: {
  today: string;
  kind: Kind; // what the sheet opens as; "+ Add card" opens it as a credit card
  banks: Account[]; // the user's bank accounts, one of which can pay a new card off
  issuers: Brand[]; // banks to pick as the issuer when the name does not say it
  onClose: () => void;
  onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>(props.kind);
  // The bank that pays the card off (D-075). The only bank is picked for you.
  const [paidFrom, setPaidFrom] = useState(props.banks.length === 1 ? props.banks[0]!.id : "");
  const [dueDay, setDueDay] = useState("");
  const [issuer, setIssuer] = useState("");
  const pickIssuer = (key: string) => {
    setIssuer(key);
    // A card is most likely paid from an account at the same bank: suggest it if one exists.
    const same = props.banks.find((b) => b.brand?.key === key);
    if (same) setPaidFrom(same.id);
  };
  const [balance, setBalance] = useState("");
  const [limit, setLimit] = useState("");
  const [date, setDate] = useState(props.today);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Once the account exists, a failed opening balance must not create the account again.
  const [created, setCreated] = useState<string | null>(null);

  const isCard = kind === "credit_card";

  const save = async (event: FormEvent) => {
    event.preventDefault();
    const opening = balance.trim() ? toMinor(balance) : 0;
    const limitMinor = isCard && limit.trim() ? toMinor(limit) : undefined;
    if (opening === null || limitMinor === null) return setError("Enter amounts like 1500.00.");
    setSaving(true);
    setError(null);
    try {
      let id = created;
      if (!id) {
        const body = {
          name,
          subtype: kind,
          ...(limitMinor && { limit_minor: limitMinor }),
          ...(isCard && paidFrom && { linked_bank_id: paidFrom }),
          ...(kind !== "cash" && issuer && { issuer }),
          ...(isCard && dueDay && { due_day: Number(dueDay) }),
        };
        id = (await post<Account>("/accounts", body)).id;
        setCreated(id);
      }
      if (opening > 0) {
        // For a card the opening amount is what is owed; the service turns it the right way.
        await post("/transactions/opening", {
          account_id: id,
          amount_minor: opening,
          occurred_on: date,
        });
      }
      props.onDone();
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  };

  return (
    <Sheet title={isCard ? "Add credit card" : "Add account"} onClose={props.onClose}>
      <form onSubmit={save} className="form">
        <Field label="Type">
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as Kind)}
            disabled={!!created}
          >
            <option value="bank">Bank account</option>
            <option value="cash">Cash</option>
            <option value="credit_card">Credit card</option>
          </select>
        </Field>
        <Field label="Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={isCard ? "Juniper Card" : "Harbor Checking"}
            disabled={!!created}
            required
            autoFocus
          />
        </Field>
        {kind !== "cash" && (
          <Field label="Issued by">
            <select
              value={issuer}
              onChange={(e) => pickIssuer(e.target.value)}
              disabled={!!created}
            >
              <option value="">From the name, or none</option>
              {props.issuers.map((b) => (
                <option key={b.key} value={b.key}>
                  {b.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <div className="pair">
          <Field label={isCard ? "Owed today" : "Balance today"}>
            <input
              className="num"
              inputMode="decimal"
              placeholder="0.00"
              value={balance}
              onChange={(e) => setBalance(e.target.value)}
            />
          </Field>
          <Field label="As of">
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
          </Field>
        </div>
        {isCard && (
          <div className="pair">
            <Field label="Paid from">
              <select
                value={paidFrom}
                onChange={(e) => setPaidFrom(e.target.value)}
                disabled={!!created}
              >
                <option value="">Not set</option>
                {props.banks.map((bank) => (
                  <option key={bank.id} value={bank.id}>
                    {bank.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Payment due day">
              <input
                type="number"
                min={1}
                max={31}
                placeholder="e.g. 21"
                value={dueDay}
                onChange={(e) => setDueDay(e.target.value)}
                disabled={!!created}
              />
            </Field>
          </div>
        )}
        {isCard && (
          <Field label="Credit limit">
            <input
              className="num"
              inputMode="decimal"
              placeholder="Optional"
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              disabled={!!created}
            />
          </Field>
        )}
        {error && <p className="form-error">{error}</p>}
        <button className="primary" disabled={saving}>
          {saving ? "Saving…" : isCard ? "Add card" : "Add account"}
        </button>
      </form>
    </Sheet>
  );
}
