# Setup

## What you need

| Tool | Why | Notes |
|---|---|---|
| `arm-none-eabi-gcc` | builds the firmware | tested with 14.2.Rel1 |
| `make` | build driver | on Windows, use Git Bash — the Makefile uses `mkdir -p` |
| Python 3.11+ | platform generation, trace tooling | |
| Renode 1.16+ | runs the target | see the warning below |

## Linux

```bash
sudo apt-get install -y gcc-arm-none-eabi make python3
curl -fsSL -o renode.tar.gz \
  https://github.com/renode/renode/releases/download/v1.16.1/renode-1.16.1.linux-portable-dotnet.tar.gz
mkdir -p ~/renode && tar xf renode.tar.gz -C ~/renode --strip-components=1
pip install -r ~/renode/tests/requirements.txt

export RENODE_DIR=~/renode
scripts/test.sh
```

## Windows — read this before installing Renode

**The winget package (`Renode.Renode`) does not work.** It installs the Mono-based build
without the CPU translation libraries (`tlib`), so creating any machine fails at
`TranslationCPU.Init()` with:

```
InvalidOperationException: Error while getting symbol from dynamic library: unknown error
   at Antmicro.Renode.Utilities.Binding.NativeBinder.ResolveCallsToNative(...)
   at Antmicro.Renode.Peripherals.CPU.TranslationCPU.Init()
```

This is not specific to this project's platform file — the stock
`platforms/boards/stm32f4_discovery.repl` fails the same way.

The official `renode-1.16.1.windows-portable-dotnet.zip` bundles the native libraries inside
a single self-contained executable and extracts them at runtime. On a Windows machine with
commercial endpoint protection running, this still failed with the same symbol-resolution
error — consistent with an antivirus quarantining the freshly extracted, unsigned native
library before it can be loaded. If you hit this, the options are, in order of robustness:

1. **Use WSL2 with Ubuntu** and follow the Linux instructions. This is also exactly what CI
   runs, so local results and CI results cannot drift.
2. Add an antivirus exclusion for the Renode directory and the temp directory it extracts
   into. Faster, but it is a security setting — decide deliberately.
3. Build the firmware locally and let CI do the Renode verification. Works, but every check
   costs a push.

The firmware build itself is fine on Windows; only running the emulator is affected.

```bash
winget install -e --id Arm.GnuArmEmbeddedToolchain --source winget
winget install -e --id ezwinports.make --source winget
```

If winget reports `0x8a15005e : The server certificate did not match any of the expected
values`, that is the `msstore` source failing behind a TLS-inspecting antivirus — pass
`--source winget` as shown above to skip it.

## Building without Renode

```bash
make -C firmware        # produces firmware/build/rewind-m.elf and .bin
make -C firmware size
```

The build is warning-clean under `-Wall -Wextra -Werror -Wshadow -Wundef`; keep it that way.
