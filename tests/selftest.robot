*** Settings ***
Documentation     Self-test check. Asserts the three things every later
...               milestone depends on: the firmware boots and reaches the host
...               over UART, the DWT cycle counter advances, and the seeded
...               sensor peripheral returns values the firmware cannot predict.
Suite Setup       Setup
Suite Teardown    Teardown
Test Setup        Reset Emulation
Test Teardown     Test Teardown
Resource          ${RENODEKEYWORDS}

*** Variables ***
# From the environment, set by scripts/test.sh. Not repeated here: a second copy
# of the seed is a second copy that can drift from the one used to generate the
# platform file.
${SEED}           %{SEED}
${PLATFORM}       ${CURDIR}/../build/gen/rewind_${SEED}.repl
${ELF}            ${CURDIR}/../firmware/build/rewind-m.elf
${UART}           sysbus.usart2

*** Keywords ***
Create Rewind Machine
    Execute Command           mach create "rewind-m"
    Execute Command           machine LoadPlatformDescription @${PLATFORM}
    Execute Command           sysbus LoadELF @${ELF}
    Create Terminal Tester    ${UART}

*** Test Cases ***
Firmware Boots And Reports
    Create Rewind Machine
    Start Emulation
    Wait For Line On Uart     rewind-m self-test

Cycle Counter Advances
    [Documentation]           A stuck CYCCNT would silently corrupt every trace
    ...                       timestamp, so it is a hard gate.
    ...                       The firmware itself prints FAIL dwt_stuck if the
    ...                       counter did not move; this asserts the good path.
    Create Rewind Machine
    Start Emulation
    Wait For Line On Uart     selftest OK

Sensor Returns Varying Samples
    [Documentation]           Two consecutive sensor reads must differ,
    ...                       otherwise the run carries no non-determinism for
    ...                       the recorder to capture and the whole experiment
    ...                       is vacuous.
    Create Rewind Machine
    Start Emulation
    ${s0}=    Wait For Line On Uart    sensor\\[0\\]=(0x[0-9a-f]+)    treatAsRegex=true
    ${s1}=    Wait For Line On Uart    sensor\\[1\\]=(0x[0-9a-f]+)    treatAsRegex=true
    Should Not Be Equal       ${s0.Groups[0]}    ${s1.Groups[0]}
