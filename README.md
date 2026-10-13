# NovaGuard

NovaGuard is a local camera monitoring dashboard with live threat detection, incident evidence, and camera source switching.

## Run the full project in development

Use two terminals. In the first, start the FastAPI detection service with the project's Python dependencies installed:

```powershell
python dashboard.py
```

In the second terminal, start the React landing page:

```powershell
cd designpro
npm.cmd ci
npm.cmd run dev
```

Vite serves the adapted `index (3).html` design from `designpro/index.html`, so opening the Vite URL shows that landing page directly.

Open the Vite URL shown in the terminal, usually [http://127.0.0.1:5173](http://127.0.0.1:5173). Its **Open dashboard** button connects to the FastAPI service at [http://127.0.0.1:5000/dashboard](http://127.0.0.1:5000/dashboard). The server binds to the local computer by default. Set `NOVAGUARD_HOST` only when you intentionally need another interface.

For a single-server local deployment, build the landing page first and then start FastAPI:

```powershell
cd designpro
npm.cmd ci
npm.cmd run build
cd ..
python dashboard.py
```

The built landing page is served at `/`; when no build exists, FastAPI serves `index (3).html` directly. The monitor dashboard remains at `/dashboard`.

## Connect a webcam

Choose **Add camera**, select **Webcam connected to this computer**, enter a name, and use index `0` for the default webcam. If that device is unavailable, try `1` or `2`. The webcam must be connected to the computer running the Python server.

## Connect an IP camera or NVR

Enable RTSP on the camera/NVR and add its stream URL from **Add camera → IP camera or NVR stream**. A common Hikvision main-stream pattern is:

```text
rtsp://CAMERA_IP:554/Streaming/Channels/101
```

Camera URL paths vary by manufacturer and recorder. Use the exact RTSP URL from the camera/NVR documentation. For an authenticated stream, include the camera username and password in the URL. NovaGuard accepts RTSP, RTSPS, HTTP, and HTTPS video stream URLs through OpenCV/FFmpeg.

Camera profiles and their stream URLs are saved in `cameras.json` beside the app. That file is ignored by Git because it can contain camera credentials. The dashboard keeps profiles for multiple cameras but processes one selected live feed at a time. If a stream drops, NovaGuard retries the active source and reports its connection state in the dashboard.

Email alerts are optional. Configure `NOVAGUARD_EMAIL_SENDER`, `NOVAGUARD_EMAIL_PASSWORD`, and the recipient variables `NOVAGUARD_FIRE_EMAIL`, `NOVAGUARD_ACCIDENT_EMAIL`, `NOVAGUARD_VIOLENCE_EMAIL`, and `NOVAGUARD_WEAPON_EMAIL` in the environment. Use an app password, not an account password. Without these values, the dashboard continues to record incidents but does not send email.

Use a dedicated read-only camera account where supported. On Render, set `NOVAGUARD_ACCESS_USERNAME` and `NOVAGUARD_ACCESS_PASSWORD` to enable HTTP Basic Authentication; the service refuses dashboard requests if it detects Render without configured credentials. Keep the app behind HTTPS and do not expose camera streams directly to the public internet.

## Render deployment

The repository Dockerfile listens on Render's `PORT` and exposes `/health` for health checks. Configure `NOVAGUARD_ACCESS_USERNAME` and `NOVAGUARD_ACCESS_PASSWORD` as Render environment variables before opening the public URL. On Render, inference defaults to disabled so the dashboard can run on the free 512 MB instance without loading the YOLO and SlowFast models. Set `NOVAGUARD_ENABLE_INFERENCE=true` only on an instance with sufficient memory; verify model startup before relying on detection. The service can only process a camera stream reachable from Render; a webcam plugged into your personal computer is not available to the hosted service. Render's filesystem is ephemeral, so evidence and camera profiles are not durable across restarts without a persistent disk.
