// Drawn credit cards. Each card can wear one of these designs, so that at a glance (here, and as
// a small swatch on every Activity row it paid for) you know which card it is (D-072).
import type { CSSProperties } from "react";

import type { Account } from "./api";
import { inkOn } from "./theme";
import { BrandTile } from "./ui";

/** The designs, in picker order. Keys match CARD_DESIGNS in backend/app/services/ledger.py;
 * each one is drawn by a `.design-<key>` rule in styles.css. */
export const DESIGNS: { key: string; name: string }[] = [
  { key: "midnight", name: "Midnight" },
  { key: "aurora", name: "Aurora" },
  { key: "sunset", name: "Sunset" },
  { key: "waves", name: "Waves" },
  { key: "topo", name: "Topo" },
  { key: "prism", name: "Prism" },
  { key: "terrazzo", name: "Terrazzo" },
  { key: "carbon", name: "Carbon" },
  { key: "marble", name: "Marble" },
  { key: "ocean", name: "Ocean" },
  { key: "grid", name: "Grid" },
  { key: "blossom", name: "Blossom" },
];

/** Plain colours, for a simple card. Any other colour can be picked with the custom swatch. */
export const COLOURS: { color: string; name: string }[] = [
  { color: "#111214", name: "Black" },
  { color: "#1c2133", name: "Navy" },
  { color: "#1565a8", name: "Blue" },
  { color: "#2f5d50", name: "Green" },
  { color: "#9aa3ad", name: "Silver" },
  { color: "#b08d57", name: "Gold" },
  { color: "#b76e79", name: "Rose" },
  { color: "#8e2b2b", name: "Red" },
];

export const NEUTRAL_CARD = "#2a3350";

/** A design is a drawn one ("aurora") or a plain colour ("#1565a8"). Class and style for it. */
function look(design: string): { className: string; style?: CSSProperties } {
  if (!design.startsWith("#")) return { className: `design-${design}` };
  // A plain colour gets a gentle darker corner and text that stays readable on it.
  return {
    className: "design-solid",
    style: { "--card": design, "--card-ink": inkOn(design) } as CSSProperties,
  };
}

/**
 * A picture of the card: its design (or the bank's colour until one is picked), the issuer's
 * logo, a chip and the last four digits. `design` overrides the saved one, for a live preview.
 * ponytail: drawn designs, not the issuer's real card art, which is copyrighted with no
 * licensed source (D-070).
 */
export function CardArt({ card, design }: { card: Account; design?: string | null }) {
  // Without a design, the card is the bank's colour.
  const { className, style } = look(
    design ?? card.credit?.design ?? card.brand?.color ?? NEUTRAL_CARD,
  );
  return (
    <div
      className={`card-art ${className}`}
      style={style}
      role="img"
      aria-label={`${card.name}${card.last4 ? ` ending in ${card.last4}` : ""}`}
    >
      <div className="card-art-top">
        <BrandTile
          brand={card.brand}
          fallback={<span className="card-art-name">{card.name}</span>}
        />
        <span className="card-chip" aria-hidden="true" />
      </div>
      <span className="card-art-number num">•••• •••• •••• {card.last4 ?? "····"}</span>
      <div className="card-art-foot">
        <span>{card.name}</span>
        {card.credit?.due_day && <span>Due day {card.credit.due_day}</span>}
      </div>
    </div>
  );
}

/** A thumbnail of a card's design: on Activity rows, Overview tiles and the design picker. */
export function MiniCard({ design, title }: { design: string; title?: string }) {
  const { className, style } = look(design);
  return (
    <span className={`mini-card ${className}`} style={style} title={title} aria-hidden="true" />
  );
}
