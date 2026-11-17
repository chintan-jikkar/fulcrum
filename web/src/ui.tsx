// Small shared pieces: the modal sheet and a labelled form field.
import { type CSSProperties, type ReactNode, useEffect, useState } from "react";

import { BASE, type Brand } from "./api";
import { inkOn, useIsDark } from "./theme";

/** A sheet over the page. Closes on Escape or ✕, not on a stray click outside: that would
 * throw away a half-typed form. */
export function Sheet(props: { title: string; onClose: () => void; children: ReactNode }) {
  // useEffect runs after the component appears. The function it returns runs when the
  // component goes away, which is where the key listener is removed again.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && props.onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [props.onClose]);

  return (
    <div className="backdrop">
      <div className="sheet glass" role="dialog" aria-modal="true" aria-label={props.title}>
        <header className="sheet-head">
          <h2>{props.title}</h2>
          <button className="icon-btn" onClick={props.onClose} aria-label="Close">
            ✕
          </button>
        </header>
        {props.children}
      </div>
    </div>
  );
}

export function Field(props: { label: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{props.label}</span>
      {props.children}
    </label>
  );
}

/**
 * A brand's logo, served by our own API (D-067), on a square in the brand's colour with its
 * short mark ("TJ", "N"). The coloured square shows at once and stays if there is no logo;
 * the logo covers it once loaded. `fallback` is drawn when the API recognised no brand.
 */
export function BrandTile(props: { brand: Brand | null; fallback: ReactNode; title?: string }) {
  // Remembers, per tile, whether the logo image arrived. False until it does.
  const [loaded, setLoaded] = useState(false);
  const dark = useIsDark();
  const { brand } = props;
  if (!brand) return <>{props.fallback}</>;
  return (
    <span
      className={loaded ? "brand-tile has-logo" : "brand-tile"}
      // The colour goes in a CSS variable so the stylesheet can swap it for a neutral
      // background once the logo is showing.
      style={{ "--brand": brand.color, color: inkOn(brand.color) } as CSSProperties}
      title={props.title ?? brand.name}
      aria-hidden="true"
    >
      {!loaded && brand.mark}
      <img
        // The dark version is lightened for dark backgrounds. Changing src loads the other file.
        src={`${BASE}/brands/${brand.key}/logo${dark ? "?theme=dark" : ""}`}
        alt=""
        loading="lazy"
        onLoad={() => setLoaded(true)}
        // A 404 (no logo, or no Logo.dev key on the server) leaves the coloured square.
        onError={() => setLoaded(false)}
      />
    </span>
  );
}
