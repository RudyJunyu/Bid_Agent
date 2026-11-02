const { app, BrowserWindow, dialog } = require("electron");

function webUrl() {
  const target = new URL(process.env.BID_WEB_URL || "http://127.0.0.1:8080");
  if (!["http:", "https:"].includes(target.protocol)) {
    throw new Error("BID_WEB_URL must be an HTTP(S) URL");
  }
  return target.href;
}

async function createWindow() {
  const target = webUrl();
  const win = new BrowserWindow({
    width: 1180, height: 820, minWidth: 960, minHeight: 680,
    title: "投标", backgroundColor: "#f6f7f9",
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true }
  });
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (event, url) => {
    if (new URL(url).origin !== new URL(target).origin) event.preventDefault();
  });
  try {
    await win.loadURL(target);
  } catch (error) {
    dialog.showErrorBox("服务连接失败", `请先执行 docker compose up -d --build。\n地址：${target}\n${error.message}`);
  }
}

app.whenReady().then(createWindow).catch((error) => {
  dialog.showErrorBox("配置错误", error.message);
  app.quit();
});
app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
