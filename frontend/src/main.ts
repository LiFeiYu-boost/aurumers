import "./styles/base.css";
import "./components";
import { router } from "./router";
import type { RouteRender } from "./router";
import { api } from "./api/client";
import { renderLanding } from "./pages/LandingPage";
import { renderDashboard } from "./pages/DashboardPage";
import { renderPredictions } from "./pages/PredictionsPage";
import { renderRecords } from "./pages/RecordsPage";
import { renderInsights } from "./pages/InsightsPage";
import { renderSettings } from "./pages/SettingsPage";
import { renderChat } from "./pages/ChatPage";
import { renderAuth } from "./pages/AuthPage";
import { renderWallet } from "./pages/WalletPage";
import { renderAdmin } from "./pages/AdminPage";
import { initTheme } from "./theme";

initTheme();

// 路由守卫(task #62):受保护页面渲染前校验登录态,未登录跳登录页。
// 返回占位容器,异步校验后再填充真实页面(render 仍同步返回 HTMLElement)。
function requireAuth(render: RouteRender): RouteRender {
  return (params) => {
    const container = document.createElement("div");
    container.dataset.title = "加载中";
    api.auth
      .me()
      .then(() => container.replaceChildren(render(params)))
      .catch(() => router.navigate("/auth/login"));
    return container;
  };
}

router
  .on("/app/predictions", requireAuth(renderPredictions))
  .on("/app/records", requireAuth(renderRecords))
  .on("/app/insights", requireAuth(renderInsights))
  .on("/app/settings", requireAuth(renderSettings))
  .on("/app/chat", requireAuth(renderChat))
  .on("/app/wallet", requireAuth(renderWallet))
  .on("/app", requireAuth(renderDashboard))
  .on("/_ops", requireAuth(renderAdmin))
  .on("/auth/login", renderAuth)
  .on("/auth/register", renderAuth)
  .on("/", renderLanding)
  .setFallback(renderLanding);

const mount = document.getElementById("app");
if (mount) {
  router.bind(mount);
}
