// Tauri 后端命令的类型化封装 + 事件监听
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export interface SystemInfo {
  cpu_count: number;
  mem_gb: number | null;
  tier_name: string;
}

export interface EnvStatus {
  wsl: boolean;
  openfoam: boolean;
  distro: string | null;
}

export interface History {
  iters: number[];
  u: number[];
  p: number[];
  cd: number[];
  cl: number[];
}

export interface Results {
  cd: number;
  cd_f: number;
  cd_r: number;
  cl: number;
  iterations: number;
  converged: boolean;
  frontal_area?: number;
  tier?: string;
  history?: History;
}

export type PipelineEvent =
  | { event: "step"; name: string; status: string; detail?: string }
  | {
      event: "residuals";
      iter: number;
      u: number;
      p: number;
      cd: number | null;
      cl: number | null;
    }
  | { event: "done"; results: Omit<Results, "history"> }
  | { event: "error"; message: string };

export const api = {
  systemInfo: () => invoke<SystemInfo>("system_info"),
  detectEnv: () => invoke<EnvStatus>("detect_environment"),
  startRun: (modelPath: string, velocity: number, scale: number) =>
    invoke<string>("start_run", { modelPath, velocity, scale }),
  cancelRun: () => invoke<boolean>("cancel_run"),
  getResults: (runId: string) => invoke<Results>("get_results", { runId }),
  getArtifact: (runId: string, name: string) =>
    invoke<string>("get_artifact", { runId, name }),
  onLog: (cb: (line: string) => void) =>
    listen<string>("run-log", (e) => cb(e.payload)),
  onExit: (cb: (code: number | null) => void) =>
    listen<number | null>("run-exit", (e) => cb(e.payload)),
};

/** Rust 端 stdout 每行是一个 JSON 事件；非 JSON 行（脚本输出）返回 null。 */
export function parseEvent(line: string): PipelineEvent | null {
  try {
    const v = JSON.parse(line);
    return typeof v?.event === "string" ? (v as PipelineEvent) : null;
  } catch {
    return null;
  }
}

export function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
