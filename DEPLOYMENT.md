# Supervisor demonstration deployment

Run one instance of the existing app behind a managed HTTPS proxy. The container starts a protected entry point for ReValue YOLO11n CPU inference. The Windows scripts continue to start the local app and comparison tool.

## Hosting and estimated cost

The Render Blueprint selects **Standard, 2 GB RAM**, in Singapore. Budget **approximately USD $25 for a full month**, before any tax. Verify the current rate and any additional charges on the Render review screen before applying the Blueprint. A local five-image CPU test reached 598,392 KiB peak process RSS, above 512 MiB, so a 512 MiB plan is unsuitable for this demo. Use one instance and stop the service when the supervisor review period ends. [Render pricing](https://render.com/pricing)

## Create the HTTPS service

1. Sign in to Render and use **New → Blueprint**. Connect GitHub and grant access to `YANKEY-CODE/ReValue-AI`. Select `fyp1-development` as the Blueprint branch. The Blueprint uses that branch directly, so PR #1 can remain in draft. [Render Blueprint documentation](https://render.com/docs/infrastructure-as-code)
2. Generate a random demo password locally. Enter the result as the value of `REVALUE_DEMO_PASSWORD` in the Blueprint setup or in the service’s **Environment** settings. Keep it out of commits and chat.

   ```powershell
   Set-Location 'C:\Users\USER\ReValue-AI'
   .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(24))"
   ```

3. Review the quoted price and apply the Blueprint only if you approve it. Render supplies the public origin as `RENDER_EXTERNAL_URL`. For another compatible Docker host, set `REVALUE_PUBLIC_ORIGIN` to the exact external `https://` origin and configure the health path as `/healthz`.
4. Wait for the deploy to be live. Copy the assigned HTTPS URL from the service overview. It is ready to share after an unauthenticated visit prompts for credentials and the authenticated workflow below passes. Use the username `supervisor` and share the generated password separately through an approved private channel.

Automatic deployment is off. Apply subsequent verified revisions with **Manual Deploy → Deploy latest commit**. A missing or invalid demo password or HTTPS origin prevents the service from starting.

## Local preflight

From the repository root, build the same container and run the gateway regression tests. The deployed browser test below also works with a local HTTPS reverse proxy and generated fixture photos. A local pass covers the application path, while the provider’s actual URL still needs its own check.

```text
docker build -t revalue-supervisor .
python -m unittest backend.tests.test_supervisor
```

## Access and privacy controls

- The login protects the application, assets, catalogue and assessment APIs. The public health route returns only `ok`. App responses use `no-store`. Embedding and cross-origin API writes are blocked.
- Use one process and one instance. The service allows six analysis submissions, 40 other writes and 240 authorized reads per minute, shared by demo users. It admits one concurrent analysis and up to 16 simultaneous connections. Failed logins have a separate throttle.
- The hosted browser resizes photos to a maximum 2,048-pixel edge, removes source metadata by encoding JPEG in the browser, and uploads synthetic view filenames. The server caps encoded scan requests at 14 MiB and individual photos at 2 MiB, with the existing file-format, image-size and view checks. Uploads are processed in memory and application logs omit request details. Use consented photos and close the browser after review. Example-shop chats can persist locally in that browser.
- The hosted build uses the pinned YOLO11n weights and excludes the experimental comparison, QR transfer and external photo verification. The reports can show a provisional grade and explain that eligible market evidence is unavailable. The separate local comparison remains available on port 8766.

## Verify the actual public URL

1. Visit the assigned HTTPS URL in a private desktop browser window. Sign in, search for an iPhone 13 Pro, confirm storage, and supply five different permitted photos. Run **Analyze Exterior** and open **View Exterior Report**. Check the detector name, grade basis and market-evidence state.
2. Repeat on a phone. Check photo selection and replacement, readability of the report and the login prompt in a fresh private window. Use an HTTPS URL without a certificate warning.
3. For a repeatable test, use Playwright and Chromium. The smoke test checks the access gate, all five uploads, a real CPU response and the report in desktop and mobile viewports. Enter the password at the local prompt. Replace the sample URL with the actual service URL.

   ```powershell
   $env:REVALUE_DEMO_URL = 'https://YOUR-ASSIGNED-SERVICE.onrender.com'
   $secret = Read-Host 'Demo password' -AsSecureString
   $env:REVALUE_DEMO_PASSWORD = [Net.NetworkCredential]::new('', $secret).Password
   try { node fyp/deployed_smoke.cjs } finally { Remove-Item Env:REVALUE_DEMO_PASSWORD }
   ```

If deployment reports an unhealthy service, check the build and startup logs, the secret, and the `/healthz` path. If the page opens but POST requests fail with 403, use the exact configured HTTPS origin. The health check alone does not verify inference or access protection.
