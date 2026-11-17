// The shell: navigation, the four screens, and the two sheets for adding things.
import { useCallback, useEffect, useState } from "react";

import { Activity, type Filter } from "./Activity";
import { AddAccount } from "./AddAccount";
import { AddTransaction, type Preset } from "./AddTransaction";
import { type Book, loadBook, post } from "./api";
import { Friends } from "./Friends";
import { Overview } from "./Overview";
import { Settings } from "./Settings";

type Tab = "overview" | "activity" | "friends" | "settings";
const TABS: { id: Tab; label: string; glyph: string }[] = [
  { id: "overview", label: "Overview", glyph: "◎" },
  { id: "activity", label: "Activity", glyph: "≡" },
  { id: "friends", label: "Friends", glyph: "☺" },
  { id: "settings", label: "Settings", glyph: "⚙" },
];

export function App() {
  // useState gives a component memory. Calling the setter redraws the component.
  const [tab, setTab] = useState<Tab>("overview");
  const [book, setBook] = useState<Book | null>(null);
  const [error, setError] = useState<string | null>(null);
  // null means the sheet is closed; an object (even empty) means open, maybe pre-filled.
  const [adding, setAdding] = useState<Preset | null>(null);
  const [addingAccount, setAddingAccount] = useState(false);
  const [filter, setFilter] = useState<Filter>(null);

  // Every figure comes from the server, so after any change the whole book is fetched again
  // rather than patched up here. useCallback keeps `reload` the same function between redraws.
  const reload = useCallback(() => {
    loadBook()
      .then((b) => {
        setBook(b);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  // An effect with [reload] as its dependency list runs once, when the app first appears.
  useEffect(reload, [reload]);

  const voidTxn = async (id: string) => {
    if (!window.confirm("Void this transaction? It stays in history but a void cannot be undone."))
      return;
    try {
      await post(`/transactions/${id}/void`);
    } catch (e) {
      window.alert((e as Error).message);
    }
    reload();
  };

  return (
    <div className="app">
      <nav className="nav glass">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          Parity
        </div>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={tab === t.id ? "nav-item active" : "nav-item"}
            aria-current={tab === t.id ? "page" : undefined}
            onClick={() => setTab(t.id)}
          >
            <span className="nav-glyph" aria-hidden="true">
              {t.glyph}
            </span>
            {t.label}
          </button>
        ))}
      </nav>

      <main className="main">
        {error && (
          <div className="banner glass">
            {error} <button onClick={reload}>Retry</button>
          </div>
        )}
        {!book && !error && <p className="muted">Loading…</p>}
        {book && tab === "overview" && (
          <Overview
            book={book}
            onAddAccount={() => setAddingAccount(true)}
            onShow={(f) => {
              setFilter(f);
              setTab("activity");
            }}
          />
        )}
        {book && tab === "activity" && (
          <>
            <h1>Activity</h1>
            <Activity
              rows={book.transactions}
              today={book.summary.as_of}
              onVoid={voidTxn}
              summary={book.summary}
              filter={filter}
              setFilter={setFilter}
            />
          </>
        )}
        {book && tab === "friends" && <Friends book={book} onAdd={setAdding} onVoid={voidTxn} />}
        {book && tab === "settings" && <Settings book={book} onChanged={reload} />}
      </main>

      {book && (
        <button className="fab" onClick={() => setAdding({})} aria-label="Add transaction">
          +
        </button>
      )}
      {book && adding && (
        <AddTransaction
          book={book}
          preset={adding}
          onClose={() => setAdding(null)}
          onDone={() => {
            setAdding(null);
            reload();
          }}
        />
      )}
      {book && addingAccount && (
        <AddAccount
          today={book.summary.as_of}
          onClose={() => setAddingAccount(false)}
          onDone={() => {
            setAddingAccount(false);
            reload();
          }}
        />
      )}
    </div>
  );
}
