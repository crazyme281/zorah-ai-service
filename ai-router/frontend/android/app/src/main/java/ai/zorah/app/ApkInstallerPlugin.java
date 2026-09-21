package ai.zorah.app;

import android.content.Intent;
import android.net.Uri;
import androidx.core.content.FileProvider;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * Downloads an APK to the app's own cache directory and hands it to
 * Android's package installer.
 *
 * Written as one small native plugin rather than wiring a community
 * download plugin plus a community "open file" plugin — both of those
 * typically register their own AndroidManifest <provider> entries, which
 * risks colliding with the FileProvider this project already declares
 * (authority "${applicationId}.fileprovider", see AndroidManifest.xml).
 * This plugin reuses that existing provider instead of adding a second
 * one, and streams the download straight to disk rather than round-
 * tripping tens of megabytes through the JS bridge as a base64 string.
 *
 * NOTE: this file has not been compiled/run — there's no Android SDK or
 * Gradle available in the environment that wrote it. It uses only
 * long-stable, well-documented Android APIs (HttpURLConnection,
 * FileProvider, ACTION_VIEW) in their standard, textbook shape, but
 * still: build once in Android Studio and check Logcat for `install()`
 * specifically before shipping.
 */
@CapacitorPlugin(name = "ApkInstaller")
public class ApkInstallerPlugin extends Plugin {

    @PluginMethod
    public void download(PluginCall call) {
        String urlStr = call.getString("url");
        String fileName = call.getString("fileName", "zorah-update.apk");
        if (urlStr == null || urlStr.isEmpty()) {
            call.reject("url is required");
            return;
        }

        // Off the plugin's call thread — this can run for a while on a
        // slow connection and must not block the bridge.
        new Thread(() -> runDownload(call, urlStr, fileName)).start();
    }

    private void runDownload(PluginCall call, String urlStr, String fileName) {
        HttpURLConnection conn = null;
        try {
            URL url = new URL(urlStr);
            conn = (HttpURLConnection) url.openConnection();
            conn.setConnectTimeout(15000);
            conn.setReadTimeout(30000);
            conn.setInstanceFollowRedirects(true);
            conn.connect();

            int status = conn.getResponseCode();
            if (status != 200) {
                call.reject("download failed: HTTP " + status);
                return;
            }

            long total = conn.getContentLengthLong();
            // Cache dir — file_paths.xml already declares a cache-path
            // covering the whole cache root, so nothing else needs
            // configuring for FileProvider to be able to serve this file.
            File outFile = new File(getContext().getCacheDir(), fileName);

            try (InputStream in = conn.getInputStream();
                 FileOutputStream out = new FileOutputStream(outFile)) {
                byte[] buffer = new byte[8192];
                long downloaded = 0;
                int lastPercentSent = -1;
                int read;
                while ((read = in.read(buffer)) != -1) {
                    out.write(buffer, 0, read);
                    downloaded += read;
                    if (total > 0) {
                        int percent = (int) (downloaded * 100 / total);
                        if (percent != lastPercentSent) {
                            lastPercentSent = percent;
                            JSObject progress = new JSObject();
                            progress.put("percent", percent);
                            notifyListeners("downloadProgress", progress);
                        }
                    }
                }
            }

            JSObject result = new JSObject();
            result.put("path", outFile.getAbsolutePath());
            call.resolve(result);
        } catch (Exception e) {
            call.reject("download error: " + e.getMessage());
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    @PluginMethod
    public void install(PluginCall call) {
        String path = call.getString("path");
        if (path == null || path.isEmpty()) {
            call.reject("path is required");
            return;
        }

        File file = new File(path);
        if (!file.exists()) {
            call.reject("file not found: " + path);
            return;
        }

        String authority = getContext().getPackageName() + ".fileprovider";
        Uri uri;
        try {
            uri = FileProvider.getUriForFile(getContext(), authority, file);
        } catch (IllegalArgumentException e) {
            call.reject("FileProvider isn't configured for this path: " + e.getMessage());
            return;
        }

        Intent intent = new Intent(Intent.ACTION_VIEW);
        intent.setDataAndType(uri, "application/vnd.android.package-archive");
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);

        // This hands off to the OS installer and returns immediately —
        // it does NOT report back whether the user actually completed
        // the install. That's intentional: Android gives no reliable
        // cross-app callback for "the user tapped Install," so the real
        // confirmation is the next /apk/current version check once the
        // app relaunches, not anything this call could return.
        try {
            getContext().startActivity(intent);
            call.resolve();
        } catch (Exception e) {
            call.reject("couldn't open the installer: " + e.getMessage());
        }
    }
}