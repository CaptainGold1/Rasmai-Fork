"use client";

import { useState } from "react";

type Platform = "desktop" | "ios";

// bump when a recording is replaced: browsers hold on to a video far longer than a page
const CUT = 2;

const CLIPS: Record<Platform, { label: string; src: string; poster: string; note: string; chrome: string; w: number; h: number }> = {
  desktop: {
    label: "On a computer",
    src: "/walkthrough/desktop.mp4",
    poster: "/walkthrough/desktop.jpg",
    note: "Chrome, Edge or Firefox. The bookmark trick works the same in all three.",
    chrome: "maimaidx-eng.com",
    w: 1280,
    h: 720,
  },
  ios: {
    label: "On iPhone",
    src: "/walkthrough/ios-safari.mp4",
    poster: "/walkthrough/ios-safari.jpg",
    note: "Safari on iOS. Android is the same idea in Chrome.",
    chrome: "maimaidx-eng.com",
    w: 560,
    h: 1214,
  },
};

/** The linking walkthrough as a screen recording, framed like the device it was taken on. */
export function Walkthrough() {
  const [platform, setPlatform] = useState<Platform>("desktop");
  const clip = CLIPS[platform];
  const video = (
    <video
      key={clip.src}
      src={`${clip.src}?v=${CUT}`}
      poster={`${clip.poster}?v=${CUT}`}
      width={clip.w}
      height={clip.h}
      controls
      playsInline
      muted
      loop
      preload="none"
      aria-label={`${clip.label}: the whole linking process, start to finish`}
    />
  );
  return (
    <div className="walkthrough">
      <div className="walk-tabs" role="tablist" aria-label="which device you are linking on">
        {(Object.keys(CLIPS) as Platform[]).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={platform === key}
            className={platform === key ? "on" : ""}
            onClick={() => setPlatform(key)}
          >
            {CLIPS[key].label}
          </button>
        ))}
      </div>

      <div className="walk-stage">
        {platform === "desktop" ? (
          <div className="walk-browser">
            <div className="walk-chrome" aria-hidden="true">
              <span className="walk-dots">
                <i />
                <i />
                <i />
              </span>
              <span className="walk-url">{clip.chrome}</span>
            </div>
            {video}
          </div>
        ) : (
          <div className="walk-phone">
            <span className="walk-notch" aria-hidden="true" />
            {video}
          </div>
        )}
        <p className="walk-note">
          <b>{clip.label}</b>
          {clip.note}
        </p>
      </div>
    </div>
  );
}
