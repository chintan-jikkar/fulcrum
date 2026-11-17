// Settings: a short list (Profile, Accounts, Appearance); each row opens its own page.
import { type FormEvent, useState } from "react";

import { toMinor } from "./amount";
import type { Kind } from "./AddAccount";
import { type Account, type Book, post } from "./api";
import { loadMode, loadTheme, type Mode, PRESETS, saveMode, saveTheme, type Theme } from "./theme";
import { AccountMark, Field } from "./ui";

const KIND_LABEL: Record<string, string> = {
  cash: "Cash",
  bank: "Bank",
  credit_card: "Card",
};

// Every IANA zone the browser knows, for the timezone picker.
const ZONES: string[] = Intl.supportedValuesOf("timeZone");

function ProfilePanel({ book, onSaved }: { book: Book; onSaved: () => void }) {
  const [name, setName] = useState(book.profile.display_name);
  const [zone, setZone] = useState(book.profile.timezone);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setNote(null);
    try {
      await post("/me", { display_name: name, timezone: zone });
      setNote("Saved.");
      onSaved(); // "today" and this month can move with the timezone, so fetch everything again
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <form className="panel glass" onSubmit={save}>
      <Field label="Name">
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </Field>
      <Field label="Timezone (sets what “today” and “this month” mean)">
        <select value={zone} onChange={(e) => setZone(e.target.value)}>
          {ZONES.map((z) => (
            <option key={z}>{z}</option>
          ))}
        </select>
      </Field>
      {error && <p className="form-error">{error}</p>}
      {note && <span className="saved-note">{note}</span>}
      <button className="primary">Save profile</button>
    </form>
  );
}

function AccountRow({ account, onChanged }: { account: Account; onChanged: () => void }) {
  const isCard = account.subtype === "credit_card";
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(account.name);
  const [limit, setLimit] = useState("");
  const [error, setError] = useState<string | null>(null);

  const run = async (path: string, body?: object) => {
    setError(null);
    try {
      await post(path, body);
      setEditing(false);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const save = (event: FormEvent) => {
    event.preventDefault();
    const limitMinor = isCard && limit.trim() ? toMinor(limit) : undefined;
    if (limitMinor === null) return setError("Enter the limit like 5000.00.");
    const body: Record<string, unknown> = {};
    if (name.trim() !== account.name) body.name = name;
    if (limitMinor !== undefined) body.limit_minor = limitMinor;
    if (Object.keys(body).length === 0) return setEditing(false);
    void run(`/accounts/${account.id}`, body);
  };

  return (
    <div className={account.is_active ? "acct-row" : "acct-row archived"}>
      <AccountMark account={account} />
      <div className="tile-body">
        <a className="tile-name plain-link" href={`#/account/${account.id}`}>
          {account.name}
        </a>
        <span className="muted small">
          {KIND_LABEL[account.subtype]} · <span className="num">{account.balance.display}</span>
          {isCard && account.credit?.limit && ` · limit ${account.credit.limit.display}`}
          {!account.is_active && " · archived"}
        </span>
      </div>
      <div className="actions">
        {account.is_active && !editing && (
          <button className="pill" onClick={() => setEditing(true)}>
            Edit
          </button>
        )}
        {account.is_active ? (
          <button
            className="pill"
            onClick={() => run(`/accounts/${account.id}/archive`)}
            title="Hides the account. Only possible at a zero balance."
          >
            Archive
          </button>
        ) : (
          <button className="pill" onClick={() => run(`/accounts/${account.id}/unarchive`)}>
            Restore
          </button>
        )}
      </div>
      {editing && (
        <form className="acct-edit" onSubmit={save}>
          <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Name" />
          {isCard && (
            <input
              className="num"
              inputMode="decimal"
              placeholder={
                account.credit?.limit ? `Limit ${account.credit.limit.display}` : "Limit"
              }
              value={limit}
              onChange={(e) => setLimit(e.target.value)}
              aria-label="Credit limit"
            />
          )}
          <button className="pill solid">Save</button>
          <button type="button" className="pill" onClick={() => setEditing(false)}>
            Cancel
          </button>
        </form>
      )}
      {error && <p className="form-error acct-edit">{error}</p>}
    </div>
  );
}

const MODES: { id: Mode; label: string }[] = [
  { id: "system", label: "System" },
  { id: "light", label: "Light" },
  { id: "dark", label: "Dark" },
];

function presetName(t: Theme): string {
  return PRESETS.find((p) => p.theme.a === t.a && p.theme.b === t.b)?.name ?? "Custom";
}

function AppearancePanel() {
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [mode, setMode] = useState<Mode>(loadMode);

  const pick = (t: Theme) => {
    setTheme(t);
    saveTheme(t); // repaints at once and remembers it in this browser
  };
  const pickMode = (m: Mode) => {
    setMode(m);
    saveMode(m);
  };
  const same = (t: Theme) => t.a === theme.a && t.b === theme.b;

  return (
    <>
      <section className="panel glass">
        <h2>Mode</h2>
        <div className="segmented" role="radiogroup" aria-label="Light or dark">
          {MODES.map((m) => (
            <button
              key={m.id}
              role="radio"
              aria-checked={mode === m.id}
              className={mode === m.id ? "active" : ""}
              onClick={() => pickMode(m.id)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <p className="muted small" style={{ margin: 0 }}>
          System follows your device and switches with it.
        </p>
      </section>
      <section className="panel glass">
        <h2>Colours</h2>
        <p className="muted small" style={{ margin: 0 }}>
          Two colours tint the whole app. Pick a preset or mix your own. Saved on this device.
        </p>
        <div className="swatches">
          {PRESETS.map((p) => (
            <button
              key={p.name}
              className={same(p.theme) ? "swatch active" : "swatch"}
              onClick={() => pick(p.theme)}
              aria-pressed={same(p.theme)}
            >
              <span
                className="swatch-dot"
                style={{
                  background: `linear-gradient(135deg, ${p.theme.a} 50%, ${p.theme.b} 50%)`,
                }}
              />
              {p.name}
            </button>
          ))}
        </div>
        <div className="custom-colours">
          <Field label="Main colour">
            <input
              type="color"
              value={theme.a}
              onChange={(e) => pick({ ...theme, a: e.target.value })}
            />
          </Field>
          <Field label="Second colour">
            <input
              type="color"
              value={theme.b}
              onChange={(e) => pick({ ...theme, b: e.target.value })}
            />
          </Field>
          {presetName(theme) === "Custom" && <span className="muted small">Custom</span>}
        </div>
      </section>
    </>
  );
}

type Page = "profile" | "accounts" | "appearance";

export function Settings({
  book,
  onChanged,
  onAddAccount,
}: {
  book: Book;
  onChanged: () => void;
  onAddAccount: (kind: Kind) => void;
}) {
  // Which page is open; null is the list. Leaving the tab closes the page again.
  const [page, setPage] = useState<Page | null>(null);
  const mine = book.accounts.filter(
    (a) => a.subtype === "cash" || a.subtype === "bank" || a.subtype === "credit_card",
  );
  const active = mine.filter((a) => a.is_active).length;
  const modeLabel = MODES.find((m) => m.id === loadMode())?.label;

  const rows: { id: Page; title: string; detail: string; glyph: string }[] = [
    {
      id: "profile",
      title: "Profile",
      detail: `${book.profile.display_name} · ${book.profile.timezone}`,
      glyph: "☺",
    },
    {
      id: "accounts",
      title: "Accounts",
      detail: `${active} active${mine.length > active ? `, ${mine.length - active} archived` : ""}`,
      glyph: "▤",
    },
    {
      id: "appearance",
      title: "Appearance",
      detail: `${modeLabel} · ${presetName(loadTheme())}`,
      glyph: "◐",
    },
  ];

  if (!page) {
    return (
      <>
        <h1>Settings</h1>
        <nav className="settings-list glass" aria-label="Settings">
          {rows.map((r) => (
            <button key={r.id} className="settings-row" onClick={() => setPage(r.id)}>
              <span className="glyph" aria-hidden="true">
                {r.glyph}
              </span>
              <span className="row-main">
                <span className="row-title">{r.title}</span>
                <span className="muted small">{r.detail}</span>
              </span>
              <span className="chevron" aria-hidden="true">
                ›
              </span>
            </button>
          ))}
        </nav>
      </>
    );
  }

  const title = rows.find((r) => r.id === page)?.title;
  return (
    <>
      <button className="back link" onClick={() => setPage(null)}>
        ‹ Settings
      </button>
      <h1>{title}</h1>
      <div className="settings-page">
        {page === "profile" && <ProfilePanel book={book} onSaved={onChanged} />}
        {page === "accounts" && (
          <section className="panel glass">
            <div className="actions add-row">
              <button className="pill" onClick={() => onAddAccount("bank")}>
                + Bank or cash
              </button>
              <button className="pill" onClick={() => onAddAccount("credit_card")}>
                + Credit card
              </button>
            </div>
            {mine.length === 0 && <p className="muted">No accounts yet.</p>}
            <div>
              {mine.map((a) => (
                <AccountRow key={a.id} account={a} onChanged={onChanged} />
              ))}
            </div>
          </section>
        )}
        {page === "appearance" && <AppearancePanel />}
      </div>
    </>
  );
}
