import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.listing.InstructionIterator;

public class ReportStats extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            println("BLOCK " + b.getName() + " " + b.getStart() + "-" + b.getEnd());
        }
        int ins = 0;
        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) { it.next(); ins++; }
        println("COUNTS instructions=" + ins
            + " functions=" + currentProgram.getFunctionManager().getFunctionCount()
            + " lang=" + currentProgram.getLanguageID());
    }
}
