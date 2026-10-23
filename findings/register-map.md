# Telink B80 (TLSR825x / TC32) peripheral register map

For symbolicating stripped 8BitDo Ultimate 2C firmware (SDK string `telink_b80_ble_2.4g_dual_mode_sdk_V3.0.0`).

Peripheral window base `REG_BASE_ADDR = 0x800000`; `REG_ADDR8(a)` = byte at `0x800000 + a`. **Register offset = absolute address − 0x800000.** The B80 digital register layout is identical to TLSR8258/8278 (B85/B87); addresses below are taken verbatim from Telink's `chip/B80/drivers/register.h`, cross-checked against B85/B87 and the pvvx 8258 map.

## Primary sources (raw headers fetched, not guessed)

- `telink-semi/tc_platform_sdk` → `chip/B80/drivers/register.h` (master digital map), `gpio.h`, `pm.h` (`lib/include/pm.h`), `adc.h`, `analog.h`, `usbhw.c`, `lib/include/rf_drv.h`. This is the exact SDK generation the firmware string names.
- `telink-semi/tc_ble_sdk` → `tc_ble_sdk/drivers/{B85,B87}/register.h`, `.../B85/gpio.c` (analog pull / pad-wakeup writes).
- `pvvx/ATC_MiThermometer` → `SDK/components/drivers/8258/{register_8258.h, pm.h, lpc.h}` (battle-tested 825x map + low-power-comparator).

## Address-space reminder

`0x000000–0x7FFFFF` = program/flash space; **bit23 set** selects peripheral space, so `0x800000–0x80FFFF` = registers, `0x840000–0x84FFFF` = 64K SRAM. Analog registers (ADC, PMU trims, pad pulls, deep-sleep retention, VBAT divider, comparator) are **not** in this window — they live in a separate analog address space reached indirectly through the analog port at offset `0xb8/0xb9/0xba` (`analog_read`/`analog_write`).

---

## The 18 specific addresses in your disassembly

### Controller image

| abs addr   | off   | identification                                                       | conf       | notes                                                                                                                                                                                                                                                                                                  |
| ---------- | ----- | -------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `0x800740` | 0x740 | **`reg_system_tick`** (REG_ADDR32)                                   | **high**   | Free-running system-timer tick counter. This being the single hottest register is textbook Telink: every BLE/2.4G scheduling deadline, `clock_time()`, timeout and `while(!clock_time_exceed())` busy-wait reads it.                                                                                   |
| `0x800f00` | 0xf00 | **RF link-layer command/trigger** (descriptive name `reg_rf_ll_cmd`) | med-high   | `rf_drv.h` does `write_reg8(0xf00, 0x80)` — the RF LL stop/reset/trigger byte at the base of the "linklayer registers: 0xf00" block. No SDK macro is defined for 0xf00 itself; it is the RF LL command/mode register.                                                                                  |
| `0x800f04` | 0xf04 | **RF TX settle time** (descriptive `reg_rf_tx_settle`, REG_ADDR16)   | med-high   | `rf_drv.h`: `write_reg16(0xf04, tx_stl_us-1)`. TX-settle timing in the 0xf00 RF LL block.                                                                                                                                                                                                              |
| `0x800f2c` | 0xf2c | **`reg_rf_fsm_timeout`** (REG_ADDR32)                                | **high**   | RF state-machine timeout in the 0xf00 RF LL block.                                                                                                                                                                                                                                                     |
| `0x800660` | 0x660 | **undocumented / reserved**                                          | **low**    | Not defined in B80, B85, B87, or pvvx 8258 register maps. Sits in the gap between the IRQ controller (0x640–0x64a) and the PMU/wakeup block (0x6e–0x6f). 4-byte stride (0x660/0x664/0x668 = three 32-bit words) suggests an internal/analog-test or undisclosed RF/baseband bank. Treat as unknown.    |
| `0x800664` | 0x664 | **undocumented / reserved**                                          | **low**    | See 0x660.                                                                                                                                                                                                                                                                                             |
| `0x800668` | 0x668 | **undocumented / reserved**                                          | **low**    | See 0x660.                                                                                                                                                                                                                                                                                             |
| `0x800643` | 0x643 | **`reg_irq_en`** (REG_ADDR8)                                         | **high**   | Global interrupt enable byte (`irq_disable()`/`irq_restore()` toggle this). Frequent read-modify-write around critical sections. It is byte 3 of the 32-bit `reg_irq_mask` @0x640, but the SDK exposes it as its own 8-bit `reg_irq_en`.                                                               |
| `0x800c2a` | 0xc2a | **`reg_dma_tx_rptr`** (REG_ADDR8)                                    | **high**   | DMA TX FIFO read pointer.                                                                                                                                                                                                                                                                              |
| `0x800c2b` | 0xc2b | **`reg_dma_tx_wptr`** (REG_ADDR8)                                    | **high**   | DMA TX FIFO write pointer. Paired with 0xc2a for the SW-managed DMA TX FIFO.                                                                                                                                                                                                                           |
| `0x800b10` | 0xb10 | **`reg_dfifo_mode`** (REG_ADDR8)                                     | **medium** | Audio DFIFO mode/enable in the 0xb00 DFIFO block. Unusual for a gamepad with no audio; plausible if the firmware repurposes a DFIFO path or the SDK init touches it unconditionally. If the surrounding code has no audio, re-examine — but the address is unambiguously `reg_dfifo_mode` in this SDK. |
| `0x800700` | 0x700 | **`reg_aes_ctrl`** (REG_ADDR8)                                       | **high**   | AES engine control (`FLD_AES_CTRL_CODEC_TRIG`/`DATA_FEED`/`CODEC_FINISHED`). Used for BLE link-layer encryption / key handling.                                                                                                                                                                        |
| `0x800708` | 0x708 | **`reg_aes_data`** (REG_ADDR32)                                      | **high**   | AES data in/out word.                                                                                                                                                                                                                                                                                  |
| `0x800710` | 0x710 | **`reg_aes_key(0)`** (REG_ADDR8, `reg_aes_key(v)=0x710+v`)           | **high**   | AES key byte 0.                                                                                                                                                                                                                                                                                        |
| `0x800711` | 0x711 | **`reg_aes_key(1)`**                                                 | **high**   | AES key byte 1. Contiguous key-load loop 0x710..0x71f.                                                                                                                                                                                                                                                 |

### Dongle image

| abs addr   | off   | identification                                                        | conf       | notes                                                                                                                                                                                                                          |
| ---------- | ----- | --------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `0x80009c` | 0x9c  | **`reg_uart_buf_cnt`** (REG_ADDR8)                                    | **medium** | UART RX/TX buffer byte-count (`FLD_UART_RX_BUF_CNT` [0:3], `FLD_UART_TX_BUF_CNT` [4:7]). Polled in NDMA UART. Fits a dongle that also talks UART (host bridge / pairing / debug). Only 0x9c stands apart from the USB cluster. |
| `0x800113` | 0x113 | **`reg_usb_ep3_ptr`**                                                 | **high**   | USB endpoint-3 FIFO pointer.                                                                                                                                                                                                   |
| `0x800114` | 0x114 | **`reg_usb_ep4_ptr`** (also base of `reg_usb_ep4567_ptr`, REG_ADDR32) | **high**   | USB endpoint-4 FIFO pointer.                                                                                                                                                                                                   |
| `0x80011b` | 0x11b | **`reg_usb_ep3_dat`**                                                 | **high**   | USB endpoint-3 FIFO data.                                                                                                                                                                                                      |
| `0x80011c` | 0x11c | **`reg_usb_ep4_dat`** (base of `reg_usb_ep4567_dat`)                  | **high**   | USB endpoint-4 FIFO data.                                                                                                                                                                                                      |
| `0x800123` | 0x123 | **`reg_usb_ep3_ctrl`**                                                | **high**   | USB endpoint-3 control (BUSY/STALL/DAT0/DAT1).                                                                                                                                                                                 |
| `0x800124` | 0x124 | **`reg_usb_ep4_ctrl`**                                                | **high**   | USB endpoint-4 control.                                                                                                                                                                                                        |

**Dongle takeaway:** the dongle is a **USB HID device using endpoints 3 and 4** (ptr/dat/ctrl triads at 0x113/0x11b/0x123 and 0x114/0x11c/0x124). EP3 is almost certainly the IN endpoint delivering gamepad reports to the console/PC; EP4 a second interrupt/OUT endpoint (rumble/LED/second interface). Endpoint 0 (control) lives at 0x100–0x106; the firmware also uses those during enumeration.

---

## Full block map (per-block highlights; all offsets from B80 `register.h`)

### System timer — base 0x740

| off               | abs      | name                                | meaning                                |
| ----------------- | -------- | ----------------------------------- | -------------------------------------- |
| 0x740             | 0x800740 | reg_system_tick                     | 32-bit free-running tick (hottest reg) |
| 0x744             | 0x800744 | reg_system_tick_irq_level           | tick-compare IRQ level                 |
| 0x748             | 0x800748 | reg_system_irq_mask                 | system-timer IRQ mask                  |
| 0x749             | 0x800749 | reg_system_cal_irq                  | 32k calibration IRQ                    |
| 0x74a             | 0x80074a | reg_system_ctrl                     | 32k cal mode/en, auto/manual timer en  |
| 0x74b             | 0x80074b | reg_system_status                   | 32k timer busy/state                   |
| 0x74c/0x750/0x754 | …        | reg_system_32k_tick_wt / _rd / _cal | 32k tick write/read/calib              |

### Legacy timers/watchdog — base 0x620

`reg_tmr_ctrl` @0x620 (32-bit: TMR0/1/2 en+mode, watchdog capture/en at bits 9–23), `reg_tmr_sta` @0x623, capture `reg_tmr{0,1,2}_capt` @0x624/0x628/0x62c, count `reg_tmr{0,1,2}_tick` @0x630/0x634/0x638. Watchdog enable also mirrored in `reg_wd_ctrl1` @0x622 bit7.

### Interrupt controller — base 0x640

`reg_irq_mask` @0x640 (32-bit `irq_list_e`), **`reg_irq_en` @0x643** (8-bit master enable), `reg_irq_pri` @0x644, `reg_irq_src` @0x648, `reg_irq_src3` @0x64a. A second "combined" GPIO/peripheral IRQ status is `reg_comb_irq` @0x56e.

### GPIO — base 0x500 (8 bytes per port; ports PA,PB,PC,PD,PE,PF)

Per port at `0x500 + 0x8*port`: `+0 in`, `+1 ie` (input-enable), `+2 oen` (output-enable, **active low**), `+3 out`, `+4 pol` (IRQ polarity), `+5 ds` (drive strength), `+6 gpio` (1=GPIO / 0=peripheral mux), `+7 irq_en` (per-pin IRQ/wakeup enable).

- PA 0x500–0x507, PB 0x508–0x50f, PC 0x510–0x517, PD 0x518–0x51f, PE 0x520–0x527, PF 0x528–0x52f.
- **PC exception:** PC `ie`/`pe`(pull)/`ds` are analog-domain (`areg_gpio_pc_ie=0xc0`, `pe=0xc1`, `ds=0xc2`), not the digital byte.
- Reading an input pin = `reg_gpio_pX_in` (e.g. a VBUS/charger-sense pin is read here).
- IRQ/wakeup plumbing: `reg_gpio_irq_from_pad` 0x56f, `reg_gpio_wakeup_irq` 0x574 (`FLD_GPIO_CORE_WAKEUP_EN` bit1, `FLD_GPIO_CORE_INTERRUPT_EN` bit2), `reg_gpio_irq_sel` 0x575, `reg_gpio_irq_pad_mask` 0x576, `reg_gpio_irq_lvl` 0x577; RISC0/1/2 group enables at 0x530/0x538/0x540 + port.
- **USB pins (B80): DP = PA2, DM = PA1.** So raw USB line state = `reg_gpio_pa_in` bits 2 (DP) / 1 (DM).

### ADC / SAR — analog-domain (via analog port), config in `adc.h`

The SAR ADC has only the "MISC" channel; all control is through analog registers:
`areg_adc_vref 0xea`, `areg_adc_ain_chn_misc 0xeb` (positive/negative input select), `anareg_adc_res_m 0xec` (resolution, diff-chan en), `areg_adc_tsmaple_m 0xee` (sample time), `areg_r_max_mc 0xef`, `areg_r_max_s 0xf1`, `areg_adc_chn_en 0xf2`, `adc_data_sample_control 0xf3` (`NOT_SAMPLE_ADC_DATA` bit0), `areg_adc_sampling_clk_div 0xf4`, `areg_adc_misc_l/h 0xf7/0xf8` (result low/high), `areg_adc_vref_vbat_div 0xf9` (VBAT divider select), `areg_ain_scale 0xfa`, `areg_adc_pga_ctrl 0xfc` (SAR power-down bit5).
**VBAT sensing:** positive input `VBAT` with `ADC_VBAT_DIVIDER_1F4` (÷4); `adc_vbat_channel_init()` measures the supply/battery rail. See VBUS section.

### Analog indirect port — base 0xb8

`reg_ana_addr 0xb8` / `reg_ana_data 0xb9` / `reg_ana_ctrl 0xba` (`reg_ana_addr_data`=16-bit@0xb8, `reg_ana_ctrl32`=32-bit@0xb8). `reg_ana_ctrl` bits: `FLD_ANA_BUSY` 0, `FLD_ANA_RW` 5, `FLD_ANA_START` 6, `FLD_ANA_CYC` 7. **Every `analog_read`/`analog_write` (ADC config, PMU, deep-sleep, pad pulls, VBAT divider, comparator, VBUS/charge detect) funnels through this port** — in the disassembly it appears as writes to 0xb8/0xba and reads of 0xb9, not as distinct absolute addresses. Watch this port to recover analog-register accesses.

### USB — base 0x100

Control EP0: `reg_ctrl_ep_ptr 0x100`, `reg_ctrl_ep_dat 0x101`, `reg_ctrl_ep_ctrl 0x102`, `reg_ctrl_ep_irq_sta 0x103`, `reg_ctrl_ep_irq_mode 0x104`. `reg_usb_ctrl 0x105`, `reg_usb_cyc_cali 0x106`. Device/host state: `reg_usb_mdev 0x10a` (`FLD_USB_MDEV_SELF_PWR` bit0, `FLD_USB_MDEV_SUSP_STA` bit1 = suspend status), `reg_usb_host_conn 0x10b`. Endpoint enable `reg_usb_ep_en 0x10e`. Data EPs 1–8 arranged as four parallel banks:
`ptr 0x110–0x117`, `dat 0x118–0x11f`, `ctrl 0x120–0x127`, `buf_addr 0x128–0x12f` (index order: ep8,1,2,3,4,5,6,7). `reg_usb_ram_ctrl 0x130`, `reg_usb_iso_mode 0x138`, `reg_usb_irq 0x139`, `reg_usb_mask 0x13a`, `reg_usb_ep_max_size 0x13e`.

### PWM — base 0x780

`reg_pwm_enable 0x780` / `reg_pwm0_enable 0x781`, `reg_pwm_clk 0x782`, `reg_pwm0_mode 0x783`, `reg_pwm_invert 0x784`, `reg_pwm_n_invert 0x785`, `reg_pwm_pol 0x786`, per-channel `reg_pwm_cycle(i)/cmp(i)/max(i)` @0x794+`i*4`, `reg_pwm0_pulse_num 0x7ac`, `reg_pwm_irq_mask 0x7b0`, `reg_pwm_irq_sta 0x7b1`. (Rumble-motor or LED PWM would live here.)

### AES — base 0x700

`reg_aes_ctrl 0x700`, `reg_aes_data 0x708` (32-bit), `reg_aes_key(v) 0x710+v`.

### DMA — base 0xc00

Channel descriptors at 0xc00 (uart-rx), 0xc04 (uart-tx), 0xc08 (rf-rx), 0xc0c (rf-tx), 0xc18 (pwm). Control: `reg_dma_chn_en 0xc20`, `reg_dma_chn_irq_msk 0xc21`, ready flags 0xc24–0xc27, `reg_dma_rx_rptr 0xc28`, `reg_dma_rx_wptr 0xc29`, **`reg_dma_tx_rptr 0xc2a`**, **`reg_dma_tx_wptr 0xc2b`**, `reg_dma_tx_fifo 0xc2c`.

### DFIFO / audio — base 0xb00

`reg_dfifo0_addr 0xb00`, sizes/levels 0xb02–0xb0f, **`reg_dfifo_mode 0xb10`**, `reg_dfifo_ain 0xb11`, `reg_mic_ctrl 0xb12`, `reg_dfifo_irq_status 0xb13`.

### RF baseband / link layer

- Baseband: `reg_rf_acc_len 0x405`, `reg_rf_timestamp 0x450` (32-bit).
- Link-layer block base 0xf00: `reg_rf_ll_cmd`(0xf00, descriptive), `reg_rf_ll_ctrl_0 0xf02`, `reg_rf_ll_ctrl_1 0xf03`, `reg_rf_tx_settle`(0xf04, descriptive, 16-bit), `reg_rf_rx_timeout 0xf0a`, `reg_rf_ll_ctrl_2 0xf15`, `reg_rf_ll_ctrl_3 0xf16`, `reg_rf_irq_mask 0xf1c`, `reg_rf_irq_status 0xf20`, `reg_rf_fsm_timeout 0xf2c` (32-bit), `reg_rf_ll_wifi_coex 0xf30`.
- Analog RF ("aura") block base 0x1200 (MI fractional tuning, mode cfg).
- **Note (pm.h):** after suspend, the RF register banks at **0x400, 0xf00, 0x1200 return to defaults** and must be re-inited — expect the firmware to rewrite 0xf00/0xf04 after every wake.

### Reset / clock / PMU trigger — base 0x60

`reg_rst0 0x60` / `reg_rst1 0x61` / `reg_rst2 0x62` (peripheral resets), `reg_clk_en0 0x63` / `reg_clk_en1 0x64` / `reg_clk_en2 0x65` (peripheral clock gates), `reg_clk_sel 0x66`. **`reg_wakeup_en 0x6e`** and **`reg_pwdn_ctrl 0x6f`** — see deep-sleep section. `reg_mcu_wakeup_mask 0x78` (32-bit).

### Single-wire (SWS) — base 0xb0

`reg_swire_data 0xb0`, **`reg_swire_ctl 0xb1`** (`FLD_SWIRE_USB_DET` bit6, `FLD_SWIRE_USB_EN` bit7 — see VBUS section), `reg_swire_ctl2 0xb2`, `reg_swire_id 0xb3`.

### Keyscan — base 0x800 (in-chip keyscan matrix, not related to the 0x800000 window base)

`reg_ks_col_mask0 0x800`, `reg_ks_row_sel0 0x804`, `reg_ks_en 0x80a` (KS/clk/IE/reset bits), `reg_ks_irq 0x80c`, `reg_ks_key 0x810`. (A button-matrix controller could use this; the Ultimate 2C more likely reads discrete GPIOs.)

---

## CRITICAL: VBUS / cable / charger-presence detection

**Bottom line:** the B80/825x family exposes **no single dedicated "VBUS present / 5 V-detect" status bit** in the open register map. A _dumb_ charger (VBUS 5 V, D+/D− idle, no enumeration) is sensed by one of the mechanisms below; for the "powers on when dropped on a dumb charger" behavior the realistic candidates are #5/#6 (a board VBUS/charger-status GPIO, and/or the chip simply cold-booting when VBUS powers its LDO), optionally armed through the deep-sleep pad-wakeup path.

1. **USB-core wakeup — data-dependent, does NOT fire for a dumb charger.**
   `reg_wakeup_en 0x6e`: `FLD_WAKEUP_SRC_USB` = **bit2**, `FLD_WAKEUP_SRC_USB_RESM` (resume) = **bit6**. Enum `PM_WAKEUP_CORE_USB` in pm.h. Requires USB SE0/resume/SOF traffic — a dumb charger provides none, so this cannot detect it. Suspend status readable at `reg_usb_mdev 0x10a` bit1 / `reg_usb_host_conn 0x10b`.

2. **SWS "USB detect" status bit.** `reg_swire_ctl 0xb1`: **`FLD_SWIRE_USB_DET` = bit6** (status), `FLD_SWIRE_USB_EN` = bit7 (enable). Tied to the "DP-through-SWS" mux feature (`dp_through_swire_en()` toggles 0xb1 bit7 in `usbhw.c`). Reflects DP-line activity routed through the single-wire pin, **not** a raw 5 V rail comparator. Low likelihood as the primary charger sense, but worth checking if the firmware reads 0xb1 bit6.

3. **DP/DM line state as GPIO.** DP=PA2, DM=PA1. Read `reg_gpio_pa_in` bit2/bit1. The internal 1.5 kΩ DP pull-up is enabled by `usb_dp_pullup_en()` → **`analog_write(0x0b, … | BIT(7))`** (analog register **0x0b bit7**). With DP pulled up, host-side terminations vs. a dumb charger (D+/D− shorted or floating) give distinguishable line patterns. Indirect; not the usual "is-power-connected" test.

4. **ADC on the supply/battery rail (VBAT).** `adc.h`: `VBAT` positive channel + `ADC_VBAT_DIVIDER_1F4` (÷4), `adc_vbat_channel_init()`, result via `areg_adc_misc_l/h` (analog 0xf7/0xf8). When a charger raises the battery/charge node, the sampled voltage rises and firmware infers "charging". Measures the battery/charge rail, not VBUS directly — unless the board wires VBUS through its own divider to an ADC-capable pin.

5. **Low-power comparator (LPC) — the built-in "sense an external voltage / wake on it" path.** `lpc.h`: inputs **PB1–PB7**, references ≈810–972 mV or PB0/PB3/AVDD3, input scaling 25/50/75/100 %. **Result = `analog_read(0x88) & BIT(6)`** (analog reg **0x88 bit6**, `lpc_get_result()`). Wakeup status `WAKEUP_STATUS_COMPARATOR` = pm.h **bit0**. A VBUS resistor-divider into a PB pin lets the LPC threshold-detect "5 V present" and wake the chip from deep sleep — the family's cleanest true analog VBUS-sense route.

6. **Board GPIO from VBUS divider or charger-IC status (the real-world method).** A TP4054-class charger's open-drain **CHG#/STDBY** pin, or VBUS through a divider, is routed to a plain GPIO; firmware reads it via `reg_gpio_pX_in` (0x500 + 0x8·port). This is how "cable plugged / charging / charged" is normally known on these controllers. The pad can also be armed as a **deep-sleep pad-wakeup source** (see below) so applying VBUS wakes the MCU; or, more simply, VBUS powers the board LDO and the MCU **cold-boots**, then reads the sense GPIO plus the wakeup-status to decide to turn on and show the charge LED.

**How SDK example code reads "is the cable in / charging":** Telink 825x HID reference apps do one (or more) of: poll a configured VBUS/charge-sense GPIO with `gpio_read()` in the main loop; enable `usb_dp_pullup_en()` and check DP; or watch USB suspend/SOF (`reg_usb_mdev`/500 ms SOF check) for an enumerating host. On assertion → enter "charging"/stay-awake and drive the LED/PWM; on deassertion → allow suspend/deep-sleep/off. There is no library `usb_get_vbus()` primitive in this SDK — detection is always board-specific GPIO/ADC/LPC as above.

---

## Deep-sleep / power-off path ("turn the controller off")

The sleep entry itself (`cpu_sleep_wakeup*()`, `sleep_start()`) is in the closed `libdriver_b80.a`, but the register/bit effects are fully defined in the open headers:

- **Digital sleep trigger — `reg_pwdn_ctrl 0x6f`:** `FLD_PWDN_CTRL_SLEEP` = **bit7** (enter sleep), `FLD_PWDN_CTRL_REBOOT` = **bit5** (0x20). pm.h states a failed deep-wake "will reboot by core_6f = 0x20". Writing **0x80** here is the "go to sleep" trigger; **0x20** forces a reboot. "Power off" = writing this after selecting the deepest mode.
- **Sleep mode select — `SleepMode_TypeDef` (B80):** `SUSPEND_MODE=0x00`, `DEEPSLEEP_MODE=0x30`, `SHUTDOWN_MODE=0x40`, `DEEPSLEEP_MODE_RET_SRAM_LOW16K=0x01`. (8258 values differ: SUSPEND=0, DEEP=0x80.) The mode byte is programmed into the PMU/analog control alongside the 0x6f trigger. **SHUTDOWN (0x40)** is effectively "off" — only a pad edge or power-cycle brings it back.
- **Wakeup-source enables — `reg_wakeup_en 0x6e`:** PAD/GPIO = **bit3** (`FLD_WAKEUP_SRC_GPIO`), USB = bit2, plus RM/RESM/RST variants. `PM_WAKEUP_PAD/PM_WAKEUP_TIMER/PM_WAKEUP_CORE_*` in pm.h map onto these.
- **`cpu_set_gpio_wakeup(pin, pol, en)`:** arms one pad as a deep-sleep wakeup with polarity. Because deep sleep powers the digital core down, the enable+polarity are latched in the **analog (always-on) domain**, so they persist across the sleep. (This is the call that would wire a VBUS/charge-sense GPIO or the power button to wake/boot the part.)
- **Pad hold resistors during sleep — analog regs 0x0e–0x16** (`gpio.c` `gpio_analog_resistance_init`): per-pin pull-up/pull-down = `PULL_WAKEUP_SRC_Pxx`. `analog_write(0x0e)`=PA0–3, `0x0f`=PA4–7, `0x10`=PB0–3, `0x11`=PB4–7, `0x12`=PC0–3, `0x13`=PC4–7, `0x14`=PD0–3, `0x15`=PD4–7, `0x16`=PF0–1. These hold pad levels so an external edge (button, VBUS) can wake the chip.
- **Deep-sleep retention analog registers (survive with the digital core off), pm.h:**
  - `DEEP_ANA_REG0 0x3a`, `REG1 0x3b`, `REG2 0x3c` — reset only by **power cycle**. `0x3a` bit1/bit2 = xtal/PLL start-fail flags (system-reserved). Firmware storing "why did I boot / stay-on flag" across a power-off would use these.
  - `DEEP_ANA_REG6 0x35` … `REG10 0x39` — reset by watchdog/chip-reset/RESET-pin/power-cycle; hold across deep-sleep-with-retention.
- **Wakeup status after resume:** `pm_get_wakeup_src()` / `pmParam.wakeup_src`; bits `WAKEUP_STATUS_PAD`/`_CORE`/`_TIMER` (`_COMPARATOR` on 8258). `pm_is_deepPadWakeup()` distinguishes a pad-edge wake (e.g. VBUS/button) from timer.

**So "turn off" compiles to:** quiesce peripherals (`reg_rst*`/`reg_clk_en*` at 0x60–0x65), program pad pulls (analog 0x0e–0x16) + `reg_wakeup_en 0x6e` + per-pad analog wakeup enable, optionally stash a flag in analog 0x35–0x3c, then write the mode + **`reg_pwdn_ctrl 0x6f` bit7** to drop into suspend/deepsleep/shutdown. Re-entry re-inits RF (0x400/0xf00/0x1200) and re-reads the wakeup source.

---

## Confidence summary for your 18 addresses

High: 0x740, 0xf2c, 0x643, 0xc2a, 0xc2b, 0x700, 0x708, 0x710, 0x711, and dongle 0x113/0x114/0x11b/0x11c/0x123/0x124.
Med-high: 0xf00, 0xf04 (RF LL cmd / TX-settle; SDK defines no macro exactly at these two offsets, identification via `rf_drv.h` writes).
Medium: 0xb10 (`reg_dfifo_mode` — address certain, audio use surprising for a pad), 0x9c (`reg_uart_buf_cnt`).
Low / unknown: 0x660, 0x664, 0x668 (not in any Telink/pvvx public register map).
