// Electron 外壳：拉起 Python 后端，等端口就绪后加载面板。
const { app, BrowserWindow, shell, dialog, Tray, Menu, nativeImage } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const http = require("node:http");
const fs = require("node:fs");

const PORT = 7788;
const isPackaged = app.isPackaged;
let backend = null;
let win = null;
let tray = null;

/** 后端启动命令：开发用本地 venv，打包后用随包分发的 exe */
function backendCommand() {
  if (isPackaged) {
    const exe = path.join(process.resourcesPath, "backend", "fav2note-backend.exe");
    return { cmd: exe, args: [] };
  }
  const venv = path.join(__dirname, "..", ".venv", "Scripts", "python.exe");
  const python = fs.existsSync(venv) ? venv : "python";
  return { cmd: python, args: ["-m", "fav2note.cli", "--home", path.join(__dirname, ".."), "web", "--port", String(PORT)] };
}

function waitForServer(timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get({ host: "127.0.0.1", port: PORT, path: "/api/summary", timeout: 1000 }, (res) => {
        res.resume();
        res.statusCode === 200 ? resolve() : retry();
      });
      req.on("error", retry);
      req.on("timeout", () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (Date.now() > deadline) return reject(new Error("后端启动超时"));
      setTimeout(tick, 300);
    };
    tick();
  });
}

function startBackend() {
  const { cmd, args } = backendCommand();
  backend = spawn(cmd, args, {
    cwd: path.join(__dirname, ".."),
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  backend.stdout.on("data", (d) => process.stdout.write(`[backend] ${d}`));
  backend.stderr.on("data", (d) => process.stderr.write(`[backend] ${d}`));
  backend.on("exit", (code) => {
    if (code && !app.isQuitting) {
      dialog.showErrorBox("fav2note", `后端进程退出（code ${code}），请查看日志`);
    }
  });
}

function createWindow() {
  win = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 940,
    minHeight: 620,
    title: "fav2note",
    backgroundColor: "#f6f6f4",
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile(path.join(__dirname, "loading.html"));

  waitForServer()
    .then(() => win && win.loadURL(`http://127.0.0.1:${PORT}`))
    .catch((error) => {
      dialog.showErrorBox("fav2note", `无法启动本地服务：${error.message}`);
      app.quit();
    });

  // 外链走系统浏览器，不在应用内打开
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });

  win.on("closed", () => { win = null; });
}

function createTray() {
  const icon = nativeImage.createEmpty();
  tray = new Tray(icon);
  tray.setToolTip("fav2note");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "打开面板", click: () => (win ? win.show() : createWindow()) },
    { label: "退出", click: () => app.quit() },
  ]));
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
  createTray();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("before-quit", () => {
  app.isQuitting = true;
  if (backend && !backend.killed) {
    backend.kill();
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
