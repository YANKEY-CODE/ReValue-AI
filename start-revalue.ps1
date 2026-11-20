#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The project virtual environment is missing. Run setup-windows.ps1 first.'
}

# Use the project interpreter directly so no activation script or global Python is needed.
$serverCode = @'
import json
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import ProxyHandler, build_opener
import webbrowser

runtime = Path.cwd() / '.revalue-runtime'
for name, directory in [('YOLO_CONFIG_DIR', 'yolo'), ('MPLCONFIGDIR', 'matplotlib')]:
    path = runtime / directory
    path.mkdir(parents=True, exist_ok=True)
    os.environ[name] = str(path)
os.environ['YOLO_AUTOINSTALL'] = 'false'
os.environ.setdefault('OMP_NUM_THREADS', '2')
os.environ.setdefault('MKL_NUM_THREADS', '2')
os.environ.pop('REVALUE_DETECTOR_WEIGHTS', None)
os.environ.pop('REVALUE_DETECTOR_IMGSZ', None)

from backend.src.server import ReValueHandler
from backend.src.yolo_detector import DEFAULT_MODEL_PATH

HOST, PORT = '127.0.0.1', 8765
URL = f'http://{HOST}:{PORT}'


def verify_installation():
    from base64 import b64encode
    from io import BytesIO
    from PIL import Image
    import torch
    from torchvision.ops import nms
    from backend.src.schemas import ImageInput
    from backend.src.yolo_detector import RAW_CLASS_NAMES, detect_exterior_damage, load_yolo_model

    if torch.version.cuda is not None:
        raise RuntimeError('Expected the CPU build of PyTorch. Rerun setup-windows.ps1.')
    nms(torch.tensor([[0., 0., 10., 10.]]), torch.tensor([1.]), 0.5)
    if load_yolo_model().names != RAW_CLASS_NAMES:
        raise RuntimeError('Unexpected classes in the bundled YOLO11n checkpoint.')
    photo = BytesIO()
    Image.new('RGB', (320, 240), 'white').save(photo, format='PNG')
    detect_exterior_damage([ImageInput('front', mime_type='image/png', bytes_b64=b64encode(photo.getvalue()).decode())])
    print('Bundled YOLO11n CPU inference check passed.')

    with ThreadingHTTPServer((HOST, 0), ReValueHandler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            address = f'http://{HOST}:{server.server_port}'
            client = build_opener(ProxyHandler({}))
            with client.open(f'{address}/health', timeout=5) as response:
                if json.load(response).get('status') != 'ok':
                    raise RuntimeError('The local backend health check failed.')
            with client.open(address, timeout=5) as response:
                if b'decision-support.js' not in response.read():
                    raise RuntimeError('The current ReValue website could not be loaded.')
            with client.open(f'{address}/decision-support.js', timeout=5) as response:
                if b'ReValueDecisionSupport' not in response.read():
                    raise RuntimeError('The report calculator could not be loaded.')
        finally:
            server.shutdown()
            worker.join()
    print('Local backend and website startup checks passed.')


def open_browser():
    try:
        if webbrowser.open(URL):
            return
    except (OSError, webbrowser.Error):
        pass
    print(f'Open {URL} in your browser.')


if not DEFAULT_MODEL_PATH.is_file():
    raise SystemExit(f'Bundled YOLO11n checkpoint missing: {DEFAULT_MODEL_PATH}')

mode = sys.argv[1]
if mode == 'check':
    verify_installation()
else:
    try:
        server = ThreadingHTTPServer((HOST, PORT), ReValueHandler)
    except OSError as error:
        raise SystemExit(f'Could not listen on {URL}. Close any other app using port {PORT} and try again. {error}') from error
    with server:
        print(f'ReValue AI is ready at {URL}')
        print('Press Ctrl+C to stop.')
        if mode == 'open':
            Thread(target=open_browser, daemon=True).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
'@

$mode = if ($Check) { 'check' } elseif ($NoBrowser) { 'serve' } else { 'open' }
Push-Location -LiteralPath $PSScriptRoot
try {
    $serverCode | & $python -u - $mode
    if ($LASTEXITCODE -ne 0) {
        throw "ReValue exited with code $LASTEXITCODE. See the error above and WINDOWS_SETUP.md."
    }
} finally {
    Pop-Location
}
