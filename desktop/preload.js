// 只暴露必要信息给页面，其余保持隔离。
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("fav2noteDesktop", {
  version: process.versions.electron,
  platform: process.platform,
});
