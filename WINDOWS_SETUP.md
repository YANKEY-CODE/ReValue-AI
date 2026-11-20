# Run ReValue AI on Windows

Use Windows 10 or 11 x64 with Windows PowerShell 5.1 or PowerShell 7, Git for Windows 2.23 or newer, and 64-bit Python 3.12. The installer uses CPU wheels. The laptop needs internet access during setup to reach GitHub, PyTorch and PyPI. The bundled YOLO11n runs locally without an API key.

## Install and open the website

1. Save [setup-windows.ps1](https://raw.githubusercontent.com/YANKEY-CODE/ReValue-AI/fyp1-development/setup-windows.ps1) to **Downloads**. Check that the file ends in `.ps1`.
2. Open **Windows PowerShell** from Start and run these commands.

   ```powershell
   Set-Location "$env:USERPROFILE\Downloads"
   Unblock-File -LiteralPath .\setup-windows.ps1
   powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\setup-windows.ps1 -Launch
   ```

3. If setup lists a missing prerequisite, run the relevant command below, then open a new PowerShell window and repeat step 2. The installer can also be downloaded directly from its website. [Git for Windows](https://git-scm.com/download/win) · [Python for Windows](https://www.python.org/downloads/windows/)

   ```powershell
   winget install --exact --id Git.Git
   winget install --exact --id Python.Python.3.12 --architecture x64
   ```

Setup clones `YANKEY-CODE/ReValue-AI:fyp1-development` into `$env:USERPROFILE\ReValue-AI`. Sign in to GitHub if Git Credential Manager prompts you. The script can also fast-forward an existing clean checkout of the same repository. Use `-ProjectPath 'C:\Projects\ReValue-AI'` for a different location. Existing local changes or a diverged branch require a clean checkout or a different target folder.

The installer creates `.venv`, installs PyTorch `2.14.1+cpu` and Torchvision `0.29.1+cpu` from the official CPU index, and installs the [Windows backend pins](backend/requirements-windows-cpu.txt) from PyPI. These include Ultralytics, OpenCV, Pillow, QR generation, Gemini's optional client, and the rest of the current backend requirements. It verifies imports, the Torchvision CPU operator, the bundled checkpoint and inference on a generated image, and the local HTTP service and page. [PyTorch CPU wheels](https://download.pytorch.org/whl/cpu/)

The website is ready when these two lines appear after `Setup complete`.

```text
ReValue AI is ready at http://127.0.0.1:8765
Press Ctrl+C to stop.
```

The launcher opens your default browser. If needed, enter **http://127.0.0.1:8765** in its address bar. Leave PowerShell open while using ReValue. Press **Ctrl+C** there to stop the server. The URL works on the laptop running ReValue.

## Launch it again

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File "$env:USERPROFILE\ReValue-AI\start-revalue.ps1"
```

Use the launcher in your chosen project folder if you used `-ProjectPath`. Run it with `-Check` to repeat the local model and startup checks without leaving the website running, or with `-NoBrowser` to start without opening a tab. The launcher uses the project's Python interpreter directly and keeps the YOLO and Matplotlib runtime files in `.revalue-runtime`. To update the branch and dependencies, rerun the setup script in the checkout.

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| `git` or Python 3.12 x64 is missing | Install the matching prerequisite above and open a new PowerShell window. `git --version` and `py -3.12 --version` confirm the commands are available. On a system without the Python launcher, the script also checks `python.exe` on `PATH`. |
| PowerShell cannot find or execute the `.ps1` | Check the filename and folder, including whether your browser appended `.txt`. Use `Unblock-File` on the script downloaded from your repository and launch it with the per-process command above. On a university-managed laptop, contact IT if Group Policy blocks scripts. |
| `No matching distribution found` or download failure | Check that the interpreter is Python 3.12 x64 and that GitHub, `download.pytorch.org`, `download-r2.pytorch.org`, `pypi.org` and `files.pythonhosted.org` are reachable on your network. Rerun setup after fixing access. |
| `WinError 126`, `WinError 127` or DLL load failure | Install or repair the Microsoft Visual C++ x64 runtime, then rerun setup. A persistent OpenCV DLL error on Windows N may require Media Feature Pack in Windows Optional Features. |
| `.venv` cannot run or is from another computer | Move `.venv` outside the ReValue checkout and rerun setup. Virtual environments are tied to their original Python installation. |
| Port 8765 is already in use | If ReValue is running in another PowerShell window, open its existing URL or stop that session with Ctrl+C before starting again. Use `Get-NetTCPConnection -LocalPort 8765 -State Listen` to check which process is listening. |
| Browser does not open, or shows a file preview | Enter `http://127.0.0.1:8765` in the browser and keep the launcher running. Opening the HTML file directly skips the Python backend. |
| Report has no live resale price | Local scanning still works. A live MYR estimate requires eligible market observations. See the FYP1 handoff for the evidence requirements and quote comparison. |

[Microsoft Visual C++ x64 runtime](https://aka.ms/vc14/vc_redist.x64.exe) · [FYP1 system handoff](fyp/FYP1_SYSTEM_HANDOFF.md)

## Verification status

The Windows x64 wheels resolved for Python 3.12. PowerShell on Linux verified the checkout and launcher flow with a simulated Windows executable layout, real CPU inference, and local HTTP responses. Native Windows installation and browser opening still need a laptop test.

For side-by-side predictions on your own photos, see the [separate local model comparison](fyp/MODEL_COMPARISON.md).
