// 首次运行环境安装向导（MVP：引导式手动安装）
import type { EnvStatus } from "../api";

const SETUP_SCRIPT = String.raw`# 在 Windows 终端执行（管理员 PowerShell）：
wsl --install -d Ubuntu --no-launch
# 重启电脑后，打开 Ubuntu 完成初始用户配置，然后：

# 在 WSL Ubuntu 内执行：
sudo wget -qO /etc/apt/trusted.gpg.d/openfoam.gpg https://dl.openfoam.com/pubkey.gpg
echo "deb https://dl.openfoam.com/repos/deb $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/openfoam.list
sudo apt-get update
sudo apt-get install -y openfoam2312-default libopenmpi-dev openmpi-bin python3-pip
pip3 install --user --break-system-packages numpy trimesh meshio pymeshfix networkx

# 将随应用分发的 solver/ 目录复制到 WSL：
mkdir -p ~/cd_simulator && cp -r /mnt/c/path/to/solver ~/cd_simulator/solver`;

export function showSetup(
  root: HTMLElement,
  env: EnvStatus,
  onRecheck: () => void
): void {
  root.innerHTML = "";
  const div = document.createElement("div");
  div.className = "setup";
  div.innerHTML = `
    <h1>环境安装</h1>
    <p>计算后端需要 WSL2 与 OpenFOAM。当前状态：</p>
    <ul>
      <li>WSL2：${env.wsl ? "✅ 已安装" : "❌ 未安装"}</li>
      <li>OpenFOAM v2312：${env.openfoam ? "✅ 已安装" : "❌ 未安装"}</li>
      ${env.distro ? `<li>发行版：${env.distro}</li>` : ""}
    </ul>
    <p>请按以下步骤安装（需要管理员权限与一次重启）：</p>
    <pre>${SETUP_SCRIPT}</pre>
    <button id="recheck">重新检测</button>
  `;
  root.appendChild(div);
  div.querySelector("#recheck")!.addEventListener("click", onRecheck);
}
