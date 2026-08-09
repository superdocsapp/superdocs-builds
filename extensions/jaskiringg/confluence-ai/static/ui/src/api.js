import { invoke } from "@forge/bridge";

export async function call(action, payload) {
  return invoke(action, payload || {});
}
