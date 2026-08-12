# rewind-m firmware build.
#
# Deliberately plain: one compiler, no CMake, no vendor SDK. `make` on Windows
# (ezwinports), Linux and the CI runner all take the same path.

CROSS   ?= arm-none-eabi-
CC      := $(CROSS)gcc
OBJCOPY := $(CROSS)objcopy
SIZE    := $(CROSS)size

BUILD   := build
TARGET  := $(BUILD)/rewind-m

SRCS    := src/startup.c src/hal.c src/recorder.c src/main.c
OBJS    := $(patsubst src/%.c,$(BUILD)/%.o,$(SRCS))

CPUFLAGS := -mcpu=cortex-m4 -mthumb -mfloat-abi=soft

# -O1, not -O2: the deliberate race in M1 must survive optimisation, and -O0
# would make the recorder's cycle-cost measurements meaningless.
# EXTRA_CFLAGS lets the campaign runner sweep -DCONTROL_WORK=N without editing
# the source, so calibrating how rare the race is costs one CI run, not one per
# candidate value.
CFLAGS  := $(CPUFLAGS) -O1 -g3 -std=c11 \
           -Wall -Wextra -Werror -Wshadow -Wundef \
           -ffunction-sections -fdata-sections \
           -fno-common -fno-builtin $(EXTRA_CFLAGS)

LDFLAGS := $(CPUFLAGS) -T stm32f407.ld -nostdlib -nostartfiles \
           -Wl,--gc-sections -Wl,-Map=$(TARGET).map

.PHONY: all clean size

all: $(TARGET).elf $(TARGET).bin

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/%.o: src/%.c | $(BUILD)
	$(CC) $(CFLAGS) -c $< -o $@

$(TARGET).elf: $(OBJS)
	$(CC) $(OBJS) $(LDFLAGS) -o $@

$(TARGET).bin: $(TARGET).elf
	$(OBJCOPY) -O binary $< $@

size: $(TARGET).elf
	$(SIZE) $(TARGET).elf

clean:
	rm -rf $(BUILD)
