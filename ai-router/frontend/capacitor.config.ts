import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "ai.zorah.app",
  appName: "Zorah AI",
  webDir: "dist",
  backgroundColor: "#08080a",
  plugins: {
    SplashScreen: {
      backgroundColor: "#08080a",
      showSpinner: false,
      androidScaleType: "CENTER_CROP",
    },
  },
};

export default config;
