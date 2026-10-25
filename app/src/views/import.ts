// 模型导入与参数设置视图
import { open } from "@tauri-apps/plugin-dialog";
import type { SystemInfo } from "../api";
import { createViewer, loadModelFile, type Viewer } from "../viewer";

export function showImport(
  root: HTMLElement,
  info: SystemInfo,
  onStart: (modelPath: string, velocity: number, scale: number) => void
): void {
  root.innerHTML = "";
  root.innerHTML = `
    <div class="import">
      <aside class="panel">
        <h1>汽车风洞仿真</h1>
        <label>模型文件 (STL/OBJ)</label>
        <div class="dropzone" id="dropzone">拖入模型预览，或</div>
        <button id="pick">选择文件</button>
        <div id="model-info" class="muted">未选择文件</div>

        <label>来流风速 (m/s)</label>
        <input id="velocity" type="number" value="33.3" min="1" max="80" step="0.1" />
        <label>模型缩放 (模型单位/米)</label>
        <input id="scale" type="number" value="1" min="0.001" step="0.001" />

        <div class="muted" id="machine"></div>
        <div class="muted">
          网格档位与预计时长：low ≈ 20 分钟 / mid ≈ 1–2 小时 / high ≈ 3–6 小时
        </div>
        <button id="start" class="primary" disabled>开始计算</button>
      </aside>
      <div class="stage" id="stage"></div>
    </div>`;

  let modelPath: string | null = null;
  let viewer: Viewer | null = null;
  const stage = root.querySelector<HTMLElement>("#stage")!;

  root.querySelector("#machine")!.textContent =
    `本机：${info.cpu_count} 核 / ${info.mem_gb ?? "?"} GB · 推荐档位 ${info.tier_name}`;

  const updateStart = () => {
    (root.querySelector("#start") as HTMLButtonElement).disabled = !modelPath;
  };

  const previewFile = async (file: File) => {
    viewer ??= createViewer(stage);
    const obj = await loadModelFile(file);
    viewer.showModelObject(obj);
  };

  const dz = root.querySelector<HTMLElement>("#dropzone")!;
  dz.addEventListener("dragover", (e) => e.preventDefault());
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    const file = e.dataTransfer?.files?.[0];
    if (file) previewFile(file).catch((err) => alert(String(err)));
  });

  root.querySelector("#pick")!.addEventListener("click", async () => {
    const path = await open({
      multiple: false,
      filters: [{ name: "3D 模型", extensions: ["stl", "obj"] }],
    });
    if (typeof path === "string") {
      modelPath = path;
      root.querySelector("#model-info")!.textContent = path.split(/[\\/]/).pop()!;
      updateStart();
    }
  });

  root.querySelector("#start")!.addEventListener("click", () => {
    const velocity = Number((root.querySelector("#velocity") as HTMLInputElement).value);
    const scale = Number((root.querySelector("#scale") as HTMLInputElement).value);
    if (!modelPath || !Number.isFinite(velocity) || velocity <= 0) return;
    onStart(modelPath, velocity, Number.isFinite(scale) && scale > 0 ? scale : 1);
  });
}
