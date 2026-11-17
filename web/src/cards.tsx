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

const NEUTRAL_CARD = "#2a3350";

/**
 * A picture of the card: its design (or the bank's colour until one is picked), the issuer's
 * logo, a chip and the last four digits. `design` overrides the saved one, for a live preview.
 * ponytail: drawn designs, not the issuer's real card art, which is copyrighted with no
 * licensed source (D-070).
 */
export function CardArt({ card, design }: { card: Account; design?: string | null }) {
  const picked = design ?? card.credit?.design;
  const fill = card.brand?.color ?? NEUTRAL_CARD;
  return (
    <div
      className={picked ? `card-art design-${picked}` : "card-art"}
      // Without a design, the card is the bank's colour with text that stays readable on it.
      style={picked ? undefined : ({ "--card": fill, "--card-ink": inkOn(fill) } as CSSProperties)}
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
  return <span className={`mini-card design-${design}`} title={title} aria-hidden="true" />;
}
