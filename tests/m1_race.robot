*** Settings ***
Documentation     M1: the depth-hold control loop runs to completion under the
...               TIM2 tick and reports a verdict. Whether this particular seed
...               tears is not asserted here - that is a property of the seed,
...               and measuring it across many seeds is tools/campaign.py's job.
...               What must hold for every seed is that the run terminates and
...               says what happened.
Suite Setup       Setup
Suite Teardown    Teardown
Test Setup        Reset Emulation
Test Teardown     Test Teardown
Resource          ${RENODEKEYWORDS}

*** Variables ***
${SEED}           20260812
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
Control Loop Reaches Its Tick Target
    [Documentation]           If TIM2 never fired, the loop would spin to its
    ...                       iteration cap and print RUN FAIL no_ticks instead.
    Create Rewind Machine
    Start Emulation
    ${l}=    Wait For Line On Uart
    ...      control ticks=(\\d+) iters=(\\d+) torn=(\\d+) checksum=0x[0-9a-f]+
    ...      treatAsRegex=true    timeout=60
    Should Be Equal           ${l.Groups[0]}    200

Control Loop Does Work Between The Two Reads
    [Documentation]           The race needs the main loop to actually iterate.
    ...                       A loop that ran once would make the campaign
    ...                       meaningless without failing anything.
    Create Rewind Machine
    Start Emulation
    ${l}=    Wait For Line On Uart
    ...      control ticks=\\d+ iters=(\\d+) torn=\\d+ checksum=0x[0-9a-f]+
    ...      treatAsRegex=true    timeout=60
    Should Be True            ${l.Groups[0]} > 100

Run Ends With An Explicit Verdict
    Create Rewind Machine
    Start Emulation
    Wait For Line On Uart     RUN (OK|FAIL.*)    treatAsRegex=true    timeout=60
