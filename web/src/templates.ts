// The ten transaction templates (CLAUDE.md §4) as the add sheet shows them.
//
// This only decides which fields to show and which accounts to offer. The rules themselves live
// in the Python service, which rejects anything this table gets wrong.
import type { Subtype, Template } from "./api";

type AccountField = { key: string; label: string; subtypes: Subtype[] };

export type TemplateSpec = {
  id: Template;
  label: string;
  blurb: string;
  glyph: string;
  a: AccountField;
  b?: AccountField;
  category?: "expense" | "income";
  person?: boolean;
};

const CASH_BANK: Subtype[] = ["cash", "bank"];
const ANY: Subtype[] = ["cash", "bank", "credit_card"];

export const TEMPLATES: TemplateSpec[] = [
  {
    id: "spend",
    label: "Spend",
    blurb: "You bought something",
    glyph: "↗",
    a: { key: "funding_id", label: "Paid from", subtypes: ANY },
    category: "expense",
  },
  {
    id: "income",
    label: "Income",
    blurb: "Money came in",
    glyph: "↙",
    a: { key: "dest_id", label: "Into", subtypes: CASH_BANK },
    category: "income",
  },
  {
    id: "transfer",
    label: "Transfer",
    blurb: "Between your own accounts",
    glyph: "⇄",
    a: { key: "from_id", label: "From", subtypes: CASH_BANK },
    b: { key: "to_id", label: "To", subtypes: CASH_BANK },
  },
  {
    id: "card_payment",
    label: "Pay card",
    blurb: "Pay down a credit card",
    glyph: "▭",
    a: { key: "card_id", label: "Card", subtypes: ["credit_card"] },
    b: { key: "funding_id", label: "Paid from", subtypes: CASH_BANK },
  },
  {
    id: "refund",
    label: "Refund",
    blurb: "A purchase was returned",
    glyph: "↩",
    a: { key: "funding_id", label: "Refunded to", subtypes: ANY },
    category: "expense",
  },
  {
    id: "lend",
    label: "Lend",
    blurb: "You paid for a friend",
    glyph: "→",
    a: { key: "funding_id", label: "Paid from", subtypes: ANY },
    person: true,
  },
  {
    id: "friend_repay",
    label: "They repaid",
    blurb: "A friend paid you back",
    glyph: "←",
    a: { key: "funding_id", label: "Into", subtypes: CASH_BANK },
    person: true,
  },
  {
    id: "borrow",
    label: "Borrow",
    blurb: "A friend gave you money",
    glyph: "⇠",
    a: { key: "dest_id", label: "Into", subtypes: CASH_BANK },
    person: true,
  },
  {
    id: "repay_friend",
    label: "Repay",
    blurb: "You paid a friend back",
    glyph: "⇢",
    a: { key: "funding_id", label: "Paid from", subtypes: CASH_BANK },
    person: true,
  },
];

export const LABELS: Record<Template, { label: string; glyph: string }> = {
  ...(Object.fromEntries(TEMPLATES.map((t) => [t.id, t])) as Record<
    Exclude<Template, "opening">,
    TemplateSpec
  >),
  opening: { label: "Opening balance", glyph: "◆" },
};
