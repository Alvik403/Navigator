import { defineConfig, type Plugin } from "vite";

const APP_BUILD_ID =
  process.env.APP_BUILD_ID ??
  new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);

function injectBuildBootScript(buildId: string): Plugin {
  const bootScript = `
(function () {
  var BUILD = ${JSON.stringify(buildId)};
  var BUILD_KEY = "max-rass.web.build";
  var RELOAD_KEY = "max-rass.web.build-reload";
  try {
    var prev = localStorage.getItem(BUILD_KEY);
    if (prev !== BUILD) {
      for (var i = sessionStorage.length - 1; i >= 0; i -= 1) {
        var key = sessionStorage.key(i);
        if (key && key.indexOf("oidc.") === 0) {
          sessionStorage.removeItem(key);
        }
      }
      localStorage.setItem(BUILD_KEY, BUILD);
      if (!sessionStorage.getItem(RELOAD_KEY)) {
        sessionStorage.setItem(RELOAD_KEY, "1");
        window.location.replace(window.location.pathname + window.location.search);
        return;
      }
      sessionStorage.removeItem(RELOAD_KEY);
    }
  } catch (_error) {}
})();`.trim();

  return {
    name: "inject-build-boot-script",
    transformIndexHtml(html) {
      return html.replace(
        "<head>",
        `<head>
  <meta http-equiv="Cache-Control" content="no-store, no-cache, must-revalidate">
  <meta http-equiv="Pragma" content="no-cache">
  <meta http-equiv="Expires" content="0">
  <script>${bootScript}</script>`,
      );
    },
  };
}

export default defineConfig({
  base: "/",
  define: {
    __APP_BUILD_ID__: JSON.stringify(APP_BUILD_ID),
  },
  build: {
    outDir: "dist",
  },
  plugins: [injectBuildBootScript(APP_BUILD_ID)],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/realms": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
      "/resources": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
      "/api": {
        target: "http://localhost:8025",
        changeOrigin: true,
      },
    },
  },
});
