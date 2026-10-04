/**
 * Test-only Node module hooks: run the real `.ts`/`.tsx` sources under
 * `node --test` without adding a dependency.
 *
 * - resolves the extensionless relative imports and the `@/` alias the app uses;
 * - transpiles TS/TSX with the repo's own `typescript` devDependency
 *   (`ts.transpileModule`, automatic JSX runtime). No type checking here:
 *   `npm run typecheck` owns that.
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const SRC_ROOT = fileURLToPath(new URL("../../src/", import.meta.url));
const CANDIDATE_SUFFIXES = [".ts", ".tsx", "/index.ts", "/index.tsx"];

function isFile(candidate) {
  try {
    return statSync(candidate).isFile();
  } catch {
    return false;
  }
}

function toAbsolutePath(specifier, parentURL) {
  if (specifier.startsWith("file:")) return fileURLToPath(specifier);
  if (specifier.startsWith("@/")) return path.join(SRC_ROOT, specifier.slice(2));
  if ((specifier.startsWith("./") || specifier.startsWith("../")) && parentURL?.startsWith("file:")) {
    return fileURLToPath(new URL(specifier, parentURL));
  }
  return null;
}

export async function resolve(specifier, context, nextResolve) {
  const absolute = toAbsolutePath(specifier, context.parentURL);
  if (absolute) {
    if (isFile(absolute) && /\.(tsx?|mjs|js|json)$/.test(absolute)) {
      return { url: pathToFileURL(absolute).href, shortCircuit: true };
    }
    for (const suffix of CANDIDATE_SUFFIXES) {
      if (isFile(absolute + suffix)) {
        return { url: pathToFileURL(absolute + suffix).href, shortCircuit: true };
      }
    }
  }
  return nextResolve(specifier, context);
}

export async function load(url, context, nextLoad) {
  if (url.startsWith("file:") && /\.tsx?$/.test(url)) {
    const filename = fileURLToPath(url);
    if (!existsSync(filename)) return nextLoad(url, context);
    const { outputText } = ts.transpileModule(readFileSync(filename, "utf8"), {
      fileName: filename,
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ESNext,
        jsx: ts.JsxEmit.ReactJSX,
        isolatedModules: true,
        sourceMap: false,
      },
    });
    // Node has no Vite `import.meta.env`. Route `import.meta` through a global a test can set
    // (globalThis.__IMPORT_META__ = { env: { VITE_API_BASE_URL: "..." } }) so code reading the
    // API-origin authority can actually be exercised instead of always seeing "".
    const source = outputText.replace(/\bimport\.meta\b/g, "(globalThis.__IMPORT_META__ ?? {})");
    return { format: "module", source, shortCircuit: true };
  }
  return nextLoad(url, context);
}
