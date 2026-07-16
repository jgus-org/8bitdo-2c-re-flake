import ghidra.app.script.GhidraScript;
import ghidra.app.plugin.assembler.Assembler;
import ghidra.app.plugin.assembler.Assemblers;
import ghidra.program.model.address.Address;
import java.nio.file.Files;
import java.nio.file.Paths;

// Assembles TC32 instructions (one per line, arg1 file; ';' comments) starting at base (arg0 hex), resolving PC-relative operands per address. Emits per-line bytes and a concatenated SHIM_HEX. Args: base(hex) lines-file.
public class Assemble extends GhidraScript {
    @Override
    public void run() throws Exception {
        long base = Long.parseLong(getScriptArgs()[0].toLowerCase().replace("0x", ""), 16);
        Assembler asm = Assemblers.getAssembler(currentProgram);
        StringBuilder all = new StringBuilder();
        long addr = base;
        for (String raw : Files.readAllLines(Paths.get(getScriptArgs()[1]))) {
            String line = raw.trim();
            if (line.isEmpty() || line.startsWith(";")) continue;
            Address a = toAddr(addr);
            try {
                byte[] b = asm.assembleLine(a, line);
                StringBuilder hx = new StringBuilder();
                for (byte x : b) hx.append(String.format("%02x", x & 0xff));
                println(String.format("0x%05x  %-22s %s", addr, line, hx));
                all.append(hx);
                addr += b.length;
            } catch (Exception e) {
                println(String.format("0x%05x  %-22s ASM-ERROR: %s", addr, line, e.getMessage()));
            }
        }
        println("SHIM_HEX " + all);
    }
}
