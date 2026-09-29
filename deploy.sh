#!/usr/bin/env bash
# ============================================================
# 日本二手平台上新监控系统 - 服务器一键部署脚本
# 适用：Ubuntu/Debian/CentOS 系 VPS（香港/海外服务器均可）
# 用法：bash deploy.sh
# ============================================================
set -e

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info(){ echo -e "${GREEN}[INFO]${NC} $1"; }
warn(){ echo -e "${YELLOW}[WARN]${NC} $1"; }
err(){ echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ---------- 1. 检查 root / sudo ----------
if [ "$(id -u)" -ne 0 ]; then
  if command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
  else
    err "请用 root 运行（或先 sudo -i）"
  fi
else
  SUDO=""
fi

# ---------- 2. 安装目录 ----------
INSTALL_DIR="${1:-/opt/monitor}"
info "安装目录：$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

# ---------- 3. 检测 Docker ----------
HAVE_DOCKER=0
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  HAVE_DOCKER=1
  info "检测到 Docker，使用容器方式部署"
fi

if [ "$HAVE_DOCKER" -eq 0 ]; then
  warn "未检测到 Docker，将尝试自动安装..."
  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y
    $SUDO apt-get install -y ca-certificates curl
    curl -fsSL https://get.docker.com | $SUDO sh
  elif command -v yum >/dev/null 2>&1; then
    $SUDO yum install -y yum-utils
    $SUDO yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    $SUDO yum install -y docker-ce docker-ce-cli containerd.io
  else
    warn "无法自动安装 Docker，改用 Python 方式部署"
    HAVE_DOCKER=0
  fi
  if command -v docker >/dev/null 2>&1; then
    $SUDO systemctl enable --now docker || true
    HAVE_DOCKER=1
  fi
fi

# ---------- 4. 拉取代码 ----------
if [ ! -d "$INSTALL_DIR/.git" ]; then
  info "克隆项目代码（GitHub）..."
  if command -v git >/dev/null 2>&1; then
    $SUDO git clone https://github.com/y20260821744-ship-it/hu.git "$INSTALL_DIR"
  else
    # 无 git 时用 curl 下载 zip
    warn "未安装 git，改用 zip 下载..."
    $SUDO curl -fsSL -o /tmp/hu.zip https://github.com/y20260821744-ship-it/hu/archive/refs/heads/main.zip
    $SUDO unzip -o /tmp/hu.zip -d /tmp/hu-extract >/dev/null 2>&1 || { $SUDO apt-get install -y unzip >/dev/null 2>&1 && $SUDO unzip -o /tmp/hu.zip -d /tmp/hu-extract; }
    $SUDO cp -r /tmp/hu-extract/hu-main/* "$INSTALL_DIR/"
  fi
else
  info "项目已存在，拉取最新代码..."
  $SUDO git -C "$INSTALL_DIR" pull --ff-only || warn "拉取失败（忽略，用现有代码）"
fi

# ---------- 5. 配置 .env ----------
cd "$INSTALL_DIR"
if [ ! -f .env ]; then
  $SUDO cp .env.example .env
  warn "已生成 .env 模板，请务必编辑填写：日本代理 PROXY_LIST 与通知渠道"
  warn "编辑命令：nano $INSTALL_DIR/.env  （或用面板代理池在线添加，二选一即可）"
else
  info ".env 已存在，保留现有配置"
fi

# ---------- 6. 启动 ----------
if [ "$HAVE_DOCKER" -eq 1 ]; then
  info "构建并启动 Docker 服务..."
  $SUDO docker compose up -d --build
  sleep 3
  $SUDO docker compose ps
else
  # ---------- Python 方式（无 Docker 兜底） ----------
  info "使用 Python3 + venv 方式部署..."
  if ! command -v python3 >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
      $SUDO apt-get install -y python3 python3-venv python3-pip
    else
      $SUDO yum install -y python3 python3-pip
    fi
  fi
  $SUDO bash -c "cd $INSTALL_DIR && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt -q"
  # systemd 服务
  cat > /tmp/monitor.service <<EOF
[Unit]
Description=JpSecondHandMonitor
After=network.target

[Service]
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/run.py serve
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
  $SUDO cp /tmp/monitor.service /etc/systemd/system/monitor.service
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now monitor
  $SUDO systemctl status monitor --no-pager | head -n 12
fi

# ---------- 7. 防火墙提示 ----------
IP=$(curl -fsSL --max-time 5 https://api.ipify.org 2>/dev/null || echo "服务器IP")
info "=============================================="
info "部署完成！"
info "面板地址: http://$IP:8000"
info "登录账号: admin   初始密码: admin123"
info "登录后请立即在「账号管理」修改密码"
info "=============================================="
warn "若面板无法访问，请检查云厂商安全组/防火墙放行 TCP 8000 端口："
warn "  Ubuntu/Debian: sudo ufw allow 8000/tcp"
warn "  CentOS:        sudo firewall-cmd --permanent --add-port=8000/tcp && sudo firewall-cmd --reload"
warn "抓取煤炉/骏河屋必须配置日本 IP 代理，否则大概率 403（国内/香港 IP 被限流）"
warn "配置代理：编辑 .env 的 PROXY_LIST，或登录面板 → 代理池 在线添加（无需重启）"
