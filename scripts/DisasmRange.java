import ghidra.app.script.GhidraScript;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.listing.Instruction;

// Disassembles [lo,hi) (following flow) and prints each instruction. Args: lo(hex) hi(hex).
public class DisasmRange extends GhidraScript {
    @Override
    public void run() throws Exception {
        long lo = Long.parseLong(getScriptArgs()[0].toLowerCase().replace("0x", ""), 16);
        long hi = Long.parseLong(getScriptArgs()[1].toLowerCase().replace("0x", ""), 16);
        new DisassembleCommand(toAddr(lo), null, true).applyTo(currentProgram, monitor);
        Instruction ins = getInstructionAt(toAddr(lo));
        while (ins != null && ins.getAddress().getOffset() < hi) {
            StringBuilder ops = new StringBuilder();
            for (int i = 0; i < ins.getNumOperands(); i++) {
                if (i > 0) ops.append(", ");
                ops.append(ins.getDefaultOperandRepresentation(i));
            }
            println(String.format("%s  %-8s %s", ins.getAddress(), ins.getMnemonicString(), ops));
            ins = ins.getNext();
        }
    }
}
