// 结果视图：Cd 数值 + 表面压力/流线/切片三个 tab + 精度声明 + 报告导出
import { api, base64ToBytes, type Results } from "../api";
import { createViewer, type Viewer } from "../viewer";

const DISCLAIMER =
  "精度说明：车轮不转、地面静止、网格自适应（未人工调优）条件下，" +
  "Cd 绝对值预期偏差 ±0.01–0.03；不同配置之间的趋势对比更可信。";

export function showResults(
  root: HTMLElement,
  runId: string,
  onBack: () => void
): void {
  root.innerHTML = `<div class="results"><aside class="panel"><h1>计算结果</h1><div class="muted">加载中…</div></aside><div class="stage" id="stage"></div></div>`;
  const stage = root.querySelector<HTMLElement>("#stage")!;
  const panel = root.querySelector<HTMLElement>(".panel")!;

  void (async () => {
    let results: Results;
    try {
      results = await api.getResults(runId);
    } catch (e) {
      panel.innerHTML = `<div class="error">结果读取失败：${String(e)}</div><button id="back">返回</button>`;
      panel.querySelector("#back")!.addEventListener("click", onBack);
      return;
    }

    panel.innerHTML = `
      <h1>计算结果</h1>
      <div class="big" id="cd">${results.cd.toFixed(4)}</div>
      <div class="muted">风阻系数 Cd ${results.converged ? "· 已收敛" : "· <b>未充分收敛</b>"}</div>
      <table class="kv">
        <tr><td>升阻比 Cl</td><td>${fmt(results.cl)}</td></tr>
        <tr><td>压差阻力 Cd(f)</td><td>${fmt(results.cd_f)}</td></tr>
        <tr><td>粘性阻力 Cd(r)</td><td>${fmt(results.cd_r)}</td></tr>
        <tr><td>迎风面积</td><td>${results.frontal_area ? results.frontal_area.toFixed(3) + " m²" : "—"}</td></tr>
        <tr><td>迭代步数</td><td>${results.iterations}</td></tr>
        <tr><td>网格档位</td><td>${results.tier ?? "—"}</td></tr>
      </table>
      <div class="tabs">
        <button data-tab="surface" class="active">表面压力</button>
        <button data-tab="streamlines">流线</button>
        <button data-tab="slice">切片</button>
      </div>
      <div class="disclaimer">${DISCLAIMER}</div>
      <button id="report">导出报告</button>
      <button id="back">返回首页</button>
    `;
    panel.querySelector("#back")!.addEventListener("click", onBack);
    panel.querySelector("#report")!.addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(results, null, 2)], {
        type: "application/json",
      });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `windtunnel_report_${runId}.json`;
      a.click();
      URL.revokeObjectURL(a.href);
    });

    const viewer: Viewer = createViewer(stage);
    const tab = async (name: string) => {
      viewer.clearResult();
      if (name === "surface") {
        const b64 = await api.getArtifact(runId, "surface.glb");
        await viewer.showSurfaceGlb(base64ToBytes(b64).buffer as ArrayBuffer);
      } else if (name === "streamlines") {
        const b64 = await api.getArtifact(runId, "streamlines.json");
        viewer.showStreamlines(JSON.parse(new TextDecoder().decode(base64ToBytes(b64))));
      } else {
        const b64 = await api.getArtifact(runId, "slice.json");
        viewer.showSlice(JSON.parse(new TextDecoder().decode(base64ToBytes(b64))));
      }
    };

    for (const btn of panel.querySelectorAll<HTMLButtonElement>(".tabs button")) {
      btn.addEventListener("click", () => {
        panel.querySelectorAll(".tabs button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        void tab(btn.dataset.tab!).catch((e) => alert(String(e)));
      });
    }
    await tab("surface").catch((e) => alert(String(e)));
  })();
}

function fmt(v: number): string {
  return Number.isFinite(v) ? v.toFixed(4) : "—";
}
