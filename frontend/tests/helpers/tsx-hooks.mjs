/**
 * Node module hooks that let node:test import the app's .ts/.tsx sources.
 * Uses the repo's own `typescript` (no new dependency): strips types, compiles
 * JSX with the automatic runtime, resolves extensionless relative imports and
 * the `@/` alias from tsconfig. Test-only; never used by the app build.
 */
import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const SRC_DIR = fileURLToPath(new URL("../../src/", import.meta.url));
const SUFFIXES = [".tsx", ".ts", "/index.tsx", "/index.ts"];

export async function resolve(specifier, context, nextResolve) {
  let target = null;
  if (specifier.startsWith("@/")) {
    target = path.join(SRC_DIR, specifier.slice(2));
  } else if ((specifier.startsWith("./") || specifier.startsWith("../")) && context.parentURL?.startsWith("file:")) {
    target = fileURLToPath(new URL(specifier, context.parentURL));
  }
  if (target === null) return nextResolve(specifier, context);
  if (path.extname(target) && existsSync(target)) return nextResolve(pathToFileURL(target).href, context);
  for (const suffix of SUFFIXES) {
    if (existsSync(target + suffix)) return nextResolve(pathToFileURL(target + suffix).href, context);
  }
  return nextResolve(pathToFileURL(target).href, context);
}

export async function load(url, context, nextLoad) {
  if (url.startsWith("file:") && /\.tsx?$/.test(url) && !url.includes("/node_modules/")) {
    const filePath = fileURLToPath(url);
    const source = await readFile(filePath, "utf8");
    const { outputText } = ts.transpileModule(source, {
      fileName: filePath,
      compilerOptions: {
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
        isolatedModules: true,
      },
    });
    return { format: "module", source: outputText, shortCircuit: true };
  }
  return nextLoad(url, context);
}
