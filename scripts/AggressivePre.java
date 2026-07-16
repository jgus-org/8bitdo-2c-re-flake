import ghidra.app.script.GhidraScript;

// preScript: enable heuristics that recover code unreachable from the entry call graph (jump-table targets, pointer-called handlers). Raises coverage on stripped/partly-reached images.
public class AggressivePre extends GhidraScript {
    @Override
    public void run() throws Exception {
        setAnalysisOption(currentProgram, "Aggressive Instruction Finder", "true");
        setAnalysisOption(currentProgram, "Decompiler Switch Analysis", "true");
        setAnalysisOption(currentProgram, "Decompiler Parameter ID", "true");
    }
}
