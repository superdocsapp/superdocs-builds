import { diyEngine } from "./diy/diyEngine";
import { superdocsEngine } from "./superdocs/superdocsEngine";
import type { EditingEngine, EngineId } from "./types";

const engines: Record<EngineId, EditingEngine> = {
  diy: diyEngine,
  superdocs: superdocsEngine,
};

export function getEditingEngine(id: EngineId): EditingEngine {
  return engines[id];
}

export { superdocsEngine };
export * from "./types";