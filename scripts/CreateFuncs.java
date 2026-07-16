import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

// Creates functions at TC32 `push {..,lr}` prologues (low byte 0xB5) in [lo,hi) — recovers library routines the call-graph walk missed. Disassembles the entry if needed. Args: lo(hex) hi(hex).
public class CreateFuncs extends GhidraScript {
    @Override
    public void run() throws Exception {
        long lo = Long.parseLong(getScriptArgs()[0].toLowerCase().replace("0x", ""), 16);
        long hi = Long.parseLong(getScriptArgs()[1].toLowerCase().replace("0x", ""), 16);
        int made = 0, tried = 0;
        for (long a = lo; a < hi; a += 2) {
            int b1 = currentProgram.getMemory().getByte(toAddr(a + 1)) & 0xff;
            if (b1 != 0xB5) continue;
            Address ad = toAddr(a);
            if (getFunctionContaining(ad) != null) continue;
            tried++;
            if (getInstructionAt(ad) == null) {
                new DisassembleCommand(ad, null, true).applyTo(currentProgram, monitor);
            }
            if (getInstructionAt(ad) != null) {
                Function f = createFunction(ad, null);
                if (f != null) made++;
            }
        }
        println("CREATEFUNCS tried=" + tried + " made=" + made
            + " total=" + currentProgram.getFunctionManager().getFunctionCount());
    }
}
