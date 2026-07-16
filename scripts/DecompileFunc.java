import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

// Decompiles the function containing arg0 (hex address). Prints C.
public class DecompileFunc extends GhidraScript {
    @Override
    public void run() throws Exception {
        long a = Long.parseLong(getScriptArgs()[0].toLowerCase().replace("0x", ""), 16);
        Address addr = toAddr(a);
        Function f = getFunctionContaining(addr);
        if (f == null) {
            println("NO FUNCTION at " + addr);
            return;
        }
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        DecompileResults res = di.decompileFunction(f, 60, monitor);
        println("=== " + f.getName() + " @ " + f.getEntryPoint() + " ===");
        if (res.decompileCompleted())
            println(res.getDecompiledFunction().getC());
        else
            println("DECOMPILE FAILED: " + res.getErrorMessage());
    }
}
