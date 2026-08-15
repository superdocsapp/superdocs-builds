import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import ts from "typescript";

export function loadSource<T extends Record<string, unknown>>(fileName: string, functions: string[]): T {
  const sourcePath = resolve(process.cwd(), "src", fileName);
  const source = readFileSync(sourcePath, "utf8");
  const javascript = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None }
  }).outputText;
  return new Function(`${javascript}\nreturn { ${functions.join(", ")} };`)() as T;
}
