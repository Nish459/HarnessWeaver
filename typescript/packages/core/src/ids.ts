/** Identifiers for runs, approvals and other framework objects. */

import { randomUUID } from "node:crypto";

/** A new random identifier such as `run_3f2a...`; the prefix makes it self-describing. */
export function newId(prefix: string): string {
  return `${prefix}_${randomUUID().replaceAll("-", "")}`;
}
