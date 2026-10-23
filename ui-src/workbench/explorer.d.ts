/* The explorer is plain JSX and two UMD modules (ui-src/explorer); the workbench mounts its graph. */
declare module "*/explorer/explorer.jsx" {
  import type { FC } from "react";
  export const Explorer: FC<{ full: unknown; defaults: unknown; title?: string }>;
}
declare module "*/explorer/adapter.js" {
  const adapter: { toGraph(payload: unknown): unknown };
  export default adapter;
}
declare module "*/explorer/defaults.js" {
  const defaults: { fromVocabulary(vocabulary: unknown, override: unknown): unknown };
  export default defaults;
}
