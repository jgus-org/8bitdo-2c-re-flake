import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Data;
import ghidra.program.model.listing.DataIterator;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.io.FileWriter;
import java.io.PrintWriter;

// For each defined string, lists the functions that reference it — turning surviving strings into semantic anchors for otherwise-FUN_-named functions. Arg 0 = output dir.
public class StringXrefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String out = getScriptArgs().length > 0 ? getScriptArgs()[0] : "/tmp";
        PrintWriter pw = new PrintWriter(new FileWriter(out + "/string-xrefs.txt"));
        DataIterator dit = currentProgram.getListing().getDefinedData(true);
        int n = 0;
        while (dit.hasNext()) {
            Data d = dit.next();
            if (!d.hasStringValue()) continue;
            String v = d.getValue() == null ? "" : d.getValue().toString().trim();
            if (v.isEmpty()) continue;
            StringBuilder fnList = new StringBuilder();
            ReferenceIterator rit = currentProgram.getReferenceManager().getReferencesTo(d.getAddress());
            java.util.LinkedHashSet<String> fns = new java.util.LinkedHashSet<>();
            while (rit.hasNext()) {
                Reference r = rit.next();
                Function f = getFunctionContaining(r.getFromAddress());
                fns.add(f == null ? r.getFromAddress().toString() : f.getName());
            }
            if (fns.isEmpty()) continue;
            for (String f : fns) { if (fnList.length() > 0) fnList.append(","); fnList.append(f); }
            pw.println(d.getAddress() + "\t" + fnList + "\t" + v.replace("\n", "\\n").replace("\r", ""));
            n++;
        }
        pw.close();
        println("STRINGXREFS strings-with-refs=" + n + " -> " + out + "/string-xrefs.txt");
    }
}
