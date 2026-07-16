# Findings

Reverse-engineering results for the 8BitDo Ultimate 2C, produced from the symbolicated disassembly (controller `ctrl-v109`, dongle `dongle-v103`) plus web research. Addresses are IMAGE addresses (controller file offset = img − 0x6000; the vendor `.dat` additionally prepends the 28-byte ebitdo header).

- **`FINDINGS.md`** — the authoritative synthesis. Every claim was independently re-traced (adversarial verify pass); refuted/downgraded claims are flagged. **Trust this over the raw dimension reports where they differ.**
- **`analysis-{charging,btff,buttons,iap}.md`** — raw per-dimension finder reports. Some claims here were later refuted or downgraded during verification — read alongside the matching `verify-*.md` and `FINDINGS.md`.
- **`verify-{charging,btff,buttons,iap}.md`** — adversarial verification verdicts (CONFIRMED / REFUTED / UNPROVEN per claim).
- **`register-map.md`, `regmap.tsv`** — Telink B80 peripheral register map (source-cited). `regmap.tsv` (`name<TAB>0xADDR`) is the input to `scripts/symbolicate.py`.
- **`flashing-options.md`, `flash-angle-{1..4}.md`** — flashing-feasibility research (IAP protocol, bootloader/signing, SWS hardware, flash layout).

Report bodies reference the session scratchpad paths the analysis ran in; those paths are ephemeral, the addresses/content are not.
