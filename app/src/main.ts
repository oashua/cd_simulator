// 视图路由：setup -> import -> run -> results
import { api, type SystemInfo } from "./api";
import { showSetup } from "./views/setup";
import { showImport } from "./views/import";
import { showRun } from "./views/run";
import { showResults } from "./views/results";

const root = document.getElementById("app")!;

async function boot(): Promise<void> {
  root.innerHTML = `<div class="loading">启动中…</div>`;
  let env;
  try {
    env = await api.detectEnv();
  } catch (e) {
    root.innerHTML = `<div class="error">环境检测失败：${String(e)}</div>`;
    return;
  }
  if (!env.wsl || !env.openfoam) {
    showSetup(root, env, () => void boot());
    return;
  }
  let info: SystemInfo;
  try {
    info = await api.systemInfo();
  } catch {
    info = { cpu_count: 8, mem_gb: null, tier_name: "mid" };
  }
  showImport(root, info, (modelPath, velocity, scale) => {
    void (async () => {
      root.innerHTML = `<div class="loading">正在提交计算任务…</div>`;
      try {
        const runId = await api.startRun(modelPath, velocity, scale);
        showRun(
          root,
          runId,
          () => showResults(root, runId, () => void boot()),
          () => void boot()
        );
      } catch (e) {
        root.innerHTML = `<div class="error">启动失败：${String(e)}</div><button onclick="location.reload()">返回</button>`;
      }
    })();
  });
}

void boot();
