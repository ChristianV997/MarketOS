/**
 * Test-only ESM loader: transpiles the feature's .ts/.tsx with the repo's own
 * `typescript` devDependency so node:test can render the real components with
 * react-dom/server. Adds no dependency and no test framework. Source imports use
 * explicit extensions (allowImportingTsExtensions), so no resolver is needed.
 */
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import ts from "typescript";

export async function load(url, context, nextLoad) {
  if (url.startsWith("file:") && /\.tsx?$/.test(url) && !url.includes("/node_modules/")) {
    const source = await readFile(fileURLToPath(url), "utf8");
    const { outputText } = ts.transpileModule(source, {
      fileName: fileURLToPath(url),
      compilerOptions: {
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2020,
        jsx: ts.JsxEmit.ReactJSX,
        isolatedModules: true,
      },
    });
    return { format: "module", source: outputText, shortCircuit: true };
  }
  return nextLoad(url, context);
}
