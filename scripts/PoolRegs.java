import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import java.io.FileWriter;
import java.io.PrintWriter;
import java.util.TreeMap;

// Scans initialized memory for 4-byte-aligned little-endian words whose value lands in the peripheral-register window [0x800000,0x808000) — i.e. the literal-pool constants the code loads to reach hardware. Outputs a sorted count of distinct register addresses. Arg 0 = output dir.
public class PoolRegs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String out = getScriptArgs().length > 0 ? getScriptArgs()[0] : "/tmp";
        long lo = 0x800000L, hi = 0x808000L;
        TreeMap<Long, Integer> hist = new TreeMap<>();
        TreeMap<Long, String> where = new TreeMap<>();
        for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
            if (!b.isInitialized()) continue;
            long start = b.getStart().getOffset();
            long end = b.getEnd().getOffset();
            for (long a = (start + 3) & ~3L; a + 3 <= end; a += 4) {
                Address addr = toAddr(a);
                int v = currentProgram.getMemory().getInt(addr);
                long uv = v & 0xffffffffL;
                if (uv >= lo && uv < hi) {
                    hist.merge(uv, 1, Integer::sum);
                    if (!where.containsKey(uv)) {
                        Function f = getFunctionContaining(addr);
                        where.put(uv, f == null ? "-" : f.getName());
                    }
                }
            }
        }
        PrintWriter pw = new PrintWriter(new FileWriter(out + "/poolregs.txt"));
        for (var e : hist.entrySet()) {
            pw.printf("0x%08x\t%d\t%s%n", e.getKey(), e.getValue(), where.get(e.getKey()));
        }
        pw.close();
        println("POOLREGS distinct=" + hist.size() + " -> " + out + "/poolregs.txt");
    }
}
