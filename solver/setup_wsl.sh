#!/bin/bash
# cd_simulator WSL 环境安装脚本（在 WSL Ubuntu 内以可 sudo 的普通用户运行）
# 用法: bash setup_wsl.sh
set -euo pipefail

echo "[1/4] 安装 ESI OpenFOAM v2312 官方 apt 源..."
sudo sh -c 'wget -qO - https://dl.openfoam.com/gpg.key > /etc/apt/trusted.gpg.d/openfoam.asc'
sudo add-apt-repository -y http://dl.openfoam.com/ubuntu/latest
sudo apt-get update

echo "[2/4] 安装 OpenFOAM 与 MPI..."
sudo apt-get install -y openfoam2312-default libopenmpi-dev openmpi-bin

echo "[3/4] 安装 Python 依赖..."
sudo apt-get install -y python3-pip
pip3 install --user numpy trimesh meshio pymeshfix pytest

echo "[4/4] 部署求解管线到 ~/cd_simulator ..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/cd_simulator"
cp -r "$SCRIPT_DIR" "$HOME/cd_simulator/solver"
chmod +x "$HOME/cd_simulator/solver/templates/basecase/Allrun"

echo "完成。验证: bash -lc 'source /opt/openfoam2312/etc/bashrc && simpleFoam -help' "
