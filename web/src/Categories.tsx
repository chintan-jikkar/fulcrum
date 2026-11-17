// Settings › Categories (D-080): add, rename, nest one level, archive and restore. The server
// enforces every rule (unique names per kind, one level, same kind as the parent); this page
// only shows its error message when it says no.
import { type FormEvent, useState } from "react";

import { type Category, post } from "./api";

type CatKind = Category["kind"];

/** The categories a transaction of `kind` can take, for a <select>: each parent followed by
 *  its subcategories, labelled "Food › Groceries". Archived ones are left out (I8). */
export function pickable(all: Category[], kind: CatKind): { id: string; label: string }[] {
  const live = all.filter((c) => c.kind === kind && !c.is_archived);
  return live
    .filter((c) => !c.parent_id)
    .flatMap((p) => [
      { id: p.id, label: p.name },
      ...live
        .filter((c) => c.parent_id === p.id)
        .map((c) => ({
          id: c.id,
          label: `${p.name} › ${c.name}`,
        })),
    ]);
}

/** Top-level categories of a kind that can take a subcategory (not archived, not `except`). */
const parents = (all: Category[], kind: CatKind, except?: string) =>
  all.filter((c) => c.kind === kind && !c.parent_id && !c.is_archived && c.id !== except);

function ParentPicker(props: {
  all: Category[];
  kind: CatKind;
  except?: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
      aria-label="Inside"
    >
      <option value="">Top level</option>
      {parents(props.all, props.kind, props.except).map((c) => (
        <option key={c.id} value={c.id}>
          Inside {c.name}
        </option>
      ))}
    </select>
  );
}

function CategoryRow(props: {
  cat: Category;
  all: Category[];
  childCount: number;
  onChanged: () => void;
}) {
  const { cat, all } = props;
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(cat.name);
  const [parent, setParent] = useState(cat.parent_id ?? "");
  const [error, setError] = useState<string | null>(null);

  const run = async (path: string, body?: object) => {
    setError(null);
    try {
      await post(path, body);
      setEditing(false);
      props.onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const save = (event: FormEvent) => {
    event.preventDefault();
    // Send only what changed. parent_id null means "back to the top level".
    const body: Record<string, unknown> = {};
    if (name.trim() !== cat.name) body.name = name;
    if (parent !== (cat.parent_id ?? "")) body.parent_id = parent || null;
    if (Object.keys(body).length === 0) return setEditing(false);
    void run(`/categories/${cat.id}`, body);
  };

  return (
    <div className={`acct-row${cat.is_archived ? " archived" : ""}${cat.parent_id ? " sub" : ""}`}>
      <div className="tile-body">
        <span className="tile-name">{cat.name}</span>
        <span className="muted small">
          {props.childCount > 0 &&
            `${props.childCount} subcategor${props.childCount === 1 ? "y" : "ies"}`}
          {cat.is_archived && "archived · kept on past transactions"}
        </span>
      </div>
      <div className="actions">
        {!cat.is_archived && !editing && (
          <button className="pill" onClick={() => setEditing(true)}>
            Edit
          </button>
        )}
        {cat.is_archived ? (
          <button className="pill" onClick={() => run(`/categories/${cat.id}/unarchive`)}>
            Restore
          </button>
        ) : (
          <button
            className="pill"
            onClick={() => run(`/categories/${cat.id}/archive`)}
            title="Can't be picked for new transactions; past ones keep it."
          >
            Archive
          </button>
        )}
      </div>
      {editing && (
        <form className="acct-edit" onSubmit={save}>
          <input value={name} onChange={(e) => setName(e.target.value)} aria-label="Name" />
          {/* A category with subcategories stays at the top: one level only. */}
          {props.childCount === 0 && (
            <ParentPicker
              all={all}
              kind={cat.kind}
              except={cat.id}
              value={parent}
              onChange={setParent}
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

function AddCategory({ all, onChanged }: { all: Category[]; onChanged: () => void }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<CatKind>("expense");
  const [parent, setParent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const add = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await post("/categories", { name, kind, parent_id: parent || null });
      setName("");
      setParent("");
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <form className="acct-edit add-category" onSubmit={add}>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="New category"
        aria-label="New category name"
        required
      />
      <select
        value={kind}
        onChange={(e) => {
          setKind(e.target.value as CatKind);
          setParent(""); // a parent must be the same kind
        }}
        aria-label="Kind"
      >
        <option value="expense">Spending</option>
        <option value="income">Income</option>
      </select>
      <ParentPicker all={all} kind={kind} value={parent} onChange={setParent} />
      <button className="pill solid">Add</button>
      {error && <p className="form-error">{error}</p>}
    </form>
  );
}

export function CategoriesPanel(props: { categories: Category[]; onChanged: () => void }) {
  const all = props.categories;
  // Each top-level category followed by its subcategories; archived ones last.
  const ordered = (kind: CatKind) =>
    all
      .filter((c) => c.kind === kind && !c.parent_id)
      .sort((a, b) => Number(a.is_archived) - Number(b.is_archived))
      .flatMap((p) => [p, ...all.filter((c) => c.parent_id === p.id)]);

  return (
    <>
      <section className="panel glass">
        <AddCategory all={all} onChanged={props.onChanged} />
      </section>
      {(["expense", "income"] as const).map((kind) => (
        <section key={kind} className="panel glass">
          <h2>{kind === "expense" ? "Spending" : "Income"}</h2>
          {ordered(kind).map((c) => (
            <CategoryRow
              key={c.id}
              cat={c}
              all={all}
              childCount={all.filter((x) => x.parent_id === c.id).length}
              onChanged={props.onChanged}
            />
          ))}
        </section>
      ))}
    </>
  );
}
