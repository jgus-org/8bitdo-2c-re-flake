# 8BitDo Ultimate 2C — BT vs 2.4GHz + Force-Feedback (Goals 2 & 4)

Controller: `ctrl-v109` (base 0x6000, len 74752, img end 0x18400). Dongle: `dongle-v103`. All addresses are IMAGE addresses (file offset = img − 0x6000).

## TL;DR decisions

- **Motor driver = `FUN_0000f93c` @0xf93c** — scales 0-100 strength → PWM duty, writes `reg_pwm_cmp` of **PWM4=0x8007a4 / PWM5=0x8007a8**, period max=10000. Fed by setter **`FUN_0000fa68` @0xfa68** (stores target into RAM globals) → applier **`FUN_0000faa0` @0xfaa0** (called every main-loop pass at 0xa43c). PWM4/5 = the two rumble motors; PWM0 (0x800794) = LED. [VERIFIED]
- **Rumble target is set in exactly one place: `FUN_0000fa68`.** Every caller is a USB-EP output-report parser, the 2.4GHz RF command queue, or an internal buzz/pattern generator. **No BLE/Bluetooth code path calls it.** [VERIFIED]
- **Goal 4 verdict — BT-mode FF is BROKEN as case (ii), NOT case (i).** The Bluetooth HID report map (`0x1734c`) **does** declare a rumble OUTPUT report (Report ID 5, PID page 0x0F, 4×u8 0-100), and the BLE GATT server **does** expose a writable Output-Report characteristic (buffer RAM `0x84315c`, props 0x0E). But that attribute's ATT **write callback is NULL** and its value buffer is **referenced only inside the attribute table — never read by any code**. Host rumble writes land in RAM and are silently dropped.
- **Goal 2 verdict — the charge/power gate is mode-independent (shared).** Power management and the rumble applier live in the transport-agnostic main loop (0xa430–0xa48c); the radio "mode" only selects which stack is live and (via `FUN_0000d7c8`) which rumble-intensity curve is used. The BT path inherits the same "won't power off while charging" behavior. [INFERRED, med-high]

## 1. Force-feedback chain

- **`FUN_0000f93c` @0xf93c** `motor_set(strength 0..100, channel 0/1)`: `f946` if strength==0 → off path; else `f9c2` computes duty using `FUN_0000d7c8()` (byte @SRAM 0x843470) to pick a curve — `r0!=0`: `cmp=(s*45)/255+13` (low-power), else `cmp=(s*80)/255+20` (full-power); writes `reg_pwm{4,5}_cycle = (max<<16)|(cmp*100)`. Pools: `0xfa04=0x27100000` (max=10000), `0xfa08=0x008007a8` (PWM5, ch0), `0xfa0c=0x008007a4` (PWM4, ch1). [VERIFIED]
- **`FUN_0000fa68` @0xfa68** `rumble_set(motorA, motorB, duration)` → RAM globals **0x8434ef / 0x8434f0 / 0x8434f1**. Exhaustive pool search proves these globals are written ONLY here. Single choke point for all rumble. [VERIFIED]
- **`FUN_0000faa0` @0xfaa0** rate-limits on `reg_system_tick`, then `FUN_0000f93c(motorA,0)` + `(motorB,1)`. **Called from the main loop @0xa43c** — output runs continuously, transport-independently. [VERIFIED]
- **`FUN_0000fa10`** PWM init: `reg_pwm_clk=0x17`, muxes 2 GPIO pins to PWM, programs `reg_pwm{4,5}_cycle = 10000<<16|0`, enables PWM4/5 via `reg_pwm_enable 0x800780 |0x10 |0x20`. [VERIFIED]

## 2. Per-transport rumble receive paths

| Parser         | @      | Recognizes                                | Motors at     | Reached from                                                      | Transport              |
| -------------- | ------ | ----------------------------------------- | ------------- | ----------------------------------------------------------------- | ---------------------- |
| `FUN_0000f684` | 0xf684 | hdr `81 11 04 08` (Report ID 0x81 vendor) | buf[7],buf[8] | `FUN_0000f828`←0xaa34/0xaa6e (USB EP)                             | **Wired USB (vendor)** |
| `FUN_0000eabc` | 0xeabc | buf[1]==8                                 | buf[3],buf[4] | 0xa9e0 in `FUN_0000a90c` (USB EP-OUT, EP-IRQ bits 0x10/0x20/0x40) | **Wired USB**          |
| `FUN_0000dc58` | 0xdc58 | cmd type 4                                | buf[6],buf[7] | dispatcher `FUN_0000a328` (0xa362) ← main loop 0xa49e             | **2.4GHz RF**          |

- 2.4GHz path confirmed RF: `FUN_0000a328` dispatches on RAM global **0x8434cc**, written from the RF-IRQ region (ref @0x6c88, adjacent to `reg_rf_irq_status`=0x800f20 accesses @0x6c80). RF-RX enqueues → main loop dispatches type==4 → `FUN_0000dc58` → `FUN_0000fa68`.
- Internal buzzes also hit `FUN_0000fa68`: startup/pair pattern SM @0xcf00 (100,100,300 / 0,0,300), notification buzzes @0xa0f8/0xdaa8 (60,60,20), disconnect-stop @0xa4ae (0,0,0). Mode-agnostic.
- **Dongle relay confirmed** by symbol strings `setVibration_handle_timer` (@0xf6d8) and `timer left_vibration : %x - %x - %x` (@0xf780) in the dongle's USB-mode logic (`init_usb_xinput`/`USB_MODE_XINPUT` @0xde60 — dongle enumerates XInput; host rumble arrives on the XInput OUT path, relayed over RF). [VERIFIED]
- **None of the three parsers, nor `FUN_0000fa68`, is reached from the BLE stack.**

## 3. Mode selector

- **Wired vs wireless**: USB-presence driven (Telink standard); GET_DESCRIPTOR handler ~0xe7c0 returns the wired HID descriptors; keys off USB/VBUS state (DP=PA2/DM=PA1, `reg_usb_mdev` 0x80010a).
- **Mode/profile byte @ SRAM `0x843470`** (`FUN_0000d7c8` getter @0xd7c8; pool refs 0xd668/0xd7bc/0xd7d0/0xd8d8): selects rumble curve (§1) and gates a main-loop branch @0xa44c. Writers sit in the 0xd5xx–0xd8xx connection/state block. **Exact value→mode (2.4G/BT/wired) mapping not fully decoded this pass — unresolved.**
- BLE name `8BitDo Ultimate 2C Wireless` (@0x172dc); secondary `Telink Remote` (@0x18135). Full HID-over-GATT ⇒ BT is a real runtime mode. [VERIFIED]
- Main loop (0xa430–0xa48c) that runs power mgmt + `FUN_0000faa0` is shared across modes; mode only switches the active radio stack ⇒ charge/stay-awake gate not duplicated per mode. [INFERRED]

## 4. HID / BT descriptors (crux of Goal 4)

| img         | Root usage | Role                                            | Rumble OUTPUT?                                          |
| ----------- | ---------- | ----------------------------------------------- | ------------------------------------------------------- |
| **0x1734c** | Gamepad    | **BLE HID Report Map** (ATT attr, len 0x74=116) | **YES — Report ID 5, PID page**                         |
| 0x17b74     | Gamepad    | Wired-USB / 2.4GHz DInput (== dongle 0xf334)    | No PID report; LED-page outputs + vendor Report ID 0x81 |
| 0x17c60     | Keyboard   | wired composite                                 | LED out only                                            |
| 0x17cbb     | Mouse      | wired composite                                 | none                                                    |

- **4.1 [VERIFIED]** BT descriptor 0x1734c rumble bytes @0x173af: `05 0f 09 70 85 05 15 00 25 64 75 08 95 04 91 02 c0` = Usage Page 0x0F (PID) · Usage 0x70 · **Report ID 5** · LogMin 0 · LogMax 100 · Size 8 · Count 4 · **OUTPUT(Data,Var,Abs)**. → 4 rumble bytes 0-100. This block is the value of the ATT Report-Map char (0x2A4B), idx35, val ptr 0x1734c, attrLen 0x74 (length nails identity). Same map also carries a Battery field (BT-mode gamepad).
- **4.2 [VERIFIED]** BLE GATT HID service (ATT table from 0x17454, 24-byte entries {hdr, attrLen, uuid\*, value\*, wCB, rCB}):
  - idx24 @0x17694: props 0x12 read+notify, 0x2A4D, RAM 0x843170 (2B) — input
  - idx28 @0x176f4: props 0x12 read+notify, 0x2A4D, RAM 0x843148 (8B) — main gamepad input
  - **idx31/32 @0x1773c/0x17754: props 0x0E read+write+writeNR, 0x2A4D, RAM 0x84315c — writable OUTPUT report (rumble)**
  - idx35: 0x2A4B Report-Map (0x1734c); idx39: 0x2A4C HID control point.
- **4.3 [VERIFIED] The write is never processed.** Every ATT entry's write-callback field (word4, off +16) = 0x00000000, incl. idx32, protocol-mode (idx16), boot-kbd-out (idx21), control-point (idx39). Null callback ⇒ Telink SDK default = `memcpy(pAttrValue,payload,len)` and nothing else. Exhaustive search for pointer `0x0084315c` finds one hit @0x17760 = idx32's own `value*` field inside the table; **no code reference anywhere.** Clincher: the only writer of rumble globals (0x8434ef/f0) is `FUN_0000fa68`, and no caller is BLE.
- **⇒ BT FF missing = case (ii): output report declared AND writable characteristic exists, but firmware installs no handler and never consumes the bytes. NOT case (i).**

## 5. Patch proposal — route BT output reports to the motor driver

Goal: make an ATT Write to the Output-Report characteristic (idx32, buffer 0x84315c) call `FUN_0000fa68(dataA, dataB, 0)`. Downstream (fa68→faa0→f93c→PWM4/5) is already functional and mode-independent, so only the BLE→fa68 hop is needed.

- **Option A (surgical — install the missing ATT write callback):**
  1. Hook point: entry idx32 @0x17754; write-callback field = word at **flash img 0x17764** (currently `00 00 00 00`).
  2. Shim in the zeroed image tail (396 free 0x00 bytes at **0x18274–0x18400**, e.g. @0x18280). ABI = Telink att write cb `(u16 connHandle r0, rf_packet_att_write_t *p r1)`:
     ```
     push {lr}
     ldrb r2,[r1,#VOFF]      ; motorA = value[0]
     ldrb r3,[r1,#VOFF+1]    ; motorB = value[1]
     mov  r0,r2 ; mov r1,r3 ; movs r2,#0   ; duration=0
     bl   0xfa68             ; FUN_0000fa68 (BL relative to shim)
     movs r0,#0 ; pop {pc}
     ```
  3. Byte change: write shim addr `|1` LE into flash **0x17764** (shim @0x18280 ⇒ `81 82 01 00`).
  4. Recompute the ebitdo CRC (gate is CRC-only, no signature); shim fits inside 0x18400 so `dest_len` likely unchanged.
  - **Caveats to bench-verify:** (a) that this SDK honors `attribute_t.w` at off+16 (all entries null, never seen exercised) — validate by tracing the Telink `l2cap_att_handler`/`hids` path or empirically; (b) exact `value` offset `VOFF` in the write packet (Telink typically ~8 bytes after the L2CAP/att header + 2-byte handle). Resolve both by writing known BLE bytes and reading 0x84315c / motor via SWS.
- **Option B (robust — poll the buffer from the shared main loop):** if per-attribute callbacks aren't honored, redirect one main-loop `bl` slot (0xa474–0xa488) to a shim that reads the 4 bytes @0x84315c and, on change, calls `FUN_0000fa68(buf[0],buf[1],0)`. Bypasses the callback ABI entirely; reuses the verified default-copy behavior; add a last-value byte to avoid re-triggering.

---

## Summary (~250 words)

The controller's force-feedback back end is fully intact and transport-neutral: a motor driver `FUN_0000f93c` (@0xf93c) converts a 0-100 strength to a PWM duty on the two rumble channels **PWM4 (reg 0x8007a4)** and **PWM5 (reg 0x8007a8)** (period 10000); a setter `FUN_0000fa68` (@0xfa68) stashes the target in RAM globals 0x8434ef/f0; and an applier `FUN_0000faa0` (@0xfaa0) drives both motors every pass of the shared main loop (called @0xa43c). Rumble reaches the setter from **wired USB** (parsers `FUN_0000f684` and `FUN_0000eabc`, off the USB endpoints) and from **2.4GHz RF** (`FUN_0000dc58`, off the RF-IRQ command queue at global 0x8434cc); the dongle's `setVibration_handle_timer`/`left_vibration` symbols confirm it relays host rumble over RF. Crucially, **no Bluetooth code path calls the setter**. Bluetooth mode uses a _different_ HID report map (0x1734c) that _does_ declare a rumble output report (Report ID 5, PID usage page 0x0F, 4×u8 0-100), and the BLE GATT service _does_ expose a writable Output-Report characteristic (buffer RAM 0x84315c, props 0x0E) — but its ATT write callback is NULL and the buffer is referenced only inside the attribute table, never read by code. So BT rumble writes are accepted and silently dropped. The charge/power gate lives in the shared main loop, so BT inherits the same charging behavior. The fix is a single BLE→`fa68` hop: install a write callback on the output-report attribute (patch flash 0x17764) or poll 0x84315c in the main loop.

### Most load-bearing claims (for independent verification)

- **[VERIFIED, 0.9]** Motor driver = `FUN_0000f93c` @0xf93c writing duty into `reg_pwm4 0x8007a4` / `reg_pwm5 0x8007a8` (period 10000); enabled by `FUN_0000fa10` via `reg_pwm_enable 0x800780` bits 4/5. PWM0 (0x800794) is the LED.
- **[VERIFIED, 0.85]** All rumble funnels through `FUN_0000fa68` @0xfa68 (RAM globals 0x8434ef/f0), applied from the main loop via `FUN_0000faa0` @0xfaa0; its callers are USB-EP parsers (0xf684/0xeabc) and the 2.4GHz RF command path (0xdc58) — none in the BLE stack.
- **[VERIFIED, 0.9]** The Bluetooth HID report map @0x1734c declares a rumble OUTPUT report: Report ID 5, PID page 0x0F, 4×u8 (0-100), bytes `... 85 05 ... 75 08 95 04 91 02` @0x173af (it is the ATT Report-Map characteristic value, attrLen 0x74).
- **[VERIFIED, 0.8]** The BLE GATT HID service exposes a writable Output-Report characteristic (idx31/32 @0x17754, props 0x0E, buffer RAM 0x84315c) whose ATT write callback (flash 0x17764) is NULL, and 0x84315c is referenced only inside the attribute table — no code consumes it.
- **[VERIFIED/INFERRED, 0.8]** Therefore BT-mode FF is case (ii): declared-but-ignored (a rumble output report IS present in the BT descriptor).
- **[INFERRED, 0.7]** The charge/power-off gate is mode-independent (shared main loop; mode byte 0x843470 only selects the rumble curve + minor branches), so the BT path has the same charging==on behavior; exact 0x843470 value→mode mapping is unresolved.
