import { register } from "node:module";

let registered = false;

/** Import a real source module (`.ts`/`.tsx`) by path relative to `frontend/src/`, without extension. */
export async function importSrc(relativePath) {
  if (!registered) {
    register("./ts-hooks.mjs", import.meta.url);
    registered = true;
  }
  return import(new URL(`../../src/${relativePath}`, import.meta.url).href);
}
