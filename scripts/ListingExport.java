import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.mem.Memory;
import java.io.FileWriter;
import java.io.PrintWriter;

// Dumps the full disassembly listing (address, mnemonic, operands, and any 0x800xxx pool value the instruction's PC-relative load reaches) — the ground truth for functions whose decompilation is unreliable. Function boundaries are marked. Arg 0 = output dir.
public class ListingExport extends GhidraScript {
    @Override
    public void run() throws Exception {
        String out = getScriptArgs().length > 0 ? getScriptArgs()[0] : "/tmp";
        PrintWriter pw = new PrintWriter(new FileWriter(out + "/listing.txt"));
        Memory mem = currentProgram.getMemory();
        Function cur = null;
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) {
            Instruction ins = it.next();
            Function f = getFunctionContaining(ins.getAddress());
            if (f != cur) {
                cur = f;
                pw.println();
                pw.println("==== " + (f == null ? "(no function)" : f.getName() + " @ " + f.getEntryPoint()) + " ====");
            }
            String ops = ins.getDefaultOperandRepresentation(0);
            for (int i = 1; i < ins.getNumOperands(); i++) {
                ops += ", " + ins.getDefaultOperandRepresentation(i);
            }
            // If any operand's PC-relative load reaches a register-window value, annotate it.
            String ann = "";
            for (int opi = 0; opi < ins.getNumOperands(); opi++) {
                Address a = ins.getAddress(opi);
                if (a != null) {
                    try {
                        long v = mem.getInt(a) & 0xffffffffL;
                        if (v >= 0x800000L && v < 0x808000L) ann = "   ; ->[0x" + Long.toHexString(a.getOffset()) + "]=0x" + Long.toHexString(v);
                    } catch (Exception e) { }
                }
            }
            pw.printf("%s  %-7s %s%s%n", ins.getAddress(), ins.getMnemonicString(), ops, ann);
        }
        pw.close();
        println("LISTING -> " + out + "/listing.txt");
    }
}
