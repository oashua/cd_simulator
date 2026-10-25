// 计算监控视图：残差曲线 + 日志尾窗 + 取消
import { api, parseEvent } from "../api";
import { ResidualChart, type ChartPoint } from "../chart";

export function showRun(
  root: HTMLElement,
  runId: string,
  onDone: () => void,
  onFail: (message: string) => void
): void {
  root.innerHTML = `
    <div class="run">
      <aside class="panel">
        <h1>计算中</h1>
        <div class="muted">run: ${runId}</div>
        <div id="phase" class="phase">准备中…</div>
        <div id="cd-live" class="big">Cd —</div>
        <button id="cancel">取消计算</button>
        <div id="fail" class="error"></div>
      </aside>
      <div class="stage run-stage">
        <canvas id="chart"></canvas>
        <pre id="log"></pre>
      </div>
    </div>`;

  const chart = new ResidualChart(root.querySelector<HTMLCanvasElement>("#chart")!);
  const logEl = root.querySelector<HTMLPreElement>("#log")!;
  const phaseEl = root.querySelector<HTMLElement>("#phase")!;
  const cdEl = root.querySelector<HTMLElement>("#cd-live")!;
  let done = false;
  let errorMsg = "";

  const unlog = api.onLog((line) => {
    logEl.textContent = (logEl.textContent + "\n" + line).split("\n").slice(-200).join("\n");
    logEl.scrollTop = logEl.scrollHeight;
    const evt = parseEvent(line);
    if (!evt) return;
    if (evt.event === "step") {
      const zh: Record<string, string> = {
        geometry: "几何预处理", mesh: "网格生成", solve: "流场求解", post: "后处理",
      };
      phaseEl.textContent = `${zh[evt.name] ?? evt.name}：${evt.status}${evt.detail ? ` (${evt.detail})` : ""}`;
    } else if (evt.event === "residuals" && evt.cd != null) {
      const p: ChartPoint = { iter: evt.iter, u: evt.u, p: evt.p, cd: evt.cd };
      chart.push(p);
      cdEl.textContent = `Cd ${evt.cd.toFixed(4)}`;
    } else if (evt.event === "error") {
      errorMsg = evt.message;
    }
  });

  const unexit = api.onExit((code) => {
    if (done) return;
    if (code === 0) {
      done = true;
      onDone();
    } else {
      root.querySelector<HTMLElement>("#fail")!.textContent =
        errorMsg || `计算进程异常退出 (exit ${code})`;
    }
  });

  root.querySelector("#cancel")!.addEventListener("click", async () => {
    done = true;
    await api.cancelRun();
    onFail("已取消");
  });

  // 离开视图时解绑监听
  const observer = new MutationObserver(() => {
    if (!root.isConnected || !document.body.contains(root.querySelector(".run")!)) {
      unlog.then((f) => f());
      unexit.then((f) => f());
      observer.disconnect();
    }
  });
  observer.observe(root, { childList: true });
}
