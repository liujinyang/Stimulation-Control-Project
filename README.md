# Perfusion PySide6 Starter

Starter project generated from the MATLAB App Designer file `PerfusionControl_2019_C.mlapp` and refined using the sample protocol file `ProtocolA.xls`.

## What was matched to the MATLAB app

- Serial port selection and connection at 115200 baud
- CR/LF line termination on outbound serial commands
- Excel protocol import for both `.xlsx` and legacy `.xls`
- CSV logging while protocol is running

## Protocol file format

The protocol table/file is STIMULUS-only (no valve - that hardware isn't used
in experiments anymore) and duration-based: each row holds a pulse state for
a fixed number of seconds, rather than specifying an absolute start time.
Units are fixed (seconds for duration, milliseconds for pulse width) so there
are no per-row unit columns to get wrong. Columns:

- `Duration time(in Sec)`
- `Pulse On/Off` (`on`/`off`)
- `Pulse Width(in ms)`
- `Pulse Frequency (in Hz)` (0 Hz means continuously on, not a 0 Hz pulse train)

`ProtocolCodec.encode_protocol_download()` converts this duration-based table
into the device's absolute-time wire commands (the device/firmware protocol
itself - `CLEAR`/`PULSE`/`ON`/`OFF`/`RUN`/`STOP`/`MANUAL` - is unchanged) by
accumulating a running start time and appending a final `OFF STIMULUS` at the
total duration so the protocol stops exactly when the last row's duration
ends rather than when it starts:

- `CLEAR`
- `PULSE STIMULUS <start_ms> <width_ms> <frequency>` (pulsing, frequency > 0)
- `ON STIMULUS <start_ms>` (pulse on, frequency == 0 - continuously on)
- `OFF STIMULUS <start_ms>`
- ...one final `OFF STIMULUS <total_duration_ms>` bookend

Manual commands:
- `MANUAL STIMULUS ON` / `MANUAL STIMULUS <0-500>` / `MANUAL STIMULUS OFF`

Serial receive parser:
- read all available text
- detect `DONE`
- parse `<current>,<voltage_mv>,<elapsed_us>` triples from the stream
- discard the first and last triple before plotting/logging (partial read)

## Import behavior

The original MATLAB app only opened `*.xls` files. This Python starter supports:

- `.xlsx` directly through pandas
- `.xls` by converting it to `.xlsx` with LibreOffice when needed

That makes legacy `.xls` protocol files load correctly without changing the rest of the app structure.

## Sample protocol mapping from `protocolC.xlsx`

| Duration time(in Sec) | Pulse On/Off | Pulse Width(in ms) | Pulse Frequency (in Hz) |
| --- | --- | --- | --- |
| 1 | on | 1 | 20 |
| 2 | off | | |
| 2 | on | 1 | 0 |
| 2 | off | | |

produces the following device commands:

```text
CLEAR
PULSE STIMULUS 0.0 1.0 20.0
OFF STIMULUS 1000.0
ON STIMULUS 3000.0
OFF STIMULUS 5000.0
OFF STIMULUS 7000.0
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m perfusion_app.main
```

## Build standalone apps (Windows and macOS)

PyInstaller cannot cross-compile - a build run on Windows only ever produces
a Windows `.exe`, and a build run on macOS only ever produces a `.app`. Since
this project folder is synced via OneDrive between a Windows machine and a
Mac, **always build each platform into its own distpath/workpath**, or the
two builds will overwrite each other's `_internal`/`Frameworks` folder the
next time OneDrive syncs (this happened once already - a Windows `.exe` ended
up with macOS `.dylib`/`.framework` files mixed into its `_internal` folder
and stopped launching). From `perfusion_app/`:

```bash
# On Windows:
pyinstaller "Stimulation Control.spec" --distpath "./dist-windows" --workpath "./build-windows"

# On macOS:
pyinstaller "Stimulation Control.spec" --distpath "./dist-macos" --workpath "./build-macos"
```

Full setup steps, run in a terminal from the `perfusion_pyside6_starter` folder:

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt pyinstaller
cd perfusion_app
pyinstaller "Stimulation Control.spec" --distpath "./dist-windows" --workpath "./build-windows"   # or dist-macos/build-macos on a Mac
```

This produces `perfusion_app/dist-windows/Stimulation Control/Stimulation Control.exe`
on Windows, or `perfusion_app/dist-macos/Stimulation Control.app` on macOS.
The `.spec` file detects macOS automatically (`sys.platform == "darwin"`) and
adds the extra `BUNDLE()` step needed to produce a proper `.app` instead of
just a folder; the same file still builds the Windows `.exe` unchanged when
run on Windows.

Each dist folder gets its own `Data/` (CSV logs) and `Protocols/` (sample
protocol files) alongside the app/exe - `AppController._app_base_dir()`
anchors these to wherever the running app/exe actually lives (not the current
working directory), specifically so a macOS `.app` launched by double-clicking
in Finder - which does *not* set the working directory to anywhere inside the
bundle - still finds/creates them in the right place, right next to the `.app`.

Things that are specific to macOS and worth knowing before handing this to
someone else:

- **Build on the same chip family the app will run on.** `target_arch` is
  left at its default (match the build machine), so a build made on an
  Apple Silicon Mac won't run on an Intel Mac and vice versa. If both need
  to be supported, build once on each, or build with a universal2 Python
  (not set up here).
- **Gatekeeper will block it on first launch** since this isn't signed with
  an Apple Developer certificate. The recipient needs to either right-click
  the app and choose "Open" (instead of double-clicking) the first time, or
  the person who builds it can clear the quarantine flag before sharing it:
  `xattr -cr "dist-macos/Stimulation Control.app"`.
- **Xcode Command Line Tools** (`xcode-select --install`) need to be present
  on the build Mac for PyInstaller's bootloader to compile correctly.
- UPX is skipped automatically on macOS in the `.spec` file (`use_upx`) since
  UPX-compressed binaries are a common cause of Gatekeeper/codesign failures,
  especially on Apple Silicon.

## Recommended next improvements

- Replace `QTableWidget` with a `QAbstractTableModel` and combo-box delegates for stricter editing
- Add a serial traffic recorder so you can compare Python traffic against the MATLAB app on real hardware
- Confirm whether the device needs delays or acknowledgements between downloaded protocol lines
- Confirm whether the 20000-byte MATLAB callback threshold should be replicated, or whether the current timer polling is sufficient
- Capture a few real device traces and tighten the receive parser once the packet format is known
