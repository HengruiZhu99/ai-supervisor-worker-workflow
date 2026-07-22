import type { Snapshot } from "./types";

const token =
  document.querySelector<HTMLMetaElement>('meta[name="aiflow-token"]')
    ?.content ?? "";

export async function readSnapshot(): Promise<Snapshot> {
  const response = await fetch("/api/v1/snapshot", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`Snapshot failed (${response.status})`);
  return response.json() as Promise<Snapshot>;
}

export async function post<T>(path: string, payload: object): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-AIFLOW-Token": token },
    body: JSON.stringify(payload),
  });
  const result = (await response.json()) as T & { error?: string };
  if (!response.ok)
    throw new Error(result.error ?? `Request failed (${response.status})`);
  return result;
}
