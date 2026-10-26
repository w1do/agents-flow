import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";

const require = createRequire(
  new URL("../../apps/console/package.json", import.meta.url),
);
const { compile } = require("json-schema-to-typescript");
const { format } = require("prettier");
let input = "";
for await (const chunk of process.stdin) input += chunk;
const schema = JSON.parse(input.replaceAll("#/$defs/", "#/definitions/"));
// json-schema-to-typescript consumes draft-07 definitions; Pydantic emits $defs.
schema.definitions = schema.$defs;
delete schema.$defs;
// Declare each canonical model once; no handwritten TS contracts or copied field lists.
const output = await compile(
  {
    ...schema,
    title: "Projects",
    type: "object",
    properties: {},
    additionalProperties: false,
  },
  "Projects",
  {
    unreachableDefinitions: true,
    ignoreMinAndMaxItems: true,
    bannerComment:
      "/* Generated from harness_shared.projects. Run pnpm types:generate; do not edit. */",
  },
);
const path = new URL("src/projects.ts", import.meta.url);
const formatted = await format(output, {
  parser: "typescript",
  printWidth: 90,
});
if (process.argv.includes("--check")) {
  if ((await readFile(path, "utf8")) !== formatted) {
    throw new Error("Project types are stale. Run pnpm types:generate.");
  }
} else {
  await mkdir(new URL("src/", import.meta.url), { recursive: true });
  await writeFile(path, formatted);
}
