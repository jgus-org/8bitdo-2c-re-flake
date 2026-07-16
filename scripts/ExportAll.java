import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.io.FileWriter;
import java.io.PrintWriter;

// Dumps decompiled C, function table, strings, and register-space (0x800000..0x808000) references for offline analysis. Arg 0 = output directory.
public class ExportAll extends GhidraScript {
    @Override
    public void run() throws Exception {
        String out = getScriptArgs().length > 0 ? getScriptArgs()[0] : "/tmp";

        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);

        PrintWriter c = new PrintWriter(new FileWriter(out + "/decomp.c"));
        PrintWriter fns = new PrintWriter(new FileWriter(out + "/functions.txt"));
        FunctionIterator fit = currentProgram.getFunctionManager().getFunctions(true);
        int nf = 0;
        while (fit.hasNext()) {
            Function f = fit.next();
            nf++;
            fns.println(f.getEntryPoint() + "\t" + f.getBody().getNumAddresses() + "\t" + f.getName());
            c.println("// ==== " + f.getEntryPoint() + " " + f.getName() + " ====");
            DecompileResults r = di.decompileFunction(f, 60, monitor);
            if (r != null && r.decompileCompleted()) {
                c.println(r.getDecompiledFunction().getC());
            } else {
                c.println("// <decompile failed: " + (r == null ? "null" : r.getErrorMessage()) + ">");
            }
        }
        c.close();
        fns.close();

        PrintWriter s = new PrintWriter(new FileWriter(out + "/strings.txt"));
        DataIterator dit = currentProgram.getListing().getDefinedData(true);
        int ns = 0;
        while (dit.hasNext()) {
            Data d = dit.next();
            if (d.hasStringValue()) {
                s.println(d.getAddress() + "\t" + d.getValue());
                ns++;
            }
        }
        s.close();

        PrintWriter rr = new PrintWriter(new FileWriter(out + "/regrefs.txt"));
        Address lo = toAddr(0x800000);
        Address hi = toAddr(0x808000);
        ReferenceIterator rit = currentProgram.getReferenceManager().getReferenceIterator(toAddr(0));
        int nr = 0;
        while (rit.hasNext()) {
            Reference ref = rit.next();
            Address to = ref.getToAddress();
            if (to != null && to.compareTo(lo) >= 0 && to.compareTo(hi) < 0) {
                Function f = getFunctionContaining(ref.getFromAddress());
                rr.println(ref.getFromAddress() + "\t" + to + "\t" + ref.getReferenceType()
                    + "\t" + (f == null ? "-" : f.getName()));
                nr++;
            }
        }
        rr.close();

        println("EXPORT functions=" + nf + " strings=" + ns + " regrefs=" + nr + " -> " + out);
    }
}
