import { register } from "node:module";

register("./ts-hooks.mjs", import.meta.url);

const FEATURE_ROOT = new URL("../../src/features/client-crm-profile/", import.meta.url);

/** Import a feature module by path relative to the feature directory (with extension). */
export const importFeature = (relative) => import(new URL(relative, FEATURE_ROOT).href);
export { FEATURE_ROOT };
