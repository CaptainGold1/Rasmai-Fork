const trim = (value: string | undefined, fallback = "") => (value ?? fallback).trim().replace(/\/+$/, "");

/** Runtime configuration, read from the environment on every call so the standalone server picks up .env as deployed. */
export const env = {
  publicUrl: () => trim(process.env.MAIMAI_PUBLIC_URL, "https://rasmai.lol"),
  internalUrl: () => trim(process.env.MAIMAI_INTERNAL_URL, "http://127.0.0.1:8765"),
  internalSecret: () => (process.env.RASMAI_INTERNAL_SECRET ?? "").trim(),
  discordClientId: () => (process.env.DISCORD_CLIENT_ID ?? "").trim(),
  discordClientSecret: () => (process.env.DISCORD_CLIENT_SECRET ?? "").trim(),
  botInvite: () => (process.env.DISCORD_BOT_INVITE ?? "").trim(),
  turnstileSiteKey: () => (process.env.CF_KEY ?? "").trim(),
  turnstileSecret: () => (process.env.CF_SECRET ?? "").trim(),
};

export const oauthReady = () => Boolean(env.discordClientId() && env.discordClientSecret());
export const turnstileReady = () => Boolean(env.turnstileSiteKey() && env.turnstileSecret());
export const isSecure = () => env.publicUrl().startsWith("https://");
