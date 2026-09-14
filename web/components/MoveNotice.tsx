"use client";

import { useEffect, useState } from "react";

const NEW_HOST = "rasmai.lol";
const KEY = "rasmai-move-notice";

/** Tells everyone still on the old address that the site is moving. Retires itself once they are on the new one. */
export function MoveNotice() {
  // assume hidden until the browser has been asked, so the band never flashes on a page that should not carry it
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (location.hostname === NEW_HOST || location.hostname.endsWith(`.${NEW_HOST}`)) return;
    try {
      if (localStorage.getItem(KEY) === "seen") return;
    } catch {
      /* private mode: the band shows each visit rather than never */
    }
    setShow(true);
  }, []);

  if (!show) return null;

  const dismiss = () => {
    try {
      localStorage.setItem(KEY, "seen");
    } catch {
      /* private mode: dismissed for this page only */
    }
    setShow(false);
  };

  return (
    <div className="movebar" role="status">
      <span className="movebar-lamp" aria-hidden="true" />
      <span className="movebar-text">
        Rasmai is moving to <b className="mono">{NEW_HOST}</b>. Your account and scores move with it, so there is nothing
        to re-link. This address keeps working until the switch.
      </span>
      <button type="button" className="movebar-close" onClick={dismiss} aria-label="Dismiss">
        ×
      </button>
    </div>
  );
}
